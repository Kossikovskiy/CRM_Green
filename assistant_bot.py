# -*- coding: utf-8 -*-
"""
GreenCRM Assistant Bot — личный AI-ассистент владельца.

Что умеет:
  1. 🧾 Фото чека → считывает OCR через AI и заносит расход в CRM
  2. 💬 Переписка с клиентом (текст) → AI извлекает данные и создаёт сделку
  3. ✅ Создание задач — просто напишите "задача: ..."
  4. 📸 Фото ДО/ПОСЛЕ → привязывает к последней активной сделке
  5. 🎤 Голосовые сообщения → расшифровывает и обрабатывает как текст

Использует отдельный токен: TELEGRAM_ASSISTANT_BOT_TOKEN
Работает только с авторизованными пользователями (TELEGRAM_CHAT_ID).
"""

import asyncio
import json
import logging
import os
import re
import tempfile
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

# faster-whisper: локальная расшифровка голоса
try:
    from faster_whisper import WhisperModel as _WhisperModel
    _whisper_instance = None
    FASTER_WHISPER_OK = True
except ImportError:
    FASTER_WHISPER_OK = False
    _whisper_instance = None
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("assistant_bot")

# ════════════════════════════════════════
#  ⚙️  КОНФИГ
# ════════════════════════════════════════

ASSISTANT_BOT_TOKEN = os.getenv("TELEGRAM_ASSISTANT_BOT_TOKEN")
INTERNAL_API_KEY    = os.getenv("INTERNAL_API_KEY")
API_BASE_URL        = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api")

# Основной AI: DeepSeek (работает из России)
OPENAI_BASE_URL  = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
OPENAI_ACCESS_ID = os.getenv("OPENAI_ACCESS_ID") or os.getenv("OPENAI_API_KEY")
OPENAI_MODEL     = os.getenv("OPENAI_MODEL", "deepseek-chat")

# Vision: DeepSeek тоже поддерживает картинки и работает из России
OPENAI_VISION_URL   = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
OPENAI_VISION_KEY   = OPENAI_ACCESS_ID
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "deepseek-chat")

# Whisper: локальный faster-whisper, не требует внешних API
# pip install faster-whisper  (скачает модель ~150 МБ при первом запуске)
WHISPER_MODEL_SIZE  = os.getenv("WHISPER_MODEL_SIZE", "small")

# Список chat_id, которым разрешено пользоваться ботом
_raw_allowed = os.getenv("TELEGRAM_CHAT_ID", "")
ALLOWED_CHAT_IDS: set = {
    int(x.strip()) for x in _raw_allowed.split(",") if x.strip().isdigit()
}

if not ASSISTANT_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_ASSISTANT_BOT_TOKEN не задан в .env")
if not INTERNAL_API_KEY:
    raise RuntimeError("INTERNAL_API_KEY не задан в .env")
if not OPENAI_ACCESS_ID:
    raise RuntimeError("OPENAI_ACCESS_ID / OPENAI_API_KEY не задан в .env")

API_HEADERS = {"X-Internal-API-Key": INTERNAL_API_KEY}

# ════════════════════════════════════════
#  🔒  АВТОРИЗАЦИЯ
# ════════════════════════════════════════

def _is_allowed(update: Update) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True  # если не задан список — пропускаем всех (осторожно!)
    return update.effective_chat.id in ALLOWED_CHAT_IDS

async def _deny(update: Update):
    await update.effective_message.reply_text("⛔ Нет доступа.")

# ════════════════════════════════════════
#  🌐  CRM API HELPERS
# ════════════════════════════════════════

async def _crm_get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{API_BASE_URL}{path}", headers=API_HEADERS)
        r.raise_for_status()
        return r.json()

async def _crm_post(path: str, payload: Dict) -> Any:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{API_BASE_URL}{path}", headers=API_HEADERS, json=payload)
        r.raise_for_status()
        return r.json() if r.text else {}

async def _crm_patch(path: str, payload: Dict) -> Any:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.patch(f"{API_BASE_URL}{path}", headers=API_HEADERS, json=payload)
        r.raise_for_status()
        return r.json() if r.text else {}

async def _crm_upload_file(path: str, file_bytes: bytes, filename: str,
                            extra_fields: Dict[str, str] = None) -> Any:
    """Загрузить файл через multipart/form-data на /api/files."""
    import io
    data = httpx.AsyncClient()
    async with httpx.AsyncClient(timeout=30) as c:
        files = {"file": (filename, io.BytesIO(file_bytes), "image/jpeg")}
        form  = extra_fields or {}
        r = await c.post(
            f"{API_BASE_URL}{path}",
            headers=API_HEADERS,
            files=files,
            data=form,
        )
        r.raise_for_status()
        return r.json() if r.text else {}

# ════════════════════════════════════════
#  🤖  AI HELPERS
# ════════════════════════════════════════

async def _ask_ai_text(system: str, user: str) -> str:
    url = f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": OPENAI_MODEL,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }
    headers = {"Authorization": f"Bearer {OPENAI_ACCESS_ID}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(url, json=payload, headers=headers)
    if not r.is_success:
        raise RuntimeError(f"AI error {r.status_code}: {r.text[:300]}")
    return ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content", "")


async def _ask_ai_vision(image_b64: str, prompt: str) -> str:
    """Запрос к vision-модели с base64-изображением. Всегда идёт на OpenAI (не DeepSeek)."""
    url = f"{OPENAI_VISION_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": OPENAI_VISION_MODEL,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
    }
    headers = {"Authorization": f"Bearer {OPENAI_VISION_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(url, json=payload, headers=headers)
    if not r.is_success:
        raise RuntimeError(f"Vision AI error {r.status_code}: {r.text[:300]}")
    return ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content", "")


def _get_whisper() -> "_WhisperModel":
    """Ленивая инициализация faster-whisper."""
    global _whisper_instance
    if _whisper_instance is None:
        logger.info(f"Загружаю Whisper '{WHISPER_MODEL_SIZE}'...")
        _whisper_instance = _WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        logger.info("Whisper готов.")
    return _whisper_instance


async def _transcribe_voice(file_bytes: bytes) -> str:
    """Расшифровать голосовое локально через faster-whisper."""
    if not FASTER_WHISPER_OK:
        raise RuntimeError(
            "faster-whisper не установлен.\n"
            "Выполните на сервере: pip install faster-whisper"
        )
    import asyncio as _aio
    def _run(data: bytes) -> str:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            segs, _ = _get_whisper().transcribe(path, language="ru", beam_size=5)
            return " ".join(s.text for s in segs).strip()
        finally:
            try: os.remove(path)
            except: pass
    loop = _aio.get_event_loop()
    return await loop.run_in_executor(None, _run, file_bytes)


def _parse_json_safe(text: str) -> Optional[Dict]:
    text = (text or "").strip()
    # strip fenced code blocks
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = text.replace("```", "")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end+1])
    except Exception:
        return None

# ════════════════════════════════════════
#  📋  SYSTEM PROMPTS
# ════════════════════════════════════════

RECEIPT_PROMPT = """
Ты OCR-ассистент. Тебе дано фото чека или квитанции.
Верни СТРОГО JSON без markdown-обёрток:
{
  "name": "название товара/услуги (строка)",
  "amount": число (только цифры, без валюты),
  "date": "YYYY-MM-DD или null если не разобрать",
  "category": "одна из: Топливо, Расходники, Оборудование, Транспорт, Прочее"
}
Если не можешь разобрать чек — верни {"error": "описание проблемы"}.
""".strip()

DEAL_FROM_CHAT_PROMPT = """
Ты CRM-ассистент компании по уходу за газонами и участками.
Тебе дана переписка с клиентом. Извлеки данные для создания сделки.
Верни СТРОГО JSON без markdown-обёрток:
{
  "contact_name": "имя клиента или null",
  "phone": "номер телефона в формате +7XXXXXXXXXX или null",
  "address": "адрес объекта или null",
  "title": "краткое название сделки (например: Покос 10 сот, Ивановка)",
  "notes": "детали: площадь, состояние газона, пожелания клиента",
  "service_keywords": ["список ключевых слов услуг"]
}
Если данных недостаточно — всё равно верни JSON с тем, что есть (null для неизвестных полей).
""".strip()

TASK_PROMPT = """
Ты CRM-ассистент. Тебе дан текст заметки или задачи.
Извлеки из него структурированную задачу. Верни СТРОГО JSON:
{
  "title": "краткий заголовок задачи",
  "description": "полное описание или null",
  "due_date": "YYYY-MM-DD или null",
  "priority": "Обычный или Высокий или Критический",
  "contact_name": "имя контакта если упомянут или null"
}
""".strip()

# ════════════════════════════════════════
#  🔍  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ════════════════════════════════════════

async def _get_first_stage_id() -> Optional[int]:
    try:
        stages = await _crm_get("/stages")
        for s in stages:
            if not s.get("is_final"):
                return s["id"]
        return stages[0]["id"] if stages else None
    except Exception:
        return None

async def _find_or_create_contact(name: str, phone: Optional[str] = None) -> Optional[int]:
    """Найти контакт по имени/телефону или создать новый."""
    try:
        contacts = await _crm_get("/contacts")
        # Поиск по телефону
        if phone:
            for c in contacts:
                if (c.get("phone") or "").replace(" ", "") == phone.replace(" ", ""):
                    return c["id"]
        # Поиск по имени (нечёткий)
        if name:
            norm = name.lower().strip()
            for c in contacts:
                if (c.get("name") or "").lower().strip() == norm:
                    return c["id"]
        # Создать новый
        payload = {"name": name}
        if phone:
            payload["phone"] = phone
        created = await _crm_post("/contacts", payload)
        return created.get("id")
    except Exception as e:
        logger.warning(f"_find_or_create_contact error: {e}")
        return None

# Статусы сделок, которые считаются "активными" для прикрепления фото
ACTIVE_STAGE_NAMES = {"согласовать", "в работе", "ожидание", "новая", "новый"}

async def _get_active_deals() -> List[Dict]:
    """Вернуть список активных сделок (согласовать / в работе / ожидание)."""
    try:
        deals = await _crm_get("/deals")
        active = [
            d for d in deals
            if not d.get("stage_is_final")
            and (d.get("stage_name") or "").lower().strip() in ACTIVE_STAGE_NAMES
        ]
        if not active:
            # Фолбэк: все незакрытые
            active = [d for d in deals if not d.get("stage_is_final")]
        return sorted(active, key=lambda d: d.get("updated_at") or d.get("created_at") or "", reverse=True)[:8]
    except Exception as e:
        logger.warning(f"_get_active_deals error: {e}")
        return []

async def _get_expense_categories() -> List[Dict]:
    try:
        return await _crm_get("/expense-categories")
    except Exception:
        return []

def _match_category_id(ai_cat: str, categories: List[Dict]) -> Optional[int]:
    """Сопоставить AI-категорию с реальными категориями расходов."""
    mapping = {
        "топливо":       ["топлив", "бензин", "солярк", "fuel"],
        "расходники":    ["расходник", "запчаст", "масло", "фильтр", "нож", "леска"],
        "оборудование":  ["оборудован", "техник", "инструмент", "купл"],
        "транспорт":     ["транспорт", "доставк", "перевоз"],
        "прочее":        [],
    }
    ai_lower = (ai_cat or "").lower()
    for key, triggers in mapping.items():
        if key in ai_lower or any(t in ai_lower for t in triggers):
            # Ищем среди реальных категорий
            for cat in categories:
                cat_name = (cat.get("name") or "").lower()
                if key in cat_name or any(t in cat_name for t in triggers):
                    return cat["id"]
    # Вернуть первую «прочее» или просто первую
    for cat in categories:
        if "проч" in (cat.get("name") or "").lower():
            return cat["id"]
    return categories[0]["id"] if categories else None


INTENT_PROMPT = """
Ты — ассистент CRM-системы газонокосилочной компании.
Определи намерение пользователя. Верни СТРОГО JSON без markdown:
{
  "intent": "task | deal | expense | unknown",
  "confidence": 0.0..1.0
}

intent = task    — надо что-то сделать/напомнить/позвонить/задача/встреча
intent = deal    — клиент/заявка/покос/работа на участке/адрес/переписка с клиентом
intent = expense — потратил/купил/расход/заправка/чек/оплатил/стоит X рублей
intent = unknown — не понятно

Примеры:
"Позвони Иванову завтра"                      → {"intent":"task","confidence":0.95}
"Клиент из Ропши хочет покос 15 соток"        → {"intent":"deal","confidence":0.97}
"Заправил на 2500р"                            → {"intent":"expense","confidence":0.98}
"Купил леску 500р"                             → {"intent":"expense","confidence":0.95}
"Надо купить масло для триммера"               → {"intent":"task","confidence":0.8}
""".strip()

EXPENSE_TEXT_PROMPT = """
Извлеки расход из текста. Верни СТРОГО JSON без markdown:
{
  "name": "название расхода",
  "amount": число или null,
  "date": "YYYY-MM-DD или null",
  "category": "Топливо | Расходники | Оборудование | Транспорт | Прочее"
}
Примеры:
"заправил на 2500" → {"name":"Заправка","amount":2500,"date":null,"category":"Топливо"}
"купил леску 500р" → {"name":"Леска","amount":500,"date":null,"category":"Расходники"}
""".strip()


async def _detect_intent(text: str) -> dict:
    """AI определяет что хочет пользователь. Возвращает {intent, confidence}."""
    try:
        raw = await _ask_ai_text(INTENT_PROMPT, text)
        data = _parse_json_safe(raw)
        if data and data.get("intent"):
            return data
    except Exception as e:
        logger.warning(f"Intent detection error: {e}")
    return {"intent": "unknown", "confidence": 0.0}


async def _handle_quick_expense_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Создать расход из текста (без фото). AI извлекает название и сумму."""
    try:
        raw = await _ask_ai_text(EXPENSE_TEXT_PROMPT, text)
        data = _parse_json_safe(raw)

        if not data or not data.get("amount"):
            context.user_data["pending_expense"] = {
                "name": text[:100], "amount": 0.0,
                "date": date.today().isoformat(), "category": "Прочее",
            }
            context.user_data["awaiting"] = "expense_name"
            await update.effective_message.reply_text(
                f"💸 Расход: <b>{text[:100]}</b>\n"
                "Не смог распознать сумму — введи название и сумму через запятую\n"
                "Например: <i>Бензин, 2500</i>",
                parse_mode="HTML",
            )
            return

        categories = await _get_expense_categories()
        cat_id = _match_category_id(data.get("category", "Прочее"), categories)
        cat_name = next((c["name"] for c in categories if c["id"] == cat_id), data.get("category", "Прочее"))

        context.user_data["pending_expense"] = {
            "name":     data.get("name") or text[:100],
            "amount":   float(data["amount"]),
            "date":     data.get("date") or date.today().isoformat(),
            "category": cat_name,
        }
        exp = context.user_data["pending_expense"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Сохранить",           callback_data="exp_confirm")],
            [InlineKeyboardButton("✏️ Изменить название",   callback_data="exp_edit_name")],
            [InlineKeyboardButton("❌ Отмена",              callback_data="exp_cancel")],
        ])
        await update.effective_message.reply_text(
            f"💸 <b>Расход:</b>\n\n"
            f"📌 {exp['name']}\n"
            f"💰 <b>{exp['amount']} ₽</b>\n"
            f"📅 {exp['date']}\n"
            f"🗂 {cat_name}",
            reply_markup=kb, parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Quick expense text error")
        await update.effective_message.reply_text(f"❌ Ошибка: {e}")

# ════════════════════════════════════════
#  /start — справка
# ════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return await _deny(update)
    await update.message.reply_text(
        "👋 <b>GreenCRM Ассистент</b>\n\n"
        "Что я умею:\n\n"
        "🧾 <b>Фото чека</b> → распознаю и заношу расход\n"
        "💬 <b>Переписка с клиентом</b> → создаю сделку\n"
        "✅ <b>«Задача: текст»</b> → создаю задачу\n"
        "📸 <b>Фото с подписью «до» или «после»</b> → прикрепляю к сделке\n"
        "🎤 <b>Голосовое</b> → расшифрую и обработаю\n\n"
        "Просто отправь нужное — сам разберусь.",
        parse_mode="HTML",
    )

# ════════════════════════════════════════
#  🧾  ЧЕКИ → РАСХОДЫ
# ════════════════════════════════════════

async def _handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE, photo_bytes: bytes):
    """Распознать чек и занести расход."""
    msg = await update.effective_message.reply_text("🔍 Читаю чек…")
    try:
        import base64
        b64 = base64.b64encode(photo_bytes).decode()
        raw = await _ask_ai_vision(b64, RECEIPT_PROMPT)
        data = _parse_json_safe(raw)

        if not data or "error" in data:
            err = (data or {}).get("error", raw[:200])
            await msg.edit_text(f"❌ Не смог разобрать чек: {err}")
            return

        name   = data.get("name") or "Расход (чек)"
        amount = data.get("amount")
        dt     = data.get("date") or date.today().isoformat()
        ai_cat = data.get("category", "Прочее")

        if not amount:
            await msg.edit_text("❌ Не удалось распознать сумму на чеке.")
            return

        categories = await _get_expense_categories()
        cat_id = _match_category_id(ai_cat, categories)
        cat_name = next((c["name"] for c in categories if c["id"] == cat_id), ai_cat)

        # Показываем пользователю что нашли, предлагаем подтвердить
        context.user_data["pending_expense"] = {
            "name": name, "amount": float(amount),
            "date": dt, "category": cat_name,
        }
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Сохранить", callback_data="exp_confirm")],
            [InlineKeyboardButton("✏️ Изменить название", callback_data="exp_edit_name")],
            [InlineKeyboardButton("❌ Отмена", callback_data="exp_cancel")],
        ])
        await msg.edit_text(
            f"📋 <b>Распознан расход:</b>\n\n"
            f"📌 Название: <b>{name}</b>\n"
            f"💰 Сумма: <b>{amount} ₽</b>\n"
            f"📅 Дата: <b>{dt}</b>\n"
            f"🗂 Категория: <b>{cat_name}</b>",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Receipt handling error")
        await msg.edit_text(f"❌ Ошибка: {e}")


async def cb_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data

    if action == "exp_cancel":
        context.user_data.pop("pending_expense", None)
        await query.edit_message_text("Отменено.")
        return

    if action == "exp_confirm":
        exp = context.user_data.pop("pending_expense", None)
        if not exp:
            await query.edit_message_text("Нет данных для сохранения.")
            return
        try:
            await _crm_post("/expenses", exp)
            await query.edit_message_text(
                f"✅ Расход <b>{exp['name']}</b> на <b>{exp['amount']} ₽</b> сохранён.",
                parse_mode="HTML",
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка сохранения: {e}")
        return

    if action == "exp_edit_name":
        context.user_data["awaiting"] = "expense_name"
        await query.edit_message_text("Введите новое название расхода:")
        return

# ════════════════════════════════════════
#  💬  ПЕРЕПИСКА → СДЕЛКА
# ════════════════════════════════════════

async def _handle_deal_from_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    msg = await update.effective_message.reply_text("🔄 Анализирую переписку…")
    try:
        raw = await _ask_ai_text(DEAL_FROM_CHAT_PROMPT, text)
        data = _parse_json_safe(raw)

        if not data:
            await msg.edit_text("❌ Не удалось разобрать переписку. Попробуйте отформатировать чище.")
            return

        contact_name = data.get("contact_name") or "Неизвестный клиент"
        phone  = data.get("phone")
        title  = data.get("title") or f"Заявка от {contact_name}"
        notes  = data.get("notes") or ""
        addr   = data.get("address") or ""

        context.user_data["pending_deal"] = {
            "contact_name": contact_name,
            "phone": phone,
            "title": title,
            "notes": notes,
            "address": addr,
        }
        phone_str = phone or "не указан"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Создать сделку", callback_data="deal_confirm")],
            [InlineKeyboardButton("❌ Отмена", callback_data="deal_cancel")],
        ])
        await msg.edit_text(
            f"📋 <b>Найдена заявка:</b>\n\n"
            f"👤 Клиент: <b>{contact_name}</b>\n"
            f"📱 Телефон: <b>{phone_str}</b>\n"
            f"📍 Адрес: <b>{addr or '—'}</b>\n"
            f"📌 Сделка: <b>{title}</b>\n"
            f"📝 Детали: {notes[:200] or '—'}",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Deal from chat error")
        await msg.edit_text(f"❌ Ошибка: {e}")


async def cb_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data

    if action == "deal_cancel":
        context.user_data.pop("pending_deal", None)
        await query.edit_message_text("Отменено.")
        return

    if action == "deal_confirm":
        deal = context.user_data.pop("pending_deal", None)
        if not deal:
            await query.edit_message_text("Нет данных для сохранения.")
            return
        try:
            stage_id = await _get_first_stage_id()
            if not stage_id:
                await query.edit_message_text("❌ Не удалось получить стадии сделок.")
                return

            contact_id = await _find_or_create_contact(deal["contact_name"], deal.get("phone"))

            payload = {
                "title": deal["title"],
                "stage_id": stage_id,
                "contact_id": contact_id,
                "address": deal.get("address") or None,
                "notes": deal.get("notes") or None,
            }
            if not contact_id:
                payload["new_contact_name"] = deal["contact_name"]
                del payload["contact_id"]

            created = await _crm_post("/deals", payload)
            deal_id = created.get("id", "?")
            context.user_data["last_deal_id"] = created.get("id")
            await query.edit_message_text(
                f"✅ Сделка <b>№{deal_id} «{deal['title']}»</b> создана!\n"
                f"Клиент: {deal['contact_name']}",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.exception("Deal create error")
            await query.edit_message_text(f"❌ Ошибка создания сделки: {e}")

# ════════════════════════════════════════
#  ✅  ЗАДАЧИ
# ════════════════════════════════════════

async def _handle_task(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    msg = await update.effective_message.reply_text("🔄 Разбираю задачу…")
    try:
        raw = await _ask_ai_text(TASK_PROMPT, text)
        data = _parse_json_safe(raw)

        if not data:
            # Простой fallback — создаём задачу напрямую из текста
            data = {"title": text[:200], "description": None, "due_date": None, "priority": "Обычный"}

        context.user_data["pending_task"] = data
        due = data.get("due_date") or "не указана"
        contact = data.get("contact_name") or "не указан"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Создать задачу", callback_data="task_confirm")],
            [InlineKeyboardButton("❌ Отмена", callback_data="task_cancel")],
        ])
        await msg.edit_text(
            f"📋 <b>Задача:</b>\n\n"
            f"📌 <b>{data['title']}</b>\n"
            f"📅 Срок: {due}\n"
            f"🔴 Приоритет: {data.get('priority', 'Обычный')}\n"
            f"👤 Контакт: {contact}\n"
            f"📝 {data.get('description') or ''}",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Task error")
        await msg.edit_text(f"❌ Ошибка: {e}")


async def cb_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data

    if action == "task_cancel":
        context.user_data.pop("pending_task", None)
        await query.edit_message_text("Отменено.")
        return

    if action == "task_confirm":
        task = context.user_data.pop("pending_task", None)
        if not task:
            await query.edit_message_text("Нет данных.")
            return
        try:
            contact_id = None
            if task.get("contact_name"):
                contact_id = await _find_or_create_contact(task["contact_name"])

            payload = {
                "title": task["title"],
                "description": task.get("description"),
                "due_date": task.get("due_date"),
                "priority": task.get("priority") or "Обычный",
                "contact_id": contact_id,
            }
            created = await _crm_post("/tasks", payload)
            await query.edit_message_text(
                f"✅ Задача <b>«{task['title']}»</b> создана!",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.exception("Task create error")
            await query.edit_message_text(f"❌ Ошибка: {e}")

# ════════════════════════════════════════
#  📸  ФОТО ДО/ПОСЛЕ → СДЕЛКА
# ════════════════════════════════════════

async def _handle_deal_photo(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              photo_bytes: bytes, caption: str):
    """Показать список активных сделок и дать выбрать, к которой прикрепить фото."""
    caption_lower = (caption or "").lower().strip()

    if "до" in caption_lower or "before" in caption_lower:
        kind = "before"
        kind_label = "ДО"
    elif "после" in caption_lower or "after" in caption_lower:
        kind = "after"
        kind_label = "ПОСЛЕ"
    else:
        kind = "general"
        kind_label = "общее"

    msg = await update.effective_message.reply_text("🔍 Ищу активные сделки…")

    # Сохраняем фото и kind в контексте
    context.user_data["pending_photo"] = {
        "bytes": photo_bytes,
        "kind": kind,
        "kind_label": kind_label,
        "deal_id": None,
    }

    active_deals = await _get_active_deals()

    if not active_deals:
        await msg.edit_text(
            "❌ Нет активных сделок (статусы: Согласовать / В работе / Ожидание). "
            "Введите номер сделки вручную или создайте сделку сначала.",
        )
        context.user_data["awaiting"] = "photo_deal_id"
        return

    # Строим клавиатуру из списка сделок
    buttons = []
    for d in active_deals:
        deal_id = d.get("id")
        title = (d.get("title") or f"Сделка #{deal_id}")[:35]
        stage = (d.get("stage_name") or "").strip()
        label = f"#{deal_id} {title} [{stage}]"
        buttons.append([InlineKeyboardButton(label, callback_data=f"photo_pick_{deal_id}")])

    buttons.append([InlineKeyboardButton("🔢 Ввести номер вручную", callback_data="photo_other")])
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="photo_cancel")])

    await msg.edit_text(
        f"📸 Фото <b>{kind_label}</b>. Выберите сделку:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def cb_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data

    if action == "photo_cancel":
        context.user_data.pop("pending_photo", None)
        await query.edit_message_text("Отменено.")
        return

    if action == "photo_other":
        context.user_data["awaiting"] = "photo_deal_id"
        await query.edit_message_text("Введите номер сделки (только цифры):")
        return

    if action == "photo_confirm":
        pending = context.user_data.pop("pending_photo", None)
        if not pending:
            await query.edit_message_text("Нет данных.")
            return
        await _upload_photo_to_deal(query, pending["bytes"], pending["deal_id"],
                                    pending["kind"], pending["kind_label"])
        return

    if action.startswith("photo_pick_"):
        deal_id_str = action.split("photo_pick_", 1)[1]
        if not deal_id_str.isdigit():
            await query.edit_message_text("Ошибка: неверный ID сделки.")
            return
        deal_id = int(deal_id_str)
        pending = context.user_data.pop("pending_photo", None)
        if not pending:
            await query.edit_message_text("Нет данных.")
            return
        context.user_data["last_deal_id"] = deal_id
        await _upload_photo_to_deal(query, pending["bytes"], deal_id,
                                    pending["kind"], pending["kind_label"])


async def _upload_photo_to_deal(target, photo_bytes: bytes, deal_id: int,
                                 kind: str, kind_label: str):
    try:
        filename = f"photo_{kind}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        await _crm_upload_file(
            "/files",
            photo_bytes,
            filename,
            extra_fields={"deal_id": str(deal_id), "file_kind": kind},
        )
        text = f"✅ Фото <b>{kind_label}</b> прикреплено к сделке #{deal_id}."
        if hasattr(target, "edit_message_text"):
            await target.edit_message_text(text, parse_mode="HTML")
        else:
            await target.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.exception("Photo upload error")
        text = f"❌ Ошибка загрузки фото: {e}"
        if hasattr(target, "edit_message_text"):
            await target.edit_message_text(text)
        else:
            await target.reply_text(text)

# ════════════════════════════════════════
#  📥  ГЛАВНЫЙ РОУТЕР СООБЩЕНИЙ
# ════════════════════════════════════════

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return await _deny(update)

    message = update.effective_message
    caption = (message.caption or "").strip()
    caption_lower = caption.lower()

    # Скачиваем фото
    photo = message.photo[-1]  # наибольшее разрешение
    tg_file = await photo.get_file()
    photo_bytes = await tg_file.download_as_bytearray()
    photo_bytes = bytes(photo_bytes)

    # Роутинг по подписи
    # "чек" — расход
    if "чек" in caption_lower or "расход" in caption_lower or "трат" in caption_lower:
        await _handle_receipt(update, context, photo_bytes)
    # до/после — к сделке
    elif any(k in caption_lower for k in ("до", "после", "before", "after")):
        await _handle_deal_photo(update, context, photo_bytes, caption)
    else:
        # Неясно — спрашиваем
        context.user_data["pending_photo_bytes"] = photo_bytes
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧾 Это чек (занести расход)", callback_data="route_receipt")],
            [InlineKeyboardButton("📸 Фото ДО к сделке",        callback_data="route_before")],
            [InlineKeyboardButton("📸 Фото ПОСЛЕ к сделке",     callback_data="route_after")],
            [InlineKeyboardButton("❌ Отмена",                   callback_data="route_cancel")],
        ])
        await message.reply_text("Что сделать с этим фото?", reply_markup=kb)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return await _deny(update)

    message = update.effective_message
    text = (message.text or "").strip()
    if not text:
        return

    awaiting = context.user_data.get("awaiting")

    # ── Ожидаем ввод имени расхода
    if awaiting == "expense_name":
        context.user_data.pop("awaiting", None)
        exp = context.user_data.get("pending_expense")
        if exp:
            exp["name"] = text
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Сохранить", callback_data="exp_confirm")],
            [InlineKeyboardButton("❌ Отмена",    callback_data="exp_cancel")],
        ])
        await message.reply_text(
            f"Новое название: <b>{text}</b>. Сохранить?",
            reply_markup=kb, parse_mode="HTML",
        )
        return

    # ── Ожидаем номер сделки для фото
    if awaiting == "photo_deal_id":
        context.user_data.pop("awaiting", None)
        pending = context.user_data.get("pending_photo")
        if pending and text.isdigit():
            pending["deal_id"] = int(text)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Загрузить", callback_data="photo_confirm")],
                [InlineKeyboardButton("❌ Отмена",    callback_data="photo_cancel")],
            ])
            await message.reply_text(
                f"Загрузить фото <b>{pending['kind_label']}</b> в сделку <b>#{text}</b>?",
                reply_markup=kb, parse_mode="HTML",
            )
        else:
            await message.reply_text("Неверный формат. Введите только цифры.")
        return

    # ── Явные префиксы (быстро, без AI)
    text_lower = text.lower().strip()
    if text_lower.startswith("задача:"):
        await _handle_task(update, context, text[7:].strip() or text)
        return
    if text_lower.startswith("сделка:"):
        await _handle_deal_from_chat(update, context, text[7:].strip() or text)
        return
    if text_lower.startswith("расход:"):
        await _handle_quick_expense_text(update, context, text[7:].strip() or text)
        return

    # ── AI определяет намерение автоматически
    thinking = await message.reply_text("🤔 Анализирую…")
    intent_data = await _detect_intent(text)
    intent     = intent_data.get("intent", "unknown")
    confidence = float(intent_data.get("confidence", 0))
    await thinking.delete()

    if intent == "task" and confidence >= 0.6:
        await _handle_task(update, context, text)
    elif intent == "deal" and confidence >= 0.6:
        await _handle_deal_from_chat(update, context, text)
    elif intent == "expense" and confidence >= 0.6:
        await _handle_quick_expense_text(update, context, text)
    else:
        context.user_data["pending_text"] = text
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Задача",  callback_data="route_task")],
            [InlineKeyboardButton("💬 Сделка",  callback_data="route_deal")],
            [InlineKeyboardButton("💸 Расход",  callback_data="route_expense")],
            [InlineKeyboardButton("❌ Ничего",  callback_data="route_cancel")],
        ])
        await message.reply_text(
            f"Не понял точно. Выбери что сделать:\n\n<i>{text[:200]}</i>",
            reply_markup=kb, parse_mode="HTML",
        )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return await _deny(update)

    msg = await update.effective_message.reply_text("🎤 Расшифровываю голосовое…")
    try:
        voice = update.effective_message.voice
        tg_file = await voice.get_file()
        voice_bytes = bytes(await tg_file.download_as_bytearray())
        text = await _transcribe_voice(voice_bytes)

        if not text:
            await msg.edit_text("❌ Не удалось распознать речь.")
            return

        await msg.edit_text(f"📝 Расшифровка:\n<i>{text}</i>", parse_mode="HTML")

        # AI определяет намерение автоматически
        intent_data = await _detect_intent(text)
        intent     = intent_data.get("intent", "unknown")
        confidence = float(intent_data.get("confidence", 0))

        if intent == "task" and confidence >= 0.6:
            await _handle_task(update, context, text)
        elif intent == "deal" and confidence >= 0.6:
            await _handle_deal_from_chat(update, context, text)
        elif intent == "expense" and confidence >= 0.6:
            await _handle_quick_expense_text(update, context, text)
        else:
            context.user_data["pending_text"] = text
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Задача",  callback_data="route_task")],
                [InlineKeyboardButton("💬 Сделка",  callback_data="route_deal")],
                [InlineKeyboardButton("💸 Расход",  callback_data="route_expense")],
                [InlineKeyboardButton("❌ Ничего",  callback_data="route_cancel")],
            ])
            await update.effective_message.reply_text(
                "Не понял точно. Выбери что сделать:",
                reply_markup=kb,
            )
    except Exception as e:
        logger.exception("Voice error")
        await msg.edit_text(f"❌ Ошибка: {e}")

# ════════════════════════════════════════
#  🔀  ROUTING CALLBACKS
# ════════════════════════════════════════

async def cb_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data

    if action == "route_cancel":
        context.user_data.pop("pending_photo_bytes", None)
        context.user_data.pop("pending_text", None)
        context.user_data.pop("voice_transcription", None)
        await query.edit_message_text("Ок, отменено.")
        return

    if action == "route_receipt":
        photo_bytes = context.user_data.pop("pending_photo_bytes", None)
        if photo_bytes:
            await query.edit_message_text("🔍 Читаю чек…")
            await _handle_receipt(update, context, photo_bytes)
        return

    if action in ("route_before", "route_after"):
        photo_bytes = context.user_data.pop("pending_photo_bytes", None)
        if photo_bytes:
            caption = "до" if action == "route_before" else "после"
            await query.edit_message_text(f"📤 Обрабатываю фото ({caption})…")
            await _handle_deal_photo(update, context, photo_bytes, caption)
        return

    if action == "route_task":
        text = context.user_data.pop("pending_text", None) or context.user_data.pop("voice_transcription", None)
        if text:
            await query.edit_message_text("🔄 Разбираю задачу…")
            await _handle_task(update, context, text)
        return

    if action == "route_deal":
        text = context.user_data.pop("pending_text", None) or context.user_data.pop("voice_transcription", None)
        if text:
            await query.edit_message_text("🔄 Анализирую переписку…")
            await _handle_deal_from_chat(update, context, text)
        return

    if action == "route_expense":
        text = context.user_data.pop("pending_text", None) or context.user_data.pop("voice_transcription", None)
        if text:
            await query.edit_message_text("💸 Разбираю расход…")
            await _handle_quick_expense_text(update, context, text)
        return

# ════════════════════════════════════════
#  🚀  ЗАПУСК
# ════════════════════════════════════════

def main():
    app = Application.builder().token(ASSISTANT_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_start))

    # Фото
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Голосовые
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Callback-кнопки
    app.add_handler(CallbackQueryHandler(cb_expense, pattern="^exp_"))
    app.add_handler(CallbackQueryHandler(cb_deal,    pattern="^deal_"))
    app.add_handler(CallbackQueryHandler(cb_task,    pattern="^task_"))
    app.add_handler(CallbackQueryHandler(cb_photo,   pattern="^photo_"))
    app.add_handler(CallbackQueryHandler(cb_route,   pattern="^route_"))

    logger.info("GreenCRM Assistant Bot запускается…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
