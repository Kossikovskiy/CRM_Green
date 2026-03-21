# GrassCRM — app/migrations.py v8.0.1

import os
import threading
from datetime import datetime, date

from sqlalchemy import text, inspect as sa_inspect

from app.database import engine, SessionFactory
from app.models import (
    Stage, Deal, DealService, DealComment, Contact, Budget,
)
from app.logging_setup import logger
from app.security import is_lost_stage


# ── ВСПОМОГАТЕЛЬНЫЕ ───────────────────────────────────────────────────────────
def _add_column_if_missing(db, table: str, column: str, col_type: str):
    """Проверяет information_schema перед ALTER TABLE — не падает если уже есть."""
    try:
        result = db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ), {"t": table, "c": column}).fetchone()
        if not result:
            db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            db.commit()
            logger.info("Added column %s.%s", table, column)
    except Exception as e:
        db.rollback()
        logger.warning("_add_column_if_missing %s.%s: %s", table, column, e)


# ── ENSURE ФУНКЦИИ ────────────────────────────────────────────────────────────
def _ensure_budget_table():
    insp = sa_inspect(engine)
    if not insp.has_table("budgets"):
        Budget.__table__.create(engine)


def _ensure_users_telegram_column():
    insp = sa_inspect(engine)
    if not insp.has_table("users"):
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    with engine.begin() as conn:
        if "telegram_id" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN telegram_id VARCHAR(50)"))
        try:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_telegram_id ON users (telegram_id)"
            ))
        except Exception:
            pass


def _ensure_user_last_login():
    with SessionFactory() as db:
        _add_column_if_missing(db, "users", "last_login", "TIMESTAMP")


def _ensure_repeat_columns():
    """Добавить repeat_interval_days и next_repeat_date в deals."""
    with SessionFactory() as db:
        _add_column_if_missing(db, "deals", "repeat_interval_days", "INTEGER")
        _add_column_if_missing(db, "deals", "next_repeat_date", "DATE")


def _ensure_duration_hours():
    with SessionFactory() as db:
        _add_column_if_missing(db, "deals", "duration_hours", "FLOAT")


def _ensure_deals_discount_type():
    insp = sa_inspect(engine)
    if not insp.has_table("deals"):
        return
    cols = {c["name"] for c in insp.get_columns("deals")}
    if "discount_type" not in cols:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE deals ADD COLUMN discount_type VARCHAR(10) DEFAULT 'percent' NOT NULL"
            ))


def _ensure_files_kind_column():
    insp = sa_inspect(engine)
    if not insp.has_table("crm_files"):
        return
    cols = {c["name"] for c in insp.get_columns("crm_files")}
    if "file_kind" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE crm_files ADD COLUMN file_kind VARCHAR(20)"))


def _ensure_contacts_telegram_columns():
    insp = sa_inspect(engine)
    if not insp.has_table("contacts"):
        return
    cols = {c["name"] for c in insp.get_columns("contacts")}
    with engine.begin() as conn:
        if "telegram_id" not in cols:
            conn.execute(text("ALTER TABLE contacts ADD COLUMN telegram_id VARCHAR(50)"))
        if "telegram_username" not in cols:
            conn.execute(text("ALTER TABLE contacts ADD COLUMN telegram_username VARCHAR(100)"))
        if "addresses" not in cols:
            conn.execute(text("ALTER TABLE contacts ADD COLUMN addresses TEXT"))
        try:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_contacts_telegram_id "
                "ON contacts (telegram_id) WHERE telegram_id IS NOT NULL"
            ))
        except Exception:
            pass

    # deal_materials table
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS deal_materials (
                    id SERIAL PRIMARY KEY,
                    deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
                    name VARCHAR(200) NOT NULL,
                    quantity FLOAT NOT NULL DEFAULT 1.0,
                    cost_price FLOAT NOT NULL DEFAULT 0.0,
                    sell_price FLOAT NOT NULL DEFAULT 0.0
                )
            """))
            conn.commit()
        except Exception:
            pass

    # tax_on_materials column
    with engine.connect() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE deals ADD COLUMN tax_on_materials BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            conn.commit()
        except Exception:
            pass

    # revenue column
    with engine.connect() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE deals ADD COLUMN revenue FLOAT NOT NULL DEFAULT 0.0"
            ))
            conn.commit()
        except Exception:
            pass


def _ensure_archive_columns():
    insp = sa_inspect(engine)
    if not insp.has_table("deals"):
        return
    cols = {c["name"] for c in insp.get_columns("deals")}
    with engine.begin() as conn:
        if "is_archived" not in cols:
            conn.execute(text(
                "ALTER TABLE deals ADD COLUMN is_archived BOOLEAN DEFAULT FALSE NOT NULL"
            ))
        if "archived_at" not in cols:
            conn.execute(text("ALTER TABLE deals ADD COLUMN archived_at TIMESTAMP"))


def _ensure_project_columns():
    """Добавить колонку project во все нужные таблицы."""
    insp = sa_inspect(engine)
    tables = ["deals", "tasks", "expenses", "stages", "budgets"]
    with engine.begin() as conn:
        for table in tables:
            if not insp.has_table(table):
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            if "project" not in cols:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN project VARCHAR(20) DEFAULT 'pokos' NOT NULL"
                ))
                logger.info("_ensure_project_columns: added project to %s", table)


def _ensure_electric_services_tables():
    """Создать таблицы electric_services и deal_electric_services если не существуют."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS electric_services (
                id SERIAL PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                price FLOAT DEFAULT 0.0,
                unit VARCHAR(50) DEFAULT 'шт',
                min_volume FLOAT DEFAULT 1.0,
                notes TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS deal_electric_services (
                id SERIAL PRIMARY KEY,
                deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
                electric_service_id INTEGER NOT NULL REFERENCES electric_services(id) ON DELETE RESTRICT,
                quantity FLOAT DEFAULT 1.0,
                price_at_moment FLOAT NOT NULL
            )
        """))


def _ensure_stages_name_project_unique():
    """Заменить уникальный индекс stages.name на уникальный (name, project)."""
    with engine.begin() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE stages DROP CONSTRAINT IF EXISTS stages_name_key"
            ))
        except Exception:
            pass
        try:
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS ix_stages_name_project
                ON stages (name, project)
            """))
        except Exception:
            pass


# ── СИДЫ ──────────────────────────────────────────────────────────────────────
def _seed_electric_stages():
    """Создать/переименовать этапы для проекта electric."""
    target_stages = [
        {"name": "Оценка",     "order": 1, "color": "#3B82F6", "project": "electric", "is_final": False},
        {"name": "Согласован", "order": 2, "color": "#8B5CF6", "project": "electric", "is_final": False},
        {"name": "Монтаж",     "order": 3, "color": "#06B6D4", "project": "electric", "is_final": False},
        {"name": "Выполнен",   "order": 4, "color": "#10B981", "project": "electric", "is_final": True},
        {"name": "Отказ",      "order": 5, "color": "#EF4444", "project": "electric", "is_final": True},
    ]
    rename_map = {
        "Elec: Оценка":     "Оценка",
        "Elec: Согласован": "Согласован",
        "Elec: В работе":   "Монтаж",
        "Elec: Выполнен":   "Выполнен",
        "Elec: Провалена":  "Отказ",
    }
    with SessionFactory() as db:
        for old_name, new_name in rename_map.items():
            stage = db.query(Stage).filter(
                Stage.name == old_name, Stage.project == "electric"
            ).first()
            if stage:
                stage.name = new_name
                stage.is_final = new_name in ("Выполнен", "Отказ")
        db.commit()
        existing = {s.name for s in db.query(Stage).filter(Stage.project == "electric").all()}
        for sd in target_stages:
            if sd["name"] not in existing:
                db.add(Stage(**sd))
        db.commit()


# ── ВОРКЕРЫ ───────────────────────────────────────────────────────────────────
def _send_tg_sync(text_msg: str):
    """Fire-and-forget уведомление через бот отчётов."""
    import requests as _req
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat  = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    try:
        _req.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text_msg, "parse_mode": "HTML"},
            timeout=8,
        )
    except Exception as e:
        logger.warning("TG notify error: %s", e)


def _process_repeat_deals():
    from datetime import date as _date, timedelta as _td
    today   = _date.today()
    horizon = today + _td(days=3)  # создаём за 3 дня до выезда

    with SessionFactory() as db:
        lost_stage_ids = {s.id for s in db.query(Stage).all() if is_lost_stage(s)}
        first_stage    = db.query(Stage).order_by(Stage.order).first()

        deals = (
            db.query(Deal)
            .filter(Deal.repeat_interval_days.isnot(None))
            .filter(Deal.next_repeat_date.isnot(None))
            .filter(Deal.next_repeat_date <= horizon)
            .all()
        )

        for deal in deals:
            if deal.stage_id in lost_stage_ids:
                deal.repeat_interval_days = None
                deal.next_repeat_date     = None
                db.commit()
                continue

            repeat_date = deal.next_repeat_date
            day_start   = datetime.combine(repeat_date, datetime.min.time())
            day_end     = datetime.combine(repeat_date, datetime.max.time())
            existing    = db.query(Deal).filter(
                Deal.contact_id == deal.contact_id,
                Deal.deal_date  >= day_start,
                Deal.deal_date  <= day_end,
                Deal.title      == deal.title,
                Deal.id         != deal.id,
                Deal.is_repeat  == True,
            ).first()

            if not existing:
                from datetime import timedelta as _td2
                next_date = repeat_date + _td2(days=deal.repeat_interval_days)

                new_deal = Deal(
                    contact_id   = deal.contact_id,
                    stage_id     = first_stage.id if first_stage else deal.stage_id,
                    title        = deal.title,
                    notes        = deal.notes or "",
                    manager      = deal.manager,
                    address      = deal.address,
                    tax_rate     = deal.tax_rate,
                    tax_included = deal.tax_included,
                    discount     = deal.discount,
                    discount_type= deal.discount_type,
                    deal_date    = datetime.combine(repeat_date, datetime.min.time()),
                    is_repeat    = True,
                    repeat_interval_days = deal.repeat_interval_days,
                    next_repeat_date     = next_date,
                )
                db.add(new_deal)
                db.flush()
                db.refresh(new_deal)

                for ds in deal.services:
                    db.add(DealService(
                        deal_id         = new_deal.id,
                        service_id      = ds.service_id,
                        quantity        = ds.quantity,
                        price_at_moment = ds.price_at_moment,
                    ))
                db.flush()

                subtotal = sum(s.price_at_moment * s.quantity for s in new_deal.services)
                disc     = deal.discount or 0
                disc_amt = min(disc, subtotal) if deal.discount_type == "fixed" \
                           else subtotal * (disc / 100.0)
                after_disc = subtotal - disc_amt
                tax_amt    = after_disc * ((deal.tax_rate or 0) / 100.0)
                new_deal.total = round(after_disc + (0 if deal.tax_included else tax_amt), 2)

                deal.repeat_interval_days = None
                deal.next_repeat_date     = None
                db.commit()

                # Telegram уведомление
                contact      = db.query(Contact).filter(Contact.id == deal.contact_id).first()
                _contact_name = contact.name if contact else "—"
                _phone        = (contact.phone if contact else "") or ""
                _svc_lines    = []
                for si in new_deal.services:
                    _qty   = si.quantity or 1
                    _price = float(si.price_at_moment or 0)
                    _line  = _price * _qty
                    _price_str = f" — {int(_line):,} ".replace(",", "\u00a0") if _price else ""
                    _svc_lines.append(f"  · {si.service.name} × {_qty}{_price_str}")
                _lines = [f"<b>Сделка №{new_deal.id} — {deal.title}</b> (повтор)"]
                _lines.append(repeat_date.strftime("%d.%m.%Y"))
                _lines.append(f"Клиент: {_contact_name}")
                if _phone:
                    _lines.append(f"Телефон: {_phone}")
                if deal.address:
                    _lines.append(f"Адрес: {deal.address}")
                if _svc_lines:
                    _lines.append("")
                    _lines.append("Услуги:")
                    _lines.extend(_svc_lines)
                if new_deal.total:
                    _lines.append("")
                    _lines.append(f"Итого: {int(new_deal.total):,} ₽".replace(",", "\u00a0"))
                _lines.append("")
                _lines.append(f"Следующий повтор: {next_date.strftime('%d.%m.%Y')}")
                threading.Thread(
                    target=_send_tg_sync, args=("\n".join(_lines),), daemon=True
                ).start()


def _repeat_deals_worker():
    """Background thread: каждые 60 мин проверяет и создаёт повторные сделки."""
    import time as _t
    while True:
        try:
            _process_repeat_deals()
        except Exception as e:
            logger.error("repeat_deals_worker error: %s", e)
        _t.sleep(3600)


def _process_expired_archives():
    from datetime import timedelta as _td
    threshold = datetime.utcnow() - _td(days=30)
    with SessionFactory() as db:
        lost_stage = next(
            (s for s in db.query(Stage).all() if is_lost_stage(s)), None
        )
        if not lost_stage:
            return
        expired = db.query(Deal).filter(
            Deal.is_archived == True,
            Deal.archived_at <= threshold,
        ).all()
        for deal in expired:
            deal.is_archived  = False
            deal.archived_at  = None
            deal.stage_id     = lost_stage.id
            deal.repeat_interval_days = None
            deal.next_repeat_date     = None
            db.flush()
            db.add(DealComment(
                deal_id   = deal.id,
                text      = "Причина провала: Истёк срок архива (30 дней)",
                user_name = "Система",
            ))
        db.commit()
        if expired:
            logger.info("archive_expired: %d deals moved to failed stage", len(expired))


def _archive_expired_worker():
    """Background thread: каждые 60 мин проверяет архивированные сделки."""
    import time as _t
    while True:
        try:
            _process_expired_archives()
        except Exception as e:
            logger.error("archive_expired_worker error: %s", e)
        _t.sleep(3600)
