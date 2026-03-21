# GrassCRM — app/security.py v8.0.2

from functools import lru_cache
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, Header, Request

from app.config import AUTH0_DOMAIN, INTERNAL_API_KEY, OWNER_EMAIL, SERVICE_KEY


# ── JWKS (кэшируется на весь срок жизни процесса) ─────────────────────────────
@lru_cache(maxsize=1)
def get_jwks():
    return (
        httpx.get(f"https://{AUTH0_DOMAIN}/.well-known/jwks.json", timeout=10)
        .raise_for_status()
        .json()
    )


# ── АУТЕНТИФИКАЦИЯ ────────────────────────────────────────────────────────────
def get_current_user(
    req: Request,
    x_internal_api_key: Optional[str] = Header(None, alias="X-Internal-API-Key"),
):
    # Внутренние сервисы (Telegram-бот) — по API-ключу
    if INTERNAL_API_KEY and x_internal_api_key == INTERNAL_API_KEY:
        return {"sub": "internal-bot", "name": "Telegram Bot", "role": "Admin"}

    # Обычные пользователи — по сессии
    if user := req.session.get("user"):
        return user

    raise HTTPException(status_code=401, detail="Not authenticated")


# ── РОЛИ ──────────────────────────────────────────────────────────────────────
def is_admin(user: dict) -> bool:
    return (user.get("role") or "").strip().lower() == "admin"


def is_owner(user: dict) -> bool:
    return (user.get("email") or "").strip().lower() == OWNER_EMAIL.lower()


def require_admin(user: dict = Depends(get_current_user)):
    if not is_admin(user):
        raise HTTPException(403, "Доступ запрещён: требуется роль Admin")
    return user


# ── SERVICE KEY ───────────────────────────────────────────────────────────────
def require_service_key(x_service_key: Optional[str] = Header(None, alias="X-Service-Key")):
    """Защита служебных эндпоинтов /api/service/*.
    Принимает либо X-Service-Key, либо X-Internal-API-Key (для совместимости с ботом).
    Если SERVICE_KEY не задан в .env — проверка пропускается (режим разработки).
    """
    if not SERVICE_KEY:
        return  # не задан — пропускаем (dev-режим)
    if x_service_key == SERVICE_KEY:
        return
    raise HTTPException(403, "Требуется X-Service-Key")


# ── ПРОЕКТЫ ───────────────────────────────────────────────────────────────────
def guard_project(project: str, user: dict):
    """Бросает 403 если не-owner пытается получить доступ к проекту electric."""
    if project == "electric" and not is_owner(user):
        raise HTTPException(403, "Доступ к проекту electric запрещён")


# ── ЭТАПЫ ─────────────────────────────────────────────────────────────────────
def is_won_stage(stage) -> bool:
    """Этап считается выигранным если финальный и название содержит 'успешн' или 'выполнен'."""
    name = (stage.name or "").lower()
    return stage.is_final and ("успешн" in name or "выполнен" in name)


def is_lost_stage(stage) -> bool:
    return stage.is_final and not is_won_stage(stage)
