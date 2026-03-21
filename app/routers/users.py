# GrassCRM — app/routers/users.py v8.0.1

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.database import get_db
from app.models import User, Stage
from app.schemas import UserTelegramUpdate
from app.security import get_current_user, require_admin, is_owner, guard_project
from app.cache import _cache

router = APIRouter()


@router.get("/api/me")
def get_me(user: dict = Depends(get_current_user)):
    return {**user, "is_owner": is_owner(user)}


@router.get("/api/projects")
def get_projects(user: dict = Depends(get_current_user)):
    """Возвращает список доступных проектов для текущего пользователя."""
    projects = [{"id": "pokos", "name": "Покос Ропша", "theme": "pokos"}]
    if is_owner(user):
        projects.append({"id": "electric", "name": "Электрика", "theme": "electric"})
    return projects


@router.get("/api/users")
def get_users(db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    users = db.query(User).order_by(User.name).all()
    return [
        {
            "id":         u.id,
            "username":   u.username,
            "name":       u.name,
            "email":      u.email,
            "role":       u.role,
            "telegram_id": u.telegram_id,
            "last_login": u.last_login.isoformat() if u.last_login else None,
        }
        for u in users
    ]


@router.get("/api/users/by-telegram/{telegram_id}")
def get_user_by_telegram(telegram_id: str, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    return user


@router.patch("/api/users/{user_id}/telegram")
def set_user_telegram_id(user_id: str, data: UserTelegramUpdate, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    new_tid = (data.telegram_id or "").strip() or None
    if new_tid:
        conflict = db.query(User).filter(User.telegram_id == new_tid, User.id != user_id).first()
        if conflict:
            raise HTTPException(400, "Этот Telegram ID уже привязан к другому пользователю")
    user.telegram_id = new_tid
    db.commit()
    db.refresh(user)
    return user


@router.get("/api/stages")
def get_stages(project: str = "pokos", db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    guard_project(project, user)
    return db.query(Stage).filter(Stage.project == project).order_by(Stage.order).all()


@router.post("/api/cache/invalidate")
def invalidate_cache(_=Depends(get_current_user)):
    _cache.invalidate("all")
    return {"status": "ok"}
