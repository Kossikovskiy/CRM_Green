# -*- coding: utf-8 -*-
"""
Client-facing Telegram AI bot for GrassCRM.
- Replies to customers in private chat.
- Collects lead data (phone, address, service details, callback time).
- Creates contact + deal in CRM when enough concrete data is available.
- Loads services catalog AND bot_faq from Supabase via CRM API.
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("client_bot")

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

CLIENT_BOT_TOKEN = os.getenv("TELEGRAM_CLIENT_BOT_TOKEN")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_ACCESS_ID = os.getenv("OPENAI_ACCESS_ID") or os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "deepseek-chat")

if not CLIENT_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_CLIENT_BOT_TOKEN не задан")
if not INTERNAL_API_KEY:
    raise RuntimeError("INTERNAL_API_KEY не задан")
if not OPENAI_ACCESS_ID:
    raise RuntimeError("OPENAI_ACCESS_ID/OPENAI_API_KEY не задан")

API_HEADERS = {"X-Internal-API-Key": INTERNAL_API_KEY}

# In-memory state per chat
CHAT_STATE: Dict[int, Dict[str, Any]] = {}
SERVICES_CACHE: Dict[str, Any] = {"ts": 0.0, "items": []}
FAQ_CACHE: Dict[str, Any] = {"ts": 0.0, "items": []}
SERVICES_CACHE_TTL_SEC = int(os.getenv("SERVICES_CACHE_TTL_SEC", "300"))

SYSTEM_PROMPT = """
Вы — менеджер компании «Покос Ропша». Общайтесь с клиентом на «вы», по-русски, коротко и по-человечески — без официоза и канцелярщины. Вы бот, не скрывайте это, но и не акцентируйте.

Ваша задача — собрать данные для расчёта и записи:
- услуга
- адрес/населённый пункт
- площадь (сотки или м²)
- когда косили последний раз
- высота/состояние травы
- нужен ли сбор/вывоз
- желаемые дата/время
- имя и телефон клиента

Правила:
1) Цены и услуги ТОЛЬКО из `services_catalog`. Ничего не придумывайте.
2) Если услуги нет в каталоге — скажите: «Точную сумму уточню после осмотра, передам менеджеру».
3) ВАЖНО: если клиент просит вывоз травы — автоматически добавляйте к нему сбор скошенной травы (это отдельная услуга в каталоге). Объясните клиенту: «Вывоз включает погрузку, а сбор в мешки считается отдельно».
4) Не придумывайте имя клиента. Если не представился — не обращайтесь по имени.
5) Используйте `bot_faq` для ответов на типовые вопросы.
6) Стиль: 1–3 коротких абзаца, живой язык. Сначала ответ, потом ориентир по цене.
7) Если дорого — предложите альтернативу или обсудите бюджет.
8) Если отказался — «Без проблем, хорошего дня».
9) БЕЗ markdown-разметки (никаких **, *, `, #). Обычный текст.

Логика вопросов: локация → площадь → когда косили → высота травы → вывоз/сбор → когда удобно → имя и телефон.

ВАЖНО: Верните строго JSON и ничего кроме него:
{
  "reply": "текст ответа клиенту",
  "lead": {
    "name": null,
    "phone": null,
    "service_type": null,
    "address": null,
    "area": null,
    "grass_height_or_condition": null,
    "extra_services": null,
    "callback_time": null,
    "notes": null
  },
  "should_create_deal": false,
  "spam_or_prank": false
}
""".strip()

PHONE_RE = re.compile(r"(?:\+7|7|8)?[\s\-\(]*\d{3}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
NAME_EXPLICIT_RE = re.compile(r"(?:меня\s+зовут|я)\s+([А-ЯЁ][а-яё]{1,30})", re.IGNORECASE)


def _normalize_phone(text: str) -> Optional[str]:
    m = PHONE_RE.search(text or "")
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(0))
    if len(digits) == 11 and digits[0] in ("7", "8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11:
        return None
    return "+" + digits


def _merge_lead(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(old)
    for k, v in (new or {}).items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        merged[k] = v
    return merged


def _extract_explicit_name(text: str) -> Optional[str]:
    m = NAME_EXPLICIT_RE.search(text or "")
    if not m:
        return None
    name = (m.group(1) or "").strip()
    if not name:
        return None
    return name[:1].upper() + name[1:].lower()


def _normalize_service_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip())


def _parse_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting from text."""
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"`{1,3}(.+?)`{1,3}", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"_{1,2}(.+?)_{1,2}", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # numbered list "1. " → keep as is but without bold
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _sanitize_reply(reply: str, services_catalog: List[Dict[str, Any]]) -> str:
    text = (reply or "").strip()
    if not text:
        return ""

    # Remove any accidental fenced code blocks
    text = re.sub(r"```(?:json)?\s*\{.*?```", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"```", "", text)

    text = _strip_markdown(text)

    # Block hallucinated equipment not in catalog
    catalog_blob = " ".join(
        f"{item.get('name') or ''} {item.get('notes') or ''}".lower()
        for item in (services_catalog or [])
    )
    if "камаз" not in catalog_blob:
        text = re.sub(r"камаз[а-яё-]*", "вывоз", text, flags=re.IGNORECASE)

    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def _crm_get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{API_BASE_URL}{path}", headers=API_HEADERS)
        r.raise_for_status()
        return r.json()


async def _crm_post(path: str, payload: Dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{API_BASE_URL}{path}", headers=API_HEADERS, json=payload)
        r.raise_for_status()
        return r.json() if r.text else None


async def _load_services_catalog(force: bool = False) -> List[Dict[str, Any]]:
    now = time.time()
    cached = SERVICES_CACHE.get("items") or []
    if not force and cached and (now - float(SERVICES_CACHE.get("ts") or 0.0) < SERVICES_CACHE_TTL_SEC):
        return cached

    services = await _crm_get("/services")
    normalized: List[Dict[str, Any]] = []
    for item in services or []:
        name = _normalize_service_name(item.get("name"))
        if not name:
            continue
        normalized.append({
            "id": item.get("id"),
            "name": name,
            "price": _parse_float(item.get("price")),
            "unit": _normalize_service_name(item.get("unit")) or "ед.",
            "min_volume": _parse_float(item.get("min_volume")),
            "notes": _normalize_service_name(item.get("notes")) or None,
        })

    SERVICES_CACHE["items"] = normalized
    SERVICES_CACHE["ts"] = now
    return normalized


async def _load_bot_faq(force: bool = False) -> List[Dict[str, Any]]:
    """Load active FAQ entries from bot_faq table via CRM API."""
    now = time.time()
    cached = FAQ_CACHE.get("items") or []
    if not force and cached and (now - float(FAQ_CACHE.get("ts") or 0.0) < SERVICES_CACHE_TTL_SEC):
        return cached

    try:
        faq_items = await _crm_get("/bot-faq")
        active = [
            {
                "intent": item.get("intent"),
                "question_example": item.get("question_example"),
                "answer": item.get("answer"),
            }
            for item in (faq_items or [])
            if item.get("active", True)
        ]
        FAQ_CACHE["items"] = active
        FAQ_CACHE["ts"] = now
        return active
    except Exception:
        logger.warning("Could not load bot_faq — using empty list")
        return cached or []


async def _match_services(lead: Dict[str, Any], catalog: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Match lead service_type and extra_services to catalog items, return list of {service_id, quantity}."""
    if not catalog:
        return []

    service_type = (lead.get("service_type") or "").lower()
    extra = (lead.get("extra_services") or "").lower()
    area_raw = lead.get("area") or ""
    # Extract numeric area
    area_num = 1.0
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(area_raw))
    if m:
        try:
            area_num = float(m.group(1).replace(",", "."))
        except Exception:
            pass

    matched = []
    used_ids = set()

    def find_service(keywords: List[str]) -> Optional[Dict[str, Any]]:
        for item in catalog:
            name = (item.get("name") or "").lower()
            notes = (item.get("notes") or "").lower()
            if any(kw in name or kw in notes for kw in keywords):
                return item
        return None

    # Map service_type to catalog
    mapping = [
        (["сильно запущен", ">60", "60 см", "выше колена", "по колено"], ["сильно запущенный"]),
        (["запущен", "30-60", "30–60", "высокая трава"], ["запущенный покос"]),
        (["борщевик"], ["борщевик"]),
        (["абонем", "еженедел"], ["еженедельное"]),
        (["вдоль забора", "обочин", "периметр"], ["забор", "обочин"]),
        (["скарификац"], ["скарификац"]),
        (["аэрац"], ["аэрац"]),
        (["прополк"], ["прополк"]),
        (["культивац", "рыхлен"], ["культивац", "рыхлен"]),
        (["посев"], ["посев"]),
        (["засев", "засеив"], ["засеив"]),
        (["разравнива"], ["разравнива"]),
        (["гербицид", "сорняк"], ["гербицид"]),
        (["клещ"], ["клещ"]),
        (["парковк", "твёрд", "твerd"], ["парковк", "твёрд"]),
        (["спил", "дерев"], ["спил"]),
        (["уборка", "генерал"], ["генерал"]),
        (["листь"], ["листь"]),
        (["покос", "косить", "покосить", "стрижк", "трава"], ["стандартный покос"]),
    ]

    for triggers, keywords in mapping:
        if any(t in service_type for t in triggers):
            svc = find_service(keywords)
            if svc and svc["id"] not in used_ids:
                qty = max(area_num, float(svc.get("min_volume") or 1))
                matched.append({"service_id": svc["id"], "quantity": qty})
                used_ids.add(svc["id"])
            break

    # Extra services
    extra_mapping = [
        (["вывоз", "мусор", "увез"], ["вывоз травы"]),
        (["сбор", "мешк"], ["сбор скошенной"]),
        (["листь"], ["листь"]),
        (["клещ"], ["клещ"]),
        (["гербицид"], ["гербицид"]),
    ]
    for triggers, keywords in extra_mapping:
        if any(t in extra for t in triggers):
            svc = find_service(keywords)
            if svc and svc["id"] not in used_ids:
                qty = max(area_num, float(svc.get("min_volume") or 1))
                matched.append({"service_id": svc["id"], "quantity": qty})
                used_ids.add(svc["id"])

    # If вывоз requested — auto-add сбор if not already added
    has_disposal = any(
        (item.get("name") or "").lower() in ["вывоз травы / мусора", "вывоз травы/мусора", "вывоз травы"]
        for s in matched
        for item in catalog if item.get("id") == s["service_id"]
    )
    has_collection = any(
        "сбор скошенной" in (item.get("name") or "").lower()
        for s in matched
        for item in catalog if item.get("id") == s["service_id"]
    )
    if has_disposal and not has_collection:
        svc = find_service(["сбор скошенной"])
        if svc and svc["id"] not in used_ids:
            qty = max(area_num, float(svc.get("min_volume") or 1))
            matched.append({"service_id": svc["id"], "quantity": qty})

    return matched


async def _send_manager_notification(lead: Dict[str, Any], chat_id: int, username: str, deal_id: Optional[int]) -> None:
    """Send new lead notification to internal manager bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return

    lines = [
        "🌿 Новая заявка с Telegram!",
        "",
        f"👤 Клиент: {lead.get('name') or '—'}",
        f"📱 Телефон: {lead.get('phone') or '—'}",
        f"🔗 Telegram: @{username}" if username else "🔗 Telegram: не указан",
        f"📍 Адрес: {lead.get('address') or '—'}",
        f"📐 Площадь: {lead.get('area') or '—'}",
        f"🌾 Услуга: {lead.get('service_type') or '—'}",
        f"🌿 Состояние: {lead.get('grass_height_or_condition') or '—'}",
        f"➕ Доп.услуги: {lead.get('extra_services') or '—'}",
        f"🕐 Удобное время: {lead.get('callback_time') or '—'}",
    ]
    if deal_id:
        lines.append(f"")
        lines.append(f"✅ Сделка №{deal_id} создана в CRM")

    msg = "\n".join(lines)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": msg}
            )
    except Exception:
        logger.warning("Failed to send manager notification")


async def _crm_create_lead(lead: Dict[str, Any], chat_id: int, username: str, services_catalog: List[Dict[str, Any]]) -> Optional[int]:
    phone = _normalize_phone(lead.get("phone") or "")
    if not phone:
        return None

    contacts = await _crm_get("/contacts")
    existing = next((c for c in contacts if (c.get("phone") or "") == phone), None)

    tg_id = str(chat_id)

    if existing:
        contact_id = existing["id"]
        # Update telegram info if missing
        if not existing.get("telegram_id"):
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    await client.patch(
                        f"{API_BASE_URL}/contacts/{contact_id}",
                        headers=API_HEADERS,
                        json={"telegram_id": tg_id, "telegram_username": username or None}
                    )
            except Exception:
                pass
    else:
        contact = await _crm_post("/contacts", {
            "name": lead.get("name") or (f"@{username}" if username else f"Telegram {phone}"),
            "phone": phone,
            "source": "telegram_ai",
            "telegram_id": tg_id,
            "telegram_username": username or None,
        })
        contact_id = contact["id"]

    stages = await _crm_get("/stages")
    stage_id = None
    for s in stages:
        if not s.get("is_final"):
            stage_id = s["id"]
            break
    if not stage_id and stages:
        stage_id = stages[0]["id"]
    if not stage_id:
        return None

    service = lead.get("service_type") or "Заявка с Telegram"
    area = lead.get("area") or ""
    title = f"{service} {area}".strip()

    # Match services from catalog
    matched_services = await _match_services(lead, services_catalog)

    notes_parts = [
        f"Источник: Telegram AI bot",
        f"Chat ID: {chat_id}",
        f"Telegram: @{username}" if username else "Telegram: —",
        f"Услуга: {lead.get('service_type') or '—'}",
        f"Адрес: {lead.get('address') or '—'}",
        f"Площадь: {lead.get('area') or '—'}",
        f"Состояние травы/участка: {lead.get('grass_height_or_condition') or '—'}",
        f"Доп.услуги: {lead.get('extra_services') or '—'}",
        f"Удобное время связи: {lead.get('callback_time') or '—'}",
        f"Комментарий: {lead.get('notes') or '—'}",
    ]

    deal = await _crm_post("/deals", {
        "title": title[:180],
        "stage_id": stage_id,
        "contact_id": contact_id,
        "address": lead.get("address") or None,
        "services": matched_services,
        "notes": "\n".join(notes_parts),
    })
    return deal.get("id") if isinstance(deal, dict) else None


def _parse_ai_json(content: str) -> Optional[Dict[str, Any]]:
    raw = (content or "").strip()
    if not raw:
        return None

    candidates = [raw]

    if "```" in raw:
        fenced = re.findall(r"```(?:json)?\s*(.*?)```", raw, flags=re.IGNORECASE | re.DOTALL)
        for block in fenced:
            block = (block or "").strip()
            if block:
                candidates.append(block)

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(raw[start:end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue

    return None


async def _ask_ai(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    url = f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions"
    req = {
        "model": OPENAI_MODEL,
        "temperature": 0.2,
        "messages": messages,
    }
    headers = {"Authorization": f"Bearer {OPENAI_ACCESS_ID}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(url, json=req, headers=headers)
    if not r.is_success:
        raise RuntimeError(f"AI API {r.status_code}: {r.text[:250]}")
    data = r.json()
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")

    parsed = _parse_ai_json(content)
    if parsed is not None:
        return parsed

    logger.warning("AI returned non-JSON content; using text fallback")
    return {
        "reply": _strip_markdown((content or "").strip()) or "Спасибо! Передаю ваш запрос менеджеру.",
        "lead": {},
        "should_create_deal": False,
        "spam_or_prank": False,
    }


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот компании «Покос Ропша» 🌿\n"
        "Подскажите, что нужно сделать на участке и где он находится?"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return
    if update.effective_chat.type != "private":
        return

    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not text:
        return

    st = CHAT_STATE.setdefault(chat_id, {
        "history": [],
        "lead": {},
        "deal_created": False,
    })
    st["history"].append({"role": "user", "content": text})

    # lightweight local extraction for phone / explicit name
    ph = _normalize_phone(text)
    if ph:
        st["lead"]["phone"] = ph

    explicit_name = _extract_explicit_name(text)
    if explicit_name and not st["lead"].get("name"):
        st["lead"]["name"] = explicit_name

    username = update.effective_user.username if update.effective_user else ""

    try:
        services_catalog = await _load_services_catalog()
    except Exception:
        logger.exception("Failed to load services catalog")
        services_catalog = []

    try:
        bot_faq = await _load_bot_faq()
    except Exception:
        logger.exception("Failed to load bot_faq")
        bot_faq = []

    context_blob = {
        "known_lead": st["lead"],
        "client_profile": {"username": username},
        "name_provided_by_user": bool(st["lead"].get("name")),
        "time": datetime.now().isoformat(timespec="minutes"),
        "services_catalog": services_catalog,
        "bot_faq": bot_faq,
    }

    ai_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Контекст: {json.dumps(context_blob, ensure_ascii=False)}"},
    ]
    # last 8 turns for context
    ai_messages.extend(st["history"][-8:])

    try:
        ai = await _ask_ai(ai_messages)
    except Exception:
        logger.exception("AI error")
        await update.message.reply_text("Извините, временная ошибка сервиса. Оставьте телефон, и менеджер свяжется с вами.")
        return

    lead = ai.get("lead") if isinstance(ai.get("lead"), dict) else {}
    if not st["lead"].get("name") and isinstance(lead, dict):
        lead.pop("name", None)
    st["lead"] = _merge_lead(st["lead"], lead)

    spam = bool(ai.get("spam_or_prank"))
    should_create = bool(ai.get("should_create_deal"))

    required_ok = (
        bool(_normalize_phone(st["lead"].get("phone") or ""))
        and bool(st["lead"].get("service_type") or st["lead"].get("notes") or st["lead"].get("address"))
    )

    created_deal_id = None
    if not spam and should_create and required_ok and not st.get("deal_created"):
        try:
            created_deal_id = await _crm_create_lead(st["lead"], chat_id, username or "", services_catalog)
            if created_deal_id:
                st["deal_created"] = True
        except Exception:
            logger.exception("Failed to create CRM lead")

    # Always notify manager on first message (once per chat)
    if not st.get("manager_notified") and not spam:
        st["manager_notified"] = True
        try:
            await _send_manager_notification(st["lead"], chat_id, username or "", created_deal_id)
        except Exception:
            logger.warning("Manager notification failed")

    reply = _sanitize_reply(ai.get("reply") or "", services_catalog) or "Спасибо! Уточню детали и передам менеджеру."
    if created_deal_id:
        reply += f"\n\nЗаявка зарегистрирована (№{created_deal_id}). Менеджер свяжется с вами в указанное время."

    st["history"].append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)


async def main():
    app = Application.builder().token(CLIENT_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Client bot is starting...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
