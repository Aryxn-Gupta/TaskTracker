from fastapi import FastAPI, Depends, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from . import models, database
from datetime import datetime, timedelta

# Initialize Database
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI()
templates = Jinja2Templates(directory="frontend")
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# ===== ADMIN CREDENTIALS =====
ADMIN_EMAIL = "admin@tasktracker.com"
ADMIN_PASSWORD = "admin123"
# ===== CHANGE THESE TO YOUR DESIRED ADMIN EMAIL AND PASSWORD =====

# --- AUTH ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    # Check for error messages in query params
    error = request.query_params.get("error")
    return templates.TemplateResponse("index.html", {"request": request, "error": error})

@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    
    # Check if user exists AND password matches
    if not user or user.password_hash != password:
        return RedirectResponse(url="/?error=Invalid Credentials", status_code=303)
    
    # Check if user is admin
    if email == ADMIN_EMAIL:
        response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    else:
        response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    
    response.set_cookie(key="user_email", value=email)
    return response

@app.post("/register")
async def register(email: str = Form(...), password: str = Form(...), db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    
    # Check if user already exists
    if user:
        return RedirectResponse(url="/?error=Email already registered", status_code=303)
    
    # Create new user
    new_user = models.User(email=email, password_hash=password)
    db.add(new_user)
    db.commit()
    
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="user_email", value=email)
    return response

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("user_email")
    return response

# --- DASHBOARD & ROUTES ---
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(database.get_db)):
    user_email = request.cookies.get("user_email")
    if not user_email: return RedirectResponse(url="/")
    
    user = db.query(models.User).filter(models.User.email == user_email).first()
    if not user: return RedirectResponse(url="/")

    tasks = db.query(models.Task).filter(models.Task.owner_id == user.id).order_by(models.Task.due_date.asc()).all()
    
    today = datetime.now().date()
    upcoming_tasks = [t for t in tasks if t.due_date and t.due_date.date() > today and t.status != "Completed"][:3]

    stats = {
        "total": len(tasks),
        "pending": len([t for t in tasks if t.status == "Pending"]),
        "completed": len([t for t in tasks if t.status == "Completed"]),
        "completion_rate": int((len([t for t in tasks if t.status == "Completed"]) / len(tasks)) * 100) if tasks else 0
    }
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user, "tasks": tasks, "stats": stats, "upcoming": upcoming_tasks
    })

@app.get("/schedule", response_class=HTMLResponse)
async def schedule(request: Request, db: Session = Depends(database.get_db)):
    user_email = request.cookies.get("user_email")
    if not user_email: return RedirectResponse(url="/")
    
    user = db.query(models.User).filter(models.User.email == user_email).first()
    if not user: return RedirectResponse(url="/")

    tasks = db.query(models.Task).filter(models.Task.owner_id == user.id).all()
    
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    
    overdue, today_tasks, tomorrow_tasks, upcoming = [], [], [], []

    for t in tasks:
        try:
            if not t.due_date: continue
            t_date = t.due_date.date()
            if t_date < today and t.status != "Completed": overdue.append(t)
            elif t_date == today: today_tasks.append(t)
            elif t_date == tomorrow: tomorrow_tasks.append(t)
            elif t_date > tomorrow: upcoming.append(t)
        except: continue

    timeline = {"overdue": overdue, "today": today_tasks, "tomorrow": tomorrow_tasks, "upcoming": upcoming}
    
    return templates.TemplateResponse("schedule.html", {
        "request": request, "user": user, "timeline": timeline
    })

@app.get("/settings", response_class=HTMLResponse)
async def settings(request: Request, db: Session = Depends(database.get_db)):
    user_email = request.cookies.get("user_email")
    if not user_email: return RedirectResponse(url="/")
    user = db.query(models.User).filter(models.User.email == user_email).first()
    return templates.TemplateResponse("settings.html", {"request": request, "user": user})

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: Session = Depends(database.get_db)):
    user_email = request.cookies.get("user_email")
    if not user_email: return RedirectResponse(url="/")
    
    user = db.query(models.User).filter(models.User.email == user_email).first()
    if not user: return RedirectResponse(url="/")
    
    # Check if user is admin
    if user.email != ADMIN_EMAIL:
        return RedirectResponse(url="/dashboard?error=Access Denied: You are not authorized to access the admin panel", status_code=303)
    
    # Get all users
    users = db.query(models.User).all()
    return templates.TemplateResponse("admin.html", {"request": request, "user": user, "users": users})

# --- ACTIONS ---
@app.post("/tasks/add")
async def add_task(request: Request, title: str = Form(...), due_date: str = Form(...), db: Session = Depends(database.get_db)):
    user_email = request.cookies.get("user_email")
    if not user_email: return RedirectResponse(url="/")

    user = db.query(models.User).filter(models.User.email == user_email).first()
    if not user: return RedirectResponse(url="/") # Strict check now
    
    try:
        dt_obj = datetime.strptime(due_date, "%Y-%m-%d")
    except:
        dt_obj = datetime.now()

    new_task = models.Task(title=title, due_date=dt_obj, owner_id=user.id)
    db.add(new_task)
    db.commit()
    
    referer = request.headers.get("referer")
    if referer and "schedule" in referer: return RedirectResponse(url="/schedule", status_code=303)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/tasks/complete/{task_id}")
async def complete_task(request: Request, task_id: int, db: Session = Depends(database.get_db)):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if task:
        task.status = "Completed"
        db.commit()
    referer = request.headers.get("referer")
    if referer and "schedule" in referer: return RedirectResponse(url="/schedule", status_code=303)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/tasks/delete/{task_id}")
async def delete_task(request: Request, task_id: int, db: Session = Depends(database.get_db)):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if task:
        db.delete(task)
        db.commit()
    referer = request.headers.get("referer")
    if referer and "schedule" in referer: return RedirectResponse(url="/schedule", status_code=303)
    return RedirectResponse(url="/dashboard", status_code=303)
# --- ADMIN API ROUTES ---
@app.get("/admin/api/users-with-stats")
async def get_users_with_stats(db: Session = Depends(database.get_db)):
    users = db.query(models.User).all()
    
    users_data = []
    for user in users:
        tasks = db.query(models.Task).filter(models.Task.owner_id == user.id).all()
        completed_count = len([t for t in tasks if t.status == "Completed"])
        pending_count = len([t for t in tasks if t.status == "Pending"])
        
        users_data.append({
            "id": user.id,
            "email": user.email,
            "total_tasks": len(tasks),
            "completed_tasks": completed_count,
            "pending_tasks": pending_count
        })
    
    return {"success": True, "users": users_data}

@app.post("/admin/verify-password")
async def verify_admin_password(password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        return JSONResponse({"success": True, "message": "Password verified"})
    else:
        return JSONResponse({"success": False, "message": "Invalid admin password"}, status_code=401)

@app.get("/admin/api/user/{user_id}/tasks")
async def get_user_tasks(user_id: int, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        return JSONResponse({"success": False, "message": "User not found"}, status_code=404)
    
    tasks = db.query(models.Task).filter(models.Task.owner_id == user_id).order_by(models.Task.due_date.asc()).all()
    
    # Convert tasks to dict format
    tasks_data = [
        {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "created_at": task.created_at.isoformat() if task.created_at else None
        }
        for task in tasks
    ]
    
    return {
        "success": True,
        "user_email": user.email,
        "tasks": tasks_data
    }