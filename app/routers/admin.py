# GrassCRM — app/routers/admin.py v8.0.4

import io
import os
import shutil
import time as _time
from datetime import datetime, date
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import text, extract
from sqlalchemy.orm import Session as DBSession, joinedload

from app.database import get_db
from app.models import (
    Deal, Task, Stage, Contact, Expense, ExpenseCategory,
    AiMemory, AiUsageLog, DealComment,
)
from app.schemas import ServiceAIAgentRequest, AIActionRequest, AiMemorySaveRequest
from app.security import get_current_user, is_admin, is_won_stage, require_admin, require_service_key
from app.cache import _cache
from app.config import OPENAI_BASE_URL, OPENAI_ACCESS_ID, OPENAI_MODEL
from app.migrations import _process_repeat_deals, _process_expired_archives

# /api/service/* — требует X-Service-Key
router = APIRouter(dependencies=[Depends(require_service_key)])

# /api/version — только сессия, без service key
version_router = APIRouter()


# In-memory расписание (сбрасывается при рестарте)
_bot_schedule = {
    "enabled":         False,   # бот отчётов (группа 18:00)
    "morning_enabled": True,    # AI-ассистент утро 09:00
    "evening_enabled": True,    # AI-ассистент вечер 19:00
    "time":            "18:00",
}
def _build_crm_context(db: DBSession, req_year: int) -> dict:
    today = date.today()
    month_prefix = today.strftime("%Y-%m")
    stages = {s.id: s for s in db.query(Stage).all()}
    won_ids = {s.id for s in stages.values() if is_won_stage(s)}

    deals_q   = db.query(Deal).filter(extract("year", Deal.deal_date) == req_year).order_by(Deal.deal_date.desc()).all()
    won_deals = [d for d in deals_q if d.stage_id in won_ids]
    total_rev = sum(d.total or 0 for d in won_deals)
    win_rate  = round(len(won_deals) / len(deals_q) * 100, 1) if deals_q else 0

    recent_deals = [{"id": d.id, "title": d.title, "contact": d.contact.name if d.contact else "—",
                     "stage": stages[d.stage_id].name if d.stage_id and d.stage_id in stages else "—",
                     "total": d.total or 0, "address": d.address or "",
                     "created_at": d.created_at.strftime("%Y-%m-%d") if d.created_at else ""}
                    for d in deals_q[:10]]

    expenses_q = db.query(Expense).filter(extract("year", Expense.date) == req_year).order_by(Expense.date.desc()).all()
    total_exp  = sum(e.amount or 0 for e in expenses_q)
    month_exp  = sum(e.amount or 0 for e in expenses_q if str(e.date)[:7] == month_prefix)
    recent_exp = [{"name": e.name, "amount": e.amount or 0, "date": str(e.date) if e.date else "",
                   "category": e.category.name if e.category else "—"} for e in expenses_q[:10]]

    tasks_q = db.query(Task).filter(Task.status.notin_(["Завершена","Выполнена"])).order_by(Task.due_date.asc().nullslast()).limit(10).all()
    recent_tasks = [{"title": t.title, "due_date": str(t.due_date) if t.due_date else "",
                     "priority": t.priority or "Обычный", "status": t.status or "Открыта"} for t in tasks_q]
    overdue_count = db.query(Task).filter(Task.due_date < today, Task.status.notin_(["Завершена","Выполнена"])).count()

    contacts_q = db.query(Contact).order_by(Contact.id.desc()).limit(10).all()
    recent_contacts = [{"name": c.name, "phone": c.phone or "", "settlement": c.settlement or "",
                        "plot_area": c.plot_area} for c in contacts_q]

    return {
        "stats": {"year": req_year, "total_deals": len(deals_q), "won_deals": len(won_deals),
                  "active_deals": len([d for d in deals_q if d.stage_id not in won_ids]),
                  "win_rate_pct": win_rate, "revenue": round(total_rev, 2),
                  "expenses_year": round(total_exp, 2), "expenses_month": round(month_exp, 2),
                  "profit": round(total_rev - total_exp, 2),
                  "open_tasks": len(recent_tasks), "overdue_tasks": overdue_count},
        "deals": recent_deals, "expenses": recent_exp,
        "tasks": recent_tasks, "contacts": recent_contacts,
    }


# ── SERVICE STATUS ────────────────────────────────────────────────────────────
@router.get("/api/service/status")
def service_status(db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")
    system_payload = {}
    try:
        try:
            import psutil
        except ImportError:
            import sys as _sys
            for _p in ["/usr/lib/python3/dist-packages","/usr/local/lib/python3.12/dist-packages","/usr/local/lib/python3.11/dist-packages"]:
                if _p not in _sys.path: _sys.path.insert(0, _p)
            import psutil
        mem = psutil.virtual_memory(); disk = psutil.disk_usage("/"); cpu = psutil.cpu_percent(interval=1.0)
        system_payload = {"cpu": round(cpu,1), "mem_used_mb": round(mem.used/1024**2), "mem_total_mb": round(mem.total/1024**2),
                          "mem_pct": round(mem.percent,1), "disk_used_gb": round(disk.used/1024**3,1),
                          "disk_total_gb": round(disk.total/1024**3,1), "disk_pct": round(disk.percent,1)}
    except ImportError:
        system_payload = {"error": "psutil is not installed"}
    except Exception as e:
        system_payload = {"error": str(e)}

    import glob as _glob
    backup_files = sorted(_glob.glob("/var/www/crm/GCRM-2/backups/*.sql.gz"))
    last_backup = datetime.fromtimestamp(os.path.getmtime(backup_files[-1])).strftime("%d.%m.%Y %H:%M") if backup_files else None

    return {
        "db": {"deals": db.query(Deal).count(), "contacts": db.query(Contact).count(),
               "active_tasks": db.query(Task).filter(Task.is_done == False).count(),
               "overdue_tasks": db.query(Task).filter(Task.is_done == False, Task.due_date < datetime.utcnow().date()).count(),
               "active_deals": db.query(Deal).join(Stage).filter(Stage.is_final == False).count(),
               "last_backup": last_backup},
        "cache": {"keys": list(_cache._data.keys()), "count": len(_cache._data), "ttl": _cache._ttl},
        "system": system_payload,
        "tg_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
        "tg2_configured": bool(os.getenv("TELEGRAM_BOT2_TOKEN")),
        "tg3_configured": bool(os.getenv("TELEGRAM_ASSISTANT_BOT_TOKEN")),
    }


@router.post("/api/service/cache/clear")
def service_clear_cache(user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")
    _cache._data.clear()
    return {"ok": True, "message": "Кэш полностью очищен"}


# ── BOT SCHEDULE ──────────────────────────────────────────────────────────────
@router.get("/api/service/bot/schedule")
def get_bot_schedule(user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")
    return _bot_schedule


@router.post("/api/service/bot/schedule")
async def set_bot_schedule(payload: dict, user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")
    import re as _re
    t = payload.get("time", "18:00")
    if not _re.match(r"^\d{1,2}:\d{2}$", t): raise HTTPException(400, "Неверный формат времени (ЧЧ:ММ)")
    _bot_schedule["enabled"]         = bool(payload.get("enabled", False))
    _bot_schedule["morning_enabled"] = bool(payload.get("morning_enabled", True))
    _bot_schedule["evening_enabled"] = bool(payload.get("evening_enabled", True))
    _bot_schedule["time"]            = t
    return {"ok": True, **_bot_schedule}


@router.get("/api/service/run-repeats")
def service_run_repeats(user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")
    try:
        _process_repeat_deals()
        return {"ok": True, "message": "Проверка повторных сделок выполнена"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/service/run-archive")
def service_run_archive(user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")
    try:
        _process_expired_archives()
        return {"ok": True, "message": "Проверка архивных сделок выполнена"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/service/run-checkup")
async def service_run_checkup(user: dict = Depends(get_current_user)):
    """Ручной запуск proactive checkup — отправляет уведомление владельцу в Telegram."""
    if not is_admin(user): raise HTTPException(403, "Admin only")
    import httpx as _hx
    token    = os.getenv("TELEGRAM_ASSISTANT_BOT_TOKEN")
    owner_id = os.getenv("TELEGRAM_OWNER_ID")
    if not token or not owner_id:
        raise HTTPException(400, "TELEGRAM_ASSISTANT_BOT_TOKEN или TELEGRAM_OWNER_ID не заданы")
    try:
        async with _hx.AsyncClient(timeout=10) as c:
            await c.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": int(owner_id), "text": "🔍 Ручная проверка запущена из CRM...", "parse_mode": "HTML"},
            )
        return {"ok": True, "message": "Checkup запущен — смотри в Telegram"}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── BOT REPORT ────────────────────────────────────────────────────────────────
@router.post("/api/service/bot/report")
async def service_send_report(db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")
    token = os.getenv("TELEGRAM_BOT_TOKEN"); chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat: raise HTTPException(400, "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID не заданы в .env")

    today = datetime.utcnow().date()
    lines = [f"🌿 GrassCRM — отчёт за {today.strftime('%d.%m.%Y')}", ""]

    active_deals = (db.query(Deal).join(Stage).filter(Stage.is_final == False)
                    .options(joinedload(Deal.contact), joinedload(Deal.stage))
                    .order_by(Stage.order, Deal.created_at.desc()).all())
    if active_deals:
        lines.append("📋 Сделки в работе:")
        current_stage = None
        for deal in active_deals:
            sn = deal.stage.name if deal.stage else "Без стадии"
            if sn != current_stage:
                current_stage = sn; lines.append(f"\n  ▸ {sn}")
            client = deal.contact.name if deal.contact else "Без клиента"
            total  = f"{int(deal.total or 0):,}".replace(",", " ")
            lines.append(f"    · {deal.title} ({client}) — {total} руб.")
            if deal.deal_date: lines.append(f"      📅 {deal.deal_date.strftime('%d.%m.%Y %H:%M')}")
            if deal.address:   lines.append(f"      📍 {deal.address}")
    else:
        lines.append("📋 Активных сделок нет.")
    lines.append("")

    today_tasks   = db.query(Task).filter(Task.is_done == False, Task.due_date == today).all()
    overdue_tasks = db.query(Task).filter(Task.is_done == False, Task.due_date < today).order_by(Task.due_date).all()
    if today_tasks:
        lines.append("✅ Задачи на сегодня:")
        for t in today_tasks: lines.append(f"    · {t.title}")
        lines.append("")
    if overdue_tasks:
        lines.append(f"⚠️ Просрочено ({len(overdue_tasks)}):")
        for t in overdue_tasks[:5]: lines.append(f"    · {t.title} (до {t.due_date.strftime('%d.%m') if t.due_date else '—'})")
        if len(overdue_tasks) > 5: lines.append(f"    ...и ещё {len(overdue_tasks)-5}")
        lines.append("")
    if not today_tasks and not overdue_tasks:
        lines.append("✅ Задач на сегодня нет."); lines.append("")

    try:
        row = db.execute(text("SELECT phrase FROM daily_phrases ORDER BY RANDOM() LIMIT 1")).fetchone()
        if row: lines.extend(["· · · · · · · · · ·", row[0].replace("\\n", "\n")])
    except Exception: pass

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": "\n".join(lines)})
        if not r.is_success: raise HTTPException(500, f"Telegram ошибка {r.status_code}: {r.text[:200]}")
    return {"ok": True, "message": "Отчёт отправлен в Telegram"}


# ── BACKUP ────────────────────────────────────────────────────────────────────
@router.post("/api/service/backup")
def service_backup(user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")
    import subprocess as _sp, glob as _glob, re as _re
    db_url = os.getenv("DATABASE_URL", "")
    m = _re.match(r"postgresql(?:\+\w+)?://([^:]+):([^@]+)@([^:/]+):?(\d+)?/(\S+)", db_url)
    if not m: raise HTTPException(500, "Не удалось разобрать DATABASE_URL")
    db_user, db_pass, db_host, db_port, db_name = m.group(1), m.group(2), m.group(3), m.group(4) or "5432", m.group(5).split("?")[0]
    backup_dir = "/var/www/crm/GCRM-2/backups"; os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S"); out_file = f"{backup_dir}/backup_{ts}.sql.gz"
    pg_dump_cmd = None
    for candidate in ["/usr/lib/postgresql/17/bin/pg_dump", "/usr/lib/postgresql/16/bin/pg_dump", "pg_dump"]:
        try:
            r = _sp.run([candidate, "--version"], capture_output=True, text=True, timeout=3)
            if r.returncode == 0: pg_dump_cmd = candidate; break
        except FileNotFoundError: continue
    if not pg_dump_cmd: raise HTTPException(500, "pg_dump не найден")
    env = {**os.environ, "PGPASSWORD": db_pass}
    try:
        dump = _sp.Popen([pg_dump_cmd,"-h",db_host,"-p",db_port,"-U",db_user,"-d",db_name,"--no-password","-F","p"], stdout=_sp.PIPE, stderr=_sp.PIPE, env=env)
        with open(out_file, "wb") as f_out:
            gzip_proc = _sp.Popen(["gzip","-c"], stdin=dump.stdout, stdout=f_out, stderr=_sp.PIPE)
        dump.stdout.close(); _, dump_err = dump.communicate(timeout=120); gzip_proc.communicate(timeout=30)
        if dump.returncode != 0:
            if os.path.exists(out_file): os.remove(out_file)
            raise HTTPException(500, f"pg_dump ошибка: {dump_err.decode()[:300]}")
    except _sp.TimeoutExpired:
        raise HTTPException(500, "pg_dump timeout (120s)")
    for old in sorted(_glob.glob(f"{backup_dir}/backup_*.sql.gz"))[:-10]:
        try: os.remove(old)
        except: pass
    return {"ok": True, "message": f"Бэкап создан: backup_{ts}.sql.gz ({round(os.path.getsize(out_file)/1024,1)} КБ)"}


@router.post("/api/service/db/check")
def service_db_check(db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")
    try:
        ver = db.execute(text("SELECT version()")).scalar()
        return {"ok": True, "message": "БД доступна", "detail": str(ver)[:80]}
    except Exception as e:
        raise HTTPException(500, f"Ошибка: {e}")


@router.get("/api/service/logs")
def service_get_logs(n: int = 60, user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")
    import subprocess as _sp
    try:
        r = _sp.run(["journalctl","-u","crm.service",f"-n{n}","--no-pager","--output=short"], capture_output=True, text=True, timeout=6)
        return {"ok": True, "logs": r.stdout}
    except Exception as e:
        return {"ok": False, "logs": str(e)}


# ── AI ASK ────────────────────────────────────────────────────────────────────
@router.post("/api/service/ai/ask")
async def service_ai_ask(payload: ServiceAIAgentRequest, db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")

    base_url  = (payload.base_url  or OPENAI_BASE_URL  or "").strip()
    access_id = (payload.access_id or OPENAI_ACCESS_ID or "").strip()
    model     = (payload.model     or OPENAI_MODEL     or "gpt-4o-mini").strip()
    if not base_url:  raise HTTPException(400, "Не задан OpenAI URL")
    if not access_id: raise HTTPException(400, "Не задан Access ID / API key")
    if not base_url.startswith("http"): base_url = f"https://{base_url}"

    req_year = payload.year or datetime.utcnow().year
    crm = _build_crm_context(db, req_year)
    stats = crm["stats"]

    deals_text    = "\n".join(f"  • #{d['id']} {d['title']} | {d['contact']} | {d['stage']} | {d['total']:,.0f}₽ | {d['created_at']}" for d in crm["deals"]) or "  нет данных"
    tasks_text    = "\n".join(f"  • [{t['priority']}] {t['title']} | срок: {t['due_date'] or '—'} | {t['status']}" for t in crm["tasks"]) or "  нет данных"
    expenses_text = "\n".join(f"  • {e['name']} | {e['amount']:,.0f}₽ | {e['category']} | {e['date']}" for e in crm["expenses"]) or "  нет данных"
    contacts_text = "\n".join(f"  • {c['name']}{' | '+c['phone'] if c['phone'] else ''}{' | '+c['settlement'] if c['settlement'] else ''}" for c in crm["contacts"]) or "  нет данных"

    context = (f"=== СТАТИСТИКА ({stats['year']}) ===\n"
               f"Сделок: {stats['total_deals']} | Успешных: {stats['won_deals']} ({stats['win_rate_pct']}%) | Активных: {stats['active_deals']}\n"
               f"Выручка: {stats['revenue']:,.0f}₽ | Расходы: {stats['expenses_year']:,.0f}₽ | Прибыль: {stats['profit']:,.0f}₽\n"
               f"Задач открытых: {stats['open_tasks']} | Просрочено: {stats['overdue_tasks']}\n\n"
               f"=== ПОСЛЕДНИЕ СДЕЛКИ (10) ===\n{deals_text}\n\n"
               f"=== ОТКРЫТЫЕ ЗАДАЧИ (10) ===\n{tasks_text}\n\n"
               f"=== ПОСЛЕДНИЕ РАСХОДЫ (10) ===\n{expenses_text}\n\n"
               f"=== ПОСЛЕДНИЕ КЛИЕНТЫ (10) ===\n{contacts_text}")

    # Контекст конкретной записи
    record_context = ""
    if payload.context_type and payload.context_id:
        try:
            ctype, cid = payload.context_type.lower(), payload.context_id
            if ctype == "deal":
                rec = db.query(Deal).filter(Deal.id == cid).first()
                if rec: record_context = f"\n=== СДЕЛКА #{cid} ===\nНазвание: {rec.title}\nКлиент: {rec.contact.name if rec.contact else '—'}\nСтадия: {rec.stage.name if rec.stage else '—'}\nСумма: {rec.total or 0:,.0f}₽\nАдрес: {rec.address or '—'}\nЗаметки: {(rec.notes or '')[:300]}\n"
            elif ctype == "task":
                rec = db.query(Task).filter(Task.id == cid).first()
                if rec: record_context = f"\n=== ЗАДАЧА #{cid} ===\n{rec.title}\nСтатус: {rec.status}\nПриоритет: {rec.priority}\nСрок: {rec.due_date or '—'}\nОписание: {(rec.description or '')[:300]}\n"
            elif ctype == "expense":
                rec = db.query(Expense).filter(Expense.id == cid).first()
                if rec: record_context = f"\n=== РАСХОД #{cid} ===\n{rec.name}\nСумма: {rec.amount:,.0f}₽\nДата: {rec.date}\nКатегория: {rec.category.name if rec.category else '—'}\n"
            elif ctype == "contact":
                rec = db.query(Contact).filter(Contact.id == cid).first()
                if rec: record_context = f"\n=== КЛИЕНТ #{cid} ===\n{rec.name}\nТелефон: {rec.phone or '—'}\nПосёлок: {rec.settlement or '—'}\nПлощадь: {rec.plot_area or '—'} сот\n"
        except Exception: pass

    system_prompt = ("Ты AI-ассистент CRM для сервиса покоса и ландшафтных работ GrassCRM. "
                     "Тебе передан полный контекст бизнеса. Отвечай строго на русском, коротко и по делу.")

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(f"{base_url.rstrip('/')}/chat/completions",
                                  json={"model": model, "temperature": 0.4,
                                        "messages": [{"role":"system","content":system_prompt},
                                                     {"role":"user","content":f"Контекст CRM:\n{context}{record_context}\n\nЗапрос: {payload.prompt}"}]},
                                  headers={"Authorization": f"Bearer {access_id}", "Content-Type": "application/json"})
    except Exception as e:
        raise HTTPException(502, f"Ошибка подключения к AI API: {e}")

    if not r.is_success: raise HTTPException(502, f"AI API {r.status_code}: {r.text[:300]}")
    data = r.json()
    text_out = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
    if not text_out: raise HTTPException(502, "AI API вернул пустой ответ")

    usage = data.get("usage") or {}
    if usage:
        try:
            db.add(AiUsageLog(prompt_tokens=usage.get("prompt_tokens",0), completion_tokens=usage.get("completion_tokens",0), total_tokens=usage.get("total_tokens",0), source="crm"))
            db.commit()
        except Exception: db.rollback()

    return {"ok": True, "answer": text_out, "model": model, "year": req_year}


# ── AI ACTION ─────────────────────────────────────────────────────────────────
@router.post("/api/service/ai/action")
async def service_ai_action(payload: AIActionRequest, db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")
    from app.models import Task as TaskModel
    from app.security import is_won_stage as _is_won
    action = (payload.action or "").strip(); data = payload.data or {}

    if action == "create_task":
        title = (data.get("title") or "").strip()
        if not title: raise HTTPException(400, "Поле title обязательно")
        contact_id = data.get("contact_id")
        if not contact_id and data.get("contact_name"):
            c = db.query(Contact).filter(Contact.name.ilike(f"%{data['contact_name']}%")).first()
            contact_id = c.id if c else None
        due = None
        if data.get("due_date"):
            try: due = date.fromisoformat(str(data["due_date"])[:10])
            except Exception: pass
        task = TaskModel(title=title, description=data.get("description"), due_date=due,
                    priority=data.get("priority") or "Обычный", status="Открыта",
                    contact_id=contact_id, deal_id=data.get("deal_id"))
        db.add(task); db.commit(); db.refresh(task); _cache.invalidate("tasks")
        return {"ok": True, "action": action, "id": task.id, "title": task.title}

    if action == "create_expense":
        name = (data.get("name") or "").strip(); amount = data.get("amount")
        if not name or amount is None: raise HTTPException(400, "Поля name и amount обязательны")
        exp_date = date.today()
        if data.get("date"):
            try: exp_date = date.fromisoformat(str(data["date"])[:10])
            except Exception: pass
        cat_name = (data.get("category") or "Прочее").strip()
        cat = db.query(ExpenseCategory).filter(ExpenseCategory.name.ilike(cat_name)).first() or db.query(ExpenseCategory).first()
        expense = Expense(name=name, amount=float(amount), date=exp_date, category_id=cat.id if cat else None)
        db.add(expense); db.commit(); db.refresh(expense); _cache.invalidate("expenses")
        return {"ok": True, "action": action, "id": expense.id, "name": expense.name}

    if action == "create_deal":
        title = (data.get("title") or "").strip()
        if not title: raise HTTPException(400, "Поле title обязательно")
        contact_id = data.get("contact_id")
        if not contact_id:
            cname = (data.get("contact_name") or "Неизвестный клиент").strip()
            phone  = data.get("phone")
            contact = None
            if phone: contact = db.query(Contact).filter(Contact.phone == phone).first()
            if not contact: contact = db.query(Contact).filter(Contact.name.ilike(f"%{cname}%")).first()
            if not contact:
                contact = Contact(name=cname, phone=phone); db.add(contact); db.flush(); db.refresh(contact)
            contact_id = contact.id
        first_stage = db.query(Stage).order_by(Stage.order.asc()).first()
        deal = Deal(title=title, contact_id=contact_id, stage_id=first_stage.id if first_stage else None,
                    notes=data.get("notes") or "", address=data.get("address") or "")
        db.add(deal); db.commit(); db.refresh(deal); _cache.invalidate("deals","years")
        return {"ok": True, "action": action, "id": deal.id, "title": deal.title}

    if action == "change_status":
        deal_id = data.get("deal_id")
        if not deal_id: raise HTTPException(400, "Поле deal_id обязательно")
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if not deal: raise HTTPException(404, f"Сделка #{deal_id} не найдена")
        stage = None
        if data.get("stage_id"):    stage = db.query(Stage).filter(Stage.id == data["stage_id"]).first()
        elif data.get("stage_name"): stage = db.query(Stage).filter(Stage.name.ilike(f"%{data['stage_name']}%")).first()
        if not stage: raise HTTPException(404, f"Стадия не найдена. Доступные: {[s.name for s in db.query(Stage).order_by(Stage.order).all()]}")
        old_stage = deal.stage.name if deal.stage else "—"
        deal.stage_id = stage.id
        if _is_won(stage): deal.closed_at = datetime.utcnow()
        db.commit(); _cache.invalidate("deals","years")
        return {"ok": True, "action": action, "deal_id": deal_id, "from": old_stage, "to": stage.name}

    if action == "add_comment":
        deal_id = data.get("deal_id"); comment_text = (data.get("text") or "").strip()
        if not deal_id or not comment_text: raise HTTPException(400, "Поля deal_id и text обязательны")
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if not deal: raise HTTPException(404, f"Сделка #{deal_id} не найдена")
        comment = DealComment(deal_id=deal_id, text=comment_text, user_name=user.get("name") or "AI", user_id=user.get("sub"))
        db.add(comment); db.commit(); db.refresh(comment)
        return {"ok": True, "action": action, "deal_id": deal_id, "comment_id": comment.id}

    raise HTTPException(400, f"Неизвестный action: '{action}'. Доступные: create_task, create_deal, create_expense, change_status, add_comment")


# ── AI MEMORY ─────────────────────────────────────────────────────────────────
@router.post("/api/service/ai/memory", status_code=201)
def ai_memory_save(payload: AiMemorySaveRequest, db: DBSession = Depends(get_db), _: dict = Depends(get_current_user)):
    from datetime import timedelta as _td
    expires = datetime.utcnow() + _td(days=payload.ttl_days) if payload.ttl_days else None
    if payload.memory_type == "message":
        from datetime import timedelta as _td2
        cutoff = datetime.utcnow() - _td2(minutes=5)
        exists = db.query(AiMemory).filter(AiMemory.chat_id == str(payload.chat_id), AiMemory.content == payload.content, AiMemory.created_at >= cutoff).first()
        if exists: return {"ok": True, "id": exists.id, "duplicate": True}
    mem = AiMemory(chat_id=str(payload.chat_id), role=payload.role, content=payload.content[:2000],
                   memory_type=payload.memory_type, importance=payload.importance, metadata_=payload.metadata, expires_at=expires)
    db.add(mem); db.commit(); db.refresh(mem)
    return {"ok": True, "id": mem.id}


@router.get("/api/service/ai/memory")
def ai_memory_search(chat_id: str, q: Optional[str] = None, memory_type: Optional[str] = None,
                     limit: int = 20, db: DBSession = Depends(get_db), _: dict = Depends(get_current_user)):
    now = datetime.utcnow()
    base_q = db.query(AiMemory).filter(AiMemory.chat_id == str(chat_id)).filter((AiMemory.expires_at == None) | (AiMemory.expires_at > now))
    if memory_type: base_q = base_q.filter(AiMemory.memory_type == memory_type)
    facts       = base_q.filter(AiMemory.memory_type.in_(["fact","preference"])).order_by(AiMemory.importance.desc(), AiMemory.created_at.desc()).limit(30).all()
    recent_msgs = base_q.filter(AiMemory.memory_type == "message").order_by(AiMemory.created_at.desc()).limit(10).all()
    search_res  = base_q.filter(AiMemory.content.ilike(f"%{q.strip()}%")).order_by(AiMemory.importance.desc(), AiMemory.created_at.desc()).limit(10).all() if q and len(q.strip()) >= 3 else []

    def _fmt(m): return {"id": m.id, "role": m.role, "content": m.content, "memory_type": m.memory_type, "importance": m.importance, "created_at": m.created_at.isoformat() if m.created_at else None, "metadata": m.metadata_ or {}}
    seen, merged = set(), []
    for m in list(facts) + list(search_res) + list(reversed(recent_msgs)):
        if m.id not in seen: seen.add(m.id); merged.append(_fmt(m))
    return {"ok": True, "count": len(merged), "memories": merged}


@router.delete("/api/service/ai/memory")
def ai_memory_clear(chat_id: str, memory_type: Optional[str] = None, db: DBSession = Depends(get_db), _: dict = Depends(get_current_user)):
    q = db.query(AiMemory).filter(AiMemory.chat_id == str(chat_id))
    if memory_type: q = q.filter(AiMemory.memory_type == memory_type)
    deleted = q.delete(synchronize_session=False); db.commit()
    return {"ok": True, "deleted": deleted}


@router.get("/api/service/ai/usage")
def service_ai_usage(db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")
    quota = int(os.getenv("AI_TOKEN_QUOTA", "500000"))
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total  = db.execute(text("SELECT COALESCE(SUM(total_tokens),0) FROM ai_usage_log")).scalar() or 0
    today  = db.execute(text("SELECT COALESCE(SUM(total_tokens),0) FROM ai_usage_log WHERE created_at >= :ts"), {"ts": today_start}).scalar() or 0
    month  = db.execute(text("SELECT COALESCE(SUM(total_tokens),0) FROM ai_usage_log WHERE created_at >= :ts"), {"ts": month_start}).scalar() or 0
    calls_total = db.execute(text("SELECT COUNT(*) FROM ai_usage_log")).scalar() or 0
    calls_month = db.execute(text("SELECT COUNT(*) FROM ai_usage_log WHERE created_at >= :ts"), {"ts": month_start}).scalar() or 0
    return {"quota": quota, "used_total": int(total), "used_month": int(month), "used_today": int(today),
            "remaining": max(0, quota - int(total)), "pct": round(int(total)/quota*100,1) if quota else 0,
            "calls_total": int(calls_total), "calls_month": int(calls_month)}


# ── VERSION + RESTART ─────────────────────────────────────────────────────────
@version_router.get("/api/version")
def get_version(db: DBSession = Depends(get_db), _: dict = Depends(get_current_user)):
    import subprocess as _sp, sys
    try: commit = _sp.check_output(["git","rev-parse","--short","HEAD"], cwd="/var/www/crm/GCRM-2", text=True).strip()
    except Exception: commit = "—"
    try: commit_date = _sp.check_output(["git","log","-1","--format=%ci"], cwd="/var/www/crm/GCRM-2", text=True).strip()[:16]
    except Exception: commit_date = "—"
    try: import fastapi as _fa; fastapi_ver = _fa.__version__
    except Exception: fastapi_ver = "—"
    try: import sqlalchemy as _sa; sa_ver = _sa.__version__
    except Exception: sa_ver = "—"
    try: db_ver = db.execute(text("SELECT version()")).scalar().split(",")[0]
    except Exception: db_ver = "—"
    return {"backend": "main.py v8.0.5", "api": "8.0.5", "commit": commit, "commit_date": commit_date,
            "python": sys.version.split()[0], "fastapi": fastapi_ver, "sqlalchemy": sa_ver, "database": db_ver}


@version_router.post("/api/service/restart")
def service_restart(user: dict = Depends(get_current_user)):
    if not is_admin(user): raise HTTPException(403, "Admin only")
    import subprocess as _sp, threading as _th
    def _do():
        import time as _t; _t.sleep(2); _sp.Popen(["systemctl","restart","crm"])
    _th.Thread(target=_do, daemon=True).start()
    return {"ok": True, "message": "Перезапуск через 2 секунды…"}
