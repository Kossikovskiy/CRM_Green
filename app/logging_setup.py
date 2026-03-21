# GrassCRM — app/logging_setup.py v8.0.1

import os
import logging
import logging.handlers
import threading
import traceback as _tb
from pathlib import Path

from app.config import LOG_DIR, TELEGRAM_OWNER_ID

# ── ЛОГГЕР ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "app.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        ),
        logging.StreamHandler(),  # также в stdout → journald
    ],
)
logger = logging.getLogger("grasscrm")


# ── TELEGRAM АЛЕРТ ────────────────────────────────────────────────────────────
def _tg_alert(text: str):
    """Отправляет сообщение владельцу в личку (fire-and-forget, не блокирует)."""
    import urllib.request
    import json as _json

    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = TELEGRAM_OWNER_ID  # всегда в личку, не в группу
    if not token or not chat_id:
        return

    def _send():
        try:
            payload = _json.dumps({"chat_id": chat_id, "text": text}).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            logger.warning("Telegram alert failed: %s", e)

    threading.Thread(target=_send, daemon=True).start()


# ── HTTP MIDDLEWARE ────────────────────────────────────────────────────────────
async def log_and_alert_errors(request, call_next):
    """Логирует все запросы. При 500 отправляет Telegram алерт."""
    try:
        response = await call_next(request)
        if response.status_code >= 500:
            msg = f"[GrassCRM] 500 ERROR\n{request.method} {request.url.path}"
            logger.error(msg)
            _tg_alert(msg)
        elif response.status_code >= 400:
            logger.warning("%s %s -> %s", request.method, request.url.path, response.status_code)
        else:
            logger.info("%s %s -> %s", request.method, request.url.path, response.status_code)
        return response
    except Exception:
        msg = f"[GrassCRM] CRASH\n{request.method} {request.url.path}\n{_tb.format_exc()[-500:]}"
        logger.exception("Unhandled exception: %s %s", request.method, request.url.path)
        _tg_alert(msg)
        raise
