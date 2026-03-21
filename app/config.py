# GrassCRM — app/config.py v8.0.2

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# ── AUTH0 ──────────────────────────────────────────────────────────────────────
AUTH0_DOMAIN   = os.getenv("AUTH0_DOMAIN")
AUTH0_AUDIENCE = os.getenv("AUTH0_AUDIENCE")
CLIENT_ID      = os.getenv("AUTH0_CLIENT_ID")
CLIENT_SECRET  = os.getenv("AUTH0_CLIENT_SECRET")

# ── ПРИЛОЖЕНИЕ ─────────────────────────────────────────────────────────────────
APP_BASE_URL     = os.getenv("APP_BASE_URL", "https://crmpokos.ru").rstrip("/")
CALLBACK_URL     = f"{APP_BASE_URL}/api/auth/callback"
SESSION_SECRET   = os.getenv("SESSION_SECRET", secrets.token_hex(32))
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")
SERVICE_KEY      = os.getenv("SERVICE_KEY")  # для /api/service/* эндпоинтов

# ── ВЛАДЕЛЕЦ ───────────────────────────────────────────────────────────────────
OWNER_EMAIL       = "kossikovskiy@yandex.ru"  # единственный пользователь с доступом к мультипроекту
TELEGRAM_OWNER_ID = os.getenv("TELEGRAM_OWNER_ID", "29635426")  # личный ID для алертов

# ── БАЗА ДАННЫХ ────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")

# ── AI / OPENAI ────────────────────────────────────────────────────────────────
OPENAI_BASE_URL  = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_ACCESS_ID = os.getenv("OPENAI_ACCESS_ID") or os.getenv("OPENAI_API_KEY")
OPENAI_MODEL     = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ── ПРОЧЕЕ ─────────────────────────────────────────────────────────────────────
ROLE_CLAIM    = "https://grass-crm/role"
CACHE_TTL     = 300
TAX_RATE      = float(os.getenv("TAX_RATE", "0.04"))  # 4% УСН "Доходы" для самозанятых
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

# ── ПУТИ ───────────────────────────────────────────────────────────────────────
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/var/www/crm/GCRM-2/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = Path("/var/log/crm")
LOG_DIR.mkdir(parents=True, exist_ok=True)
