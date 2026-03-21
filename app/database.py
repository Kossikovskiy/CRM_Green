# GrassCRM — app/database.py v8.0.1

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session as DBSession

from app.config import DATABASE_URL
from app.models import Base, Stage, ExpenseCategory


# ── ПОДКЛЮЧЕНИЕ ────────────────────────────────────────────────────────────────
engine         = create_engine(DATABASE_URL, client_encoding="utf8")
SessionFactory = sessionmaker(bind=engine, autoflush=False)


# ── ЗАВИСИМОСТИ FastAPI ────────────────────────────────────────────────────────
def get_db():
    db = SessionFactory()
    try:
        yield db
    finally:
        db.close()


def get_public_db():
    """Сессия для публичных эндпоинтов — переключается в роль anon для RLS."""
    db = SessionFactory()
    try:
        db.execute(text("SET LOCAL ROLE anon"))
        yield db
    finally:
        db.close()


# ── ИНИЦИАЛИЗАЦИЯ СХЕМЫ ────────────────────────────────────────────────────────
def init_db_structure():
    Base.metadata.create_all(engine)


def seed_initial_data(db: DBSession):
    if db.query(Stage).count() == 0:
        db.add_all([Stage(**d) for d in [
            {"name": "Согласовать", "order": 1, "color": "#3B82F6"},
            {"name": "Ожидание",    "order": 2, "color": "#F59E0B"},
            {"name": "В работе",    "order": 3, "color": "#EC4899"},
            {"name": "Успешно",     "order": 4, "color": "#10B981", "is_final": True},
            {"name": "Провалена",   "order": 5, "color": "#EF4444", "is_final": True},
        ]])
    if db.query(ExpenseCategory).count() == 0:
        db.add_all([ExpenseCategory(name=n) for n in
                    ["Техника", "Топливо", "Расходники", "Реклама", "Запчасти", "Прочее"]])
    db.commit()
