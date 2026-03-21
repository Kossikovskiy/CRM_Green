# GrassCRM Backend — main.py v8.0.6
# Этап 4: X-Service-Key защита /api/service/*

from app.config import (
    DATABASE_URL, AUTH0_DOMAIN, AUTH0_AUDIENCE, CLIENT_ID, CLIENT_SECRET,
    APP_BASE_URL, CALLBACK_URL, SESSION_SECRET, INTERNAL_API_KEY,
    OWNER_EMAIL, TELEGRAM_OWNER_ID,
    OPENAI_BASE_URL, OPENAI_ACCESS_ID, OPENAI_MODEL,
    ROLE_CLAIM, CACHE_TTL, TAX_RATE, UPLOAD_DIR, MAX_FILE_SIZE, LOG_DIR,
)
from app.cache import _cache, _Cache
from app.logging_setup import logger, _tg_alert, log_and_alert_errors

import os
import secrets
import time as _time
import shutil
import importlib.util
from pathlib import Path
from datetime import datetime, date, timedelta
from contextlib import asynccontextmanager
from typing import Optional, List
from functools import lru_cache

from fastapi import FastAPI, Depends, HTTPException, status, Request, Header, UploadFile, File as FastAPIFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Date, DateTime, 
    Boolean, ForeignKey, Text, text, MetaData, extract, Double, func
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session as DBSession, joinedload
from pydantic import BaseModel, Field, ConfigDict
import httpx
from jose import jwt, JWTError

# ── 1. КОНФИГ — вынесен в app/config.py ───────────────────────────────────────
# Все переменные импортированы в начале файла через from app.config import ...

# ── 2. КЭШ — вынесен в app/cache.py ──────────────────────────────────────────
# _cache и _Cache импортированы в начале файла через from app.cache import ...

# ── 3. БАЗА ДАННЫХ и МОДЕЛИ — вынесены в app/ ──────────────────────────────────
from app.models import (
    Base,
    User, Service, DealService, ElectricService, DealElectricService,
    DealMaterial, Stage, Contact, Deal, Task, Interaction, DealComment,
    CRMFile, ExpenseCategory, Expense, TaxPayment, Consumable,
    Equipment, EquipmentMaintenance, MaintenanceConsumable,
    DailyPhrase, AiMemory, AiUsageLog, BotFaq, Note, Budget,
)
from app.database import (
    engine, SessionFactory, get_db, get_public_db,
    init_db_structure, seed_initial_data,
)

# ── 4. HELPERS ────────────────────────────────────────────────────────────────
# update_equipment_last_maintenance — перенесён в app/routers/equipment.py

# ── 5. PYDANTIC SCHEMAS — вынесены в app/schemas.py ───────────────────────────
from app.schemas import (
    DealServiceItem, DealElectricServiceItem, DealMaterialItem,
    DealCreate, DealUpdate,
    TaskCreate, TaskUpdate,
    ContactCreate, ContactUpdate,
    ServiceCreate, ServiceUpdate,
    ElectricServiceCreate, ElectricServiceUpdate,
    EquipmentCreate, EquipmentUpdate,
    ConsumableCreate, ConsumableUpdate,
    MaintenanceConsumableItem, MaintenanceCreate, MaintenanceUpdate,
    ExpenseCreate, ExpenseUpdate,
    TaxPaymentCreate, TaxPaymentUpdate,
    InteractionCreate, DealCommentCreate,
    UserTelegramUpdate,
    ServiceAIAgentRequest, AIActionRequest, AiMemorySaveRequest,
    NoteCreate, NoteUpdate,
    BudgetCreate, BudgetUpdate, BudgetResponse,
    EquipmentResponse, MaintenanceDetailResponse, MaintenanceForListResponse,
    ConsumableForMaintResponse, MaintConsumableForDetailResponse,
    EquipmentForMaintResponse,
)

# ── 6. FASTAPI APP ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("App starting (v8.0.5)...")
    init_db_structure()
    _ensure_budget_table()
    _ensure_users_telegram_column()
    _ensure_files_kind_column()
    _ensure_contacts_telegram_columns()
    _ensure_deals_discount_type()
    _ensure_repeat_columns()
    _ensure_user_last_login()
    _ensure_archive_columns()
    _ensure_project_columns()
    _ensure_electric_services_tables()
    _ensure_stages_name_project_unique()
    _ensure_duration_hours()
    with SessionFactory() as db: seed_initial_data(db)
    _seed_electric_stages()
    # Воркеры повторных сделок и архива перенесены в systemd timers:
    # crm-repeats.timer (каждый час) и crm-archive.timer (каждый час)
    yield
    logger.info("App shutting down.")

app = FastAPI(title="GrassCRM API", version="8.0.6", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, https_only=True, same_site="lax")

_startup_time = _time.monotonic()

# Middleware из app/logging_setup.py
app.middleware("http")(log_and_alert_errors)

# ── TELEGRAM АЛЕРТ и HTTP MIDDLEWARE — вынесены в app/logging_setup.py ────────
_CORS_ORIGINS = list({
    APP_BASE_URL,
    "https://xn----8sb2apbbcfhi5f.xn--p1ai",
    "https://xn----8sbgjpqjjbr1b.xn--p1ai",
})
app.add_middleware(CORSMiddleware, allow_origins=_CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ── РОУТЕРЫ ────────────────────────────────────────────────────────────────────
from app.routers import auth, users, services, contacts, tasks, expenses, equipment, deals, files, notes, analytics, admin
for _router in [auth, users, services, contacts, tasks, expenses, equipment, deals, files, notes, analytics, admin]:
    app.include_router(_router.router)
app.include_router(admin.version_router)  # /api/version и /api/service/restart — без X-Service-Key

@lru_cache(maxsize=1)
def get_jwks(): return httpx.get(f"https://{AUTH0_DOMAIN}/.well-known/jwks.json", timeout=10).raise_for_status().json()

# get_db и get_public_db — импортированы из app.database

# ── БЕЗОПАСНОСТЬ — вынесена в app/security.py ─────────────────────────────────
from app.security import (
    get_current_user, is_admin, is_owner, guard_project,
    is_won_stage, is_lost_stage, require_admin,
)

# ── 7. HEALTH CHECK ───────────────────────────────────────────────────────────
@app.get("/api/health")
def health_check(db: DBSession = Depends(get_db)):
    """Публичный healthcheck — статус БД, диск, uptime."""
    # БД
    db_ok = False
    db_error = None
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        db_error = str(e)

    # Диск
    disk = shutil.disk_usage("/")
    disk_used_pct = round(disk.used / disk.total * 100, 1)

    # Uptime
    uptime_sec = int(_time.monotonic() - _startup_time)

    status = "ok" if db_ok else "degraded"
    return {
        "status": status,
        "uptime_sec": uptime_sec,
        "db": {"ok": db_ok, "error": db_error},
        "disk": {
            "total_gb": round(disk.total / 1024**3, 1),
            "used_gb": round(disk.used / 1024**3, 1),
            "free_gb": round(disk.free / 1024**3, 1),
            "used_pct": disk_used_pct,
        },
    }

# ── 8. AUTH, USERS, SERVICES, CONTACTS, TASKS, EXPENSES, EQUIPMENT ───────────
# Все эндпоинты вынесены в app/routers/ и подключены выше через include_router

# Deals — вынесены в app/routers/deals.py

# --- CONTACTS, EXPENSES, EQUIPMENT, TASKS, TAXES ---
# Все эндпоинты вынесены в app/routers/ и подключены через include_router


# ═══════════════════════════════════════════════════════════════════════════════
# НОВЫЕ ФИЧИ v13.0: Аналитика, Экспорт, Бюджет
# ═══════════════════════════════════════════════════════════════════════════════

# ── МИГРАЦИИ и ВОРКЕРЫ — вынесены в app/migrations.py ────────────────────────
from app.migrations import (
    _ensure_budget_table, _ensure_users_telegram_column,
    _ensure_user_last_login, _ensure_repeat_columns, _ensure_duration_hours,
    _ensure_deals_discount_type, _ensure_files_kind_column,
    _ensure_contacts_telegram_columns, _ensure_archive_columns,
    _ensure_project_columns, _ensure_electric_services_tables,
    _ensure_stages_name_project_unique,
    _seed_electric_stages,
)

# ── PYDANTIC для бюджета — импортированы из app.schemas ──────────────────────

# Analytics, budget, export — вынесены в app/routers/analytics.py

# Files — вынесены в app/routers/files.py

# Service panel, AI, version, restart — вынесены в app/routers/admin.py

# Notes, audit-log, bot-faq — вынесены в app/routers/notes.py

@app.get("/{full_path:path}", response_class=FileResponse)
async def serve_frontend(full_path: str):
    path = f"./{full_path.strip()}" if full_path else "./index.html"
    return FileResponse(path if os.path.isfile(path) else "./index.html")

print(f"main.py (v8.0.6) loaded — X-Service-Key защита /api/service/*", flush=True)
