# GrassCRM — app/routers/tasks.py v8.0.1

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import extract
from sqlalchemy.orm import Session as DBSession, joinedload

from app.database import get_db
from app.models import Task, User
from app.schemas import TaskCreate, TaskUpdate
from app.security import get_current_user, is_admin, guard_project
from app.cache import _cache

router = APIRouter()


@router.get("/api/years")
def get_years(db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    from sqlalchemy import text
    if (cached := _cache.get("years")) is not None:
        return cached
    deal_years    = [r[0] for r in db.execute(text("SELECT DISTINCT EXTRACT(YEAR FROM deal_date)::int FROM deals WHERE deal_date IS NOT NULL")).fetchall() if r[0]]
    expense_years = [r[0] for r in db.execute(text("SELECT DISTINCT EXTRACT(YEAR FROM date)::int FROM expenses WHERE date IS NOT NULL")).fetchall() if r[0]]
    from datetime import datetime
    years = sorted(set(deal_years + expense_years), reverse=True) or [datetime.utcnow().year]
    _cache.set("years", years)
    return years


@router.get("/api/tasks")
def get_tasks(
    year:       Optional[int]  = None,
    is_done:    Optional[bool] = None,
    priority:   Optional[str]  = None,
    contact_id: Optional[int]  = None,
    deal_id:    Optional[int]  = None,
    project:    str            = "pokos",
    db:         DBSession      = Depends(get_db),
    user:       dict           = Depends(get_current_user),
):
    guard_project(project, user)
    q = db.query(Task).options(joinedload(Task.contact), joinedload(Task.deal)).order_by(Task.due_date.asc())
    if year:       q = q.filter(extract("year", Task.due_date) == year)
    if is_done is not None: q = q.filter(Task.is_done == is_done)
    if priority:   q = q.filter(Task.priority == priority)
    if contact_id: q = q.filter(Task.contact_id == contact_id)
    if deal_id:    q = q.filter(Task.deal_id == deal_id)
    q = q.filter(Task.project == project)
    if not is_admin(user):
        q = q.filter(Task.assignee == user["sub"])
    users = {u.id: u.name for u in db.query(User).all()}
    today = date.today()
    result = []
    for t in q.all():
        task_dict = {c.name: getattr(t, c.name) for c in t.__table__.columns}
        task_dict["assignee_name"] = users.get(t.assignee, "Не назначен")
        task_dict["contact_name"]  = t.contact.name if t.contact else None
        task_dict["deal_title"]    = t.deal.title if t.deal else None
        task_dict["is_overdue"]    = bool(t.due_date and t.due_date < today and not t.is_done)
        result.append(task_dict)
    return result


@router.post("/api/tasks", status_code=201)
def create_task(task: TaskCreate, db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    new_task = Task(
        title=task.title,
        description=task.description,
        due_date=task.due_date or (date.today() + timedelta(days=1)),
        priority=task.priority,
        status=task.status,
        assignee=task.assignee or user["sub"],
        contact_id=task.contact_id,
        deal_id=task.deal_id,
        project=task.project or "pokos",
    )
    db.add(new_task); db.commit(); db.refresh(new_task)
    _cache.invalidate("tasks")
    return new_task


@router.patch("/api/tasks/{task_id}")
def update_task(task_id: int, task_data: TaskUpdate, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    for key, value in task_data.model_dump(exclude_unset=True).items():
        setattr(task, key, value)
    if task_data.is_done:
        task.status = "Выполнена"
    elif task_data.status == "Выполнена":
        task.is_done = True
    db.commit(); _cache.invalidate("tasks")
    return {"status": "ok"}


@router.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if task:
        db.delete(task); db.commit(); _cache.invalidate("tasks")
