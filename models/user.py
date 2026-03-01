"""
Модель пользователей — добавить в models/database.py
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime
from models.database import Base


class User(Base):
    __tablename__ = "users"

    id         = Column(Integer, primary_key=True)
    username   = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    full_name  = Column(String(100), default="")
    role       = Column(String(20), default="user")   # admin | manager | user
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
