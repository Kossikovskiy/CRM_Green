"""
Модуль авторизации — JWT токены + зашифрованные пароли
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# ── Настройки ────────────────────────────────────────────────
SECRET_KEY      = os.getenv("SECRET_KEY", "green-crm-super-secret-key-change-me-2025")
ALGORITHM       = "HS256"
TOKEN_TTL_HOURS = 8

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer      = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(username: str, role: str = "user") -> str:
    expires = datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)
    payload = {"sub": username, "role": role, "exp": expires, "iat": datetime.utcnow()}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer)
) -> dict:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен недействителен или истёк. Войдите снова.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"username": payload["sub"], "role": payload.get("role", "user")}


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Требуется роль admin.")
    return current_user
