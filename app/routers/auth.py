# GrassCRM — app/routers/auth.py v8.0.1

import secrets
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import AUTH0_DOMAIN, AUTH0_AUDIENCE, CLIENT_ID, CLIENT_SECRET, CALLBACK_URL, APP_BASE_URL
from app.database import SessionFactory
from app.models import User

router = APIRouter()


@router.get("/api/auth/login")
def login(req: Request):
    state = secrets.token_urlsafe(16)
    req.session["oauth_state"] = state
    return RedirectResponse(
        f"https://{AUTH0_DOMAIN}/authorize"
        f"?response_type=code&client_id={CLIENT_ID}"
        f"&redirect_uri={CALLBACK_URL}"
        f"&scope=openid%20profile%20email"
        f"&audience={AUTH0_AUDIENCE}"
        f"&state={state}"
    )


@router.get("/api/auth/callback")
def callback(req: Request, code: str = None, state: str = None, error: str = None):
    if error:
        return RedirectResponse(f"/?auth_error={error}")
    if not code or state != req.session.pop("oauth_state", None):
        raise HTTPException(400, "Invalid state or no code")

    with httpx.Client() as c:
        tokens = c.post(
            f"https://{AUTH0_DOMAIN}/oauth/token",
            json={
                "grant_type":    "authorization_code",
                "client_id":     CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code":          code,
                "redirect_uri":  CALLBACK_URL,
            },
        ).raise_for_status().json()
        profile = c.get(
            f"https://{AUTH0_DOMAIN}/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        ).raise_for_status().json()

    user_id   = profile.get("sub")
    user_name = profile.get("name") or profile.get("nickname") or user_id

    with SessionFactory() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            db.add(User(id=user_id, name=user_name, email=profile.get("email"), last_login=datetime.utcnow()))
        else:
            user.name, user.email = user_name, profile.get("email")
            user.last_login = datetime.utcnow()
        db.commit()

    # Роль берём из БД (задаётся вручную в Supabase: Admin / User)
    with SessionFactory() as _db:
        _u        = _db.query(User).filter(User.id == user_id).first()
        user_role = (_u.role or "User") if _u else "User"

    req.session["user"] = {
        "sub":   user_id,
        "name":  user_name,
        "role":  user_role,
        "email": profile.get("email", ""),
    }
    return RedirectResponse("/")


@router.get("/api/auth/logout")
def logout(req: Request):
    req.session.clear()
    return RedirectResponse(
        f"https://{AUTH0_DOMAIN}/v2/logout?client_id={CLIENT_ID}&returnTo={APP_BASE_URL}"
    )
