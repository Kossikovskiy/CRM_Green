# GrassCRM — app/models.py v8.0.1

from datetime import datetime, date

from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime,
    Boolean, ForeignKey, Text, Double,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ── ПОЛЬЗОВАТЕЛИ ───────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"
    id         = Column(String, primary_key=True)
    username   = Column(String)
    name       = Column(String)
    email      = Column(String)
    role       = Column(String, default="User")
    telegram_id = Column(String(50), unique=True, index=True, nullable=True)
    last_login = Column(DateTime, nullable=True)


# ── УСЛУГИ ─────────────────────────────────────────────────────────────────────
class Service(Base):
    __tablename__ = "services"
    id         = Column(Integer, primary_key=True)
    name       = Column(String(200), nullable=False)
    price      = Column(Float, default=0.0)
    unit       = Column(String(50), default="шт")
    min_volume = Column(Float, default=1.0)
    notes      = Column(Text)


class DealService(Base):
    __tablename__ = "deal_services"
    id              = Column(Integer, primary_key=True)
    deal_id         = Column(Integer, ForeignKey("deals.id", ondelete="CASCADE"))
    service_id      = Column(Integer, ForeignKey("services.id", ondelete="RESTRICT"))
    quantity        = Column(Float, default=1.0)
    price_at_moment = Column(Float, nullable=False)
    service         = relationship("Service")


class ElectricService(Base):
    __tablename__ = "electric_services"
    id         = Column(Integer, primary_key=True)
    name       = Column(String(200), nullable=False)
    price      = Column(Float, default=0.0)
    unit       = Column(String(50), default="шт")
    min_volume = Column(Float, default=1.0)
    notes      = Column(Text)


class DealElectricService(Base):
    __tablename__ = "deal_electric_services"
    id                  = Column(Integer, primary_key=True)
    deal_id             = Column(Integer, ForeignKey("deals.id", ondelete="CASCADE"))
    electric_service_id = Column(Integer, ForeignKey("electric_services.id", ondelete="RESTRICT"))
    quantity            = Column(Float, default=1.0)
    price_at_moment     = Column(Float, nullable=False)
    service             = relationship("ElectricService")


# ── МАТЕРИАЛЫ ──────────────────────────────────────────────────────────────────
class DealMaterial(Base):
    __tablename__ = "deal_materials"
    id          = Column(Integer, primary_key=True)
    deal_id     = Column(Integer, ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    name        = Column(String(200), nullable=False)
    quantity    = Column(Float, default=1.0, nullable=False)
    cost_price  = Column(Float, default=0.0, nullable=False)  # стоимость закупки
    sell_price  = Column(Float, default=0.0, nullable=False)  # стоимость для клиента


# ── ЭТАПЫ ──────────────────────────────────────────────────────────────────────
class Stage(Base):
    __tablename__ = "stages"
    id       = Column(Integer, primary_key=True)
    name     = Column(String(100), nullable=False)
    order    = Column(Integer, default=0)
    type     = Column(String(50), default="regular")
    is_final = Column(Boolean, default=False)
    color    = Column(String(20), default="#6B7280")
    project  = Column(String(20), default="pokos", nullable=False)
    deals    = relationship("Deal", back_populates="stage")


# ── КОНТАКТЫ ───────────────────────────────────────────────────────────────────
class Contact(Base):
    __tablename__ = "contacts"
    id                = Column(Integer, primary_key=True)
    name              = Column(String(200), nullable=False)
    phone             = Column(String(50), unique=True, index=True)
    source            = Column(String(100))
    telegram_id       = Column(String(50), unique=True, index=True, nullable=True)
    telegram_username = Column(String(100), nullable=True)
    addresses         = Column(Text, nullable=True)           # JSON-список адресов
    settlement        = Column(String(200), nullable=True)    # Название поселка/СНТ
    plot_area         = Column(Float, nullable=True)          # Количество соток
    deals             = relationship("Deal", back_populates="contact")


# ── СДЕЛКИ ─────────────────────────────────────────────────────────────────────
class Deal(Base):
    __tablename__ = "deals"
    id                   = Column(Integer, primary_key=True)
    contact_id           = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    stage_id             = Column(Integer, ForeignKey("stages.id"))
    title                = Column(String(200), nullable=False)
    total                = Column(Float, default=0.0)
    notes                = Column(Text, default="")
    created_at           = Column(DateTime, default=datetime.utcnow)
    deal_date            = Column(DateTime)
    closed_at            = Column(DateTime)
    is_repeat            = Column(Boolean, default=False)
    manager              = Column(String(200))
    address              = Column(Text)
    tax_rate             = Column(Float, default=4.0, nullable=False)
    tax_included         = Column(Boolean, default=True, nullable=False)
    tax_on_materials     = Column(Boolean, default=False, nullable=False)
    revenue              = Column(Float, default=0.0, nullable=False)  # выручка = total - закупка материалов
    discount             = Column(Float, default=0.0, nullable=False)
    discount_type        = Column(String(10), default="percent", nullable=False)
    repeat_interval_days = Column(Integer, nullable=True)   # NULL = не повторяется
    next_repeat_date     = Column(Date, nullable=True)      # дата следующего выезда
    is_archived          = Column(Boolean, default=False, nullable=False)
    archived_at          = Column(DateTime, nullable=True)
    project              = Column(String(20), default="pokos", nullable=False)
    duration_hours       = Column(Float, nullable=True)     # часов потрачено на выезд

    contact          = relationship("Contact", back_populates="deals")
    stage            = relationship("Stage", back_populates="deals")
    services         = relationship("DealService", cascade="all, delete-orphan", passive_deletes=True)
    electric_services = relationship("DealElectricService", cascade="all, delete-orphan", passive_deletes=True)
    materials        = relationship("DealMaterial", cascade="all, delete-orphan", passive_deletes=True)


# ── ЗАДАЧИ ─────────────────────────────────────────────────────────────────────
class Task(Base):
    __tablename__ = "tasks"
    id          = Column(Integer, primary_key=True)
    title       = Column(String, nullable=False)
    description = Column(Text)
    is_done     = Column(Boolean, default=False)
    due_date    = Column(Date)
    assignee    = Column(String)
    priority    = Column(String, default="Обычный")
    status      = Column(String, default="Открыта")
    contact_id  = Column(Integer, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    deal_id     = Column(Integer, ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    project     = Column(String(20), default="pokos", nullable=False)
    contact     = relationship("Contact")
    deal        = relationship("Deal")


# ── ВЗАИМОДЕЙСТВИЯ ─────────────────────────────────────────────────────────────
class Interaction(Base):
    __tablename__ = "interactions"
    id         = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    type       = Column(String(50), nullable=False, default="note")  # call, email, meeting, note
    text       = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user_id    = Column(String)
    user_name  = Column(String)
    contact    = relationship("Contact")


# ── КОММЕНТАРИИ К СДЕЛКАМ ──────────────────────────────────────────────────────
class DealComment(Base):
    __tablename__ = "deal_comments"
    id         = Column(Integer, primary_key=True)
    deal_id    = Column(Integer, ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    text       = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user_id    = Column(String)
    user_name  = Column(String)
    deal       = relationship("Deal")


# ── ФАЙЛЫ ──────────────────────────────────────────────────────────────────────
class CRMFile(Base):
    __tablename__ = "crm_files"
    id               = Column(Integer, primary_key=True)
    filename         = Column(String(300), nullable=False)   # оригинальное имя файла
    stored_name      = Column(String(300), nullable=False)   # имя на диске (уникальное)
    size             = Column(Integer, default=0)            # байты
    mime_type        = Column(String(100))
    contact_id       = Column(Integer, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    deal_id          = Column(Integer, ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    uploaded_by      = Column(String)
    uploaded_by_name = Column(String)
    created_at       = Column(DateTime, default=datetime.utcnow)
    file_kind        = Column(String(20), nullable=True)     # before | after | general
    contact          = relationship("Contact")
    deal             = relationship("Deal")


# ── РАСХОДЫ ────────────────────────────────────────────────────────────────────
class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    id       = Column(Integer, primary_key=True)
    name     = Column(String(100), nullable=False, unique=True)
    expenses = relationship("Expense", back_populates="category")


class Expense(Base):
    __tablename__ = "expenses"
    id          = Column(Integer, primary_key=True)
    date        = Column(Date, nullable=False, default=date.today)
    name        = Column(String(300), nullable=False)
    amount      = Column(Float, nullable=False)
    category_id = Column(Integer, ForeignKey("expense_categories.id"))
    equipment_id = Column(Integer, ForeignKey("equipment.id"))
    project     = Column(String(20), default="pokos", nullable=False)
    category    = relationship("ExpenseCategory", back_populates="expenses")
    equipment   = relationship("Equipment", back_populates="expenses")


class TaxPayment(Base):
    __tablename__ = "tax_payments"
    id         = Column(Integer, primary_key=True)
    amount     = Column(Float, nullable=False)
    date       = Column(Date, nullable=False, default=date.today)
    note       = Column(Text)
    year       = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── ТЕХНИКА ────────────────────────────────────────────────────────────────────
class Consumable(Base):
    __tablename__ = "consumables"
    id             = Column(Integer, primary_key=True)
    name           = Column(String(200), nullable=False, unique=True)
    unit           = Column(String(50), default="шт")
    stock_quantity = Column(Float, default=0.0)
    notes          = Column(Text)
    price          = Column(Float, default=0.0)


class Equipment(Base):
    __tablename__ = "equipment"
    id                   = Column(Integer, primary_key=True)
    name                 = Column(String(200), nullable=False)
    model                = Column(String(200), default="")
    serial               = Column(String(100))
    purchase_date        = Column(Date)
    purchase_cost        = Column(Double, default=0.0)
    status               = Column(String(50), default="active")
    notes                = Column(Text)
    engine_hours         = Column(Double, default=0.0)
    fuel_norm            = Column(Double, default=0.0)
    last_maintenance_date  = Column(Date)
    next_maintenance_date  = Column(Date)
    expenses             = relationship("Expense", back_populates="equipment")
    maintenance_records  = relationship("EquipmentMaintenance", back_populates="equipment", cascade="all, delete-orphan")


class EquipmentMaintenance(Base):
    __tablename__ = "equipment_maintenance"
    id               = Column(Integer, primary_key=True)
    equipment_id     = Column(Integer, ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False)
    date             = Column(Date, nullable=False)
    work_description = Column(Text, nullable=False)
    cost             = Column(Float)
    notes            = Column(Text)
    equipment        = relationship("Equipment", back_populates="maintenance_records")
    consumables_used = relationship("MaintenanceConsumable", back_populates="maintenance_record", cascade="all, delete-orphan")


class MaintenanceConsumable(Base):
    __tablename__ = "maintenance_consumables"
    id               = Column(Integer, primary_key=True)
    maintenance_id   = Column(Integer, ForeignKey("equipment_maintenance.id", ondelete="CASCADE"), nullable=False)
    consumable_id    = Column(Integer, ForeignKey("consumables.id", ondelete="RESTRICT"), nullable=False)
    quantity         = Column(Float, nullable=False)
    price_at_moment  = Column(Float, nullable=False)
    consumable       = relationship("Consumable")
    maintenance_record = relationship("EquipmentMaintenance", back_populates="consumables_used")


# ── AI / ПАМЯТЬ ────────────────────────────────────────────────────────────────
class DailyPhrase(Base):
    __tablename__ = "daily_phrases"
    id         = Column(Integer, primary_key=True)
    phrase     = Column(Text, nullable=False)
    category   = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AiMemory(Base):
    """Долгосрочная память AI-ассистента."""
    __tablename__ = "ai_memory"
    id          = Column(Integer, primary_key=True)
    chat_id     = Column(String(50), nullable=False, index=True)
    role        = Column(String(20), nullable=False, default="user")   # user|assistant|fact
    content     = Column(Text, nullable=False)
    memory_type = Column(String(20), default="message")  # message|fact|preference
    importance  = Column(Integer, default=1)              # 1=обычное 2=важное 3=критическое
    metadata_   = Column("metadata", JSONB, default=dict)
    created_at  = Column(DateTime, default=datetime.utcnow)
    expires_at  = Column(DateTime, nullable=True)


class AiUsageLog(Base):
    __tablename__ = "ai_usage_log"
    id                = Column(Integer, primary_key=True)
    created_at        = Column(DateTime, default=datetime.utcnow)
    prompt_tokens     = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens      = Column(Integer, default=0)
    source            = Column(String(50), default="crm")


# ── БОТ / ЗАМЕТКИ ──────────────────────────────────────────────────────────────
class BotFaq(Base):
    __tablename__ = "bot_faq"
    id               = Column(Integer, primary_key=True)
    intent           = Column(String(100), nullable=False)
    question_example = Column(Text)
    answer           = Column(Text, nullable=False)
    priority         = Column(Integer, default=10)
    active           = Column(Boolean, default=True)


class Note(Base):
    __tablename__ = "notes"
    id         = Column(String, primary_key=True)
    user_id    = Column(String, nullable=False, index=True)
    title      = Column(Text, default="")
    body       = Column(Text, default="")
    color      = Column(String(50), default="")
    pinned     = Column(Boolean, default=False)
    label      = Column(String(100), default="")
    checklist  = Column(JSONB, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── БЮДЖЕТ ─────────────────────────────────────────────────────────────────────
class Budget(Base):
    __tablename__ = "budgets"
    id                = Column(Integer, primary_key=True)
    year              = Column(Integer, nullable=False)
    period            = Column(String(20), nullable=False)  # "year" | "q1"-"q4" | "jan"-"dec"
    name              = Column(String(200), nullable=False)
    planned_revenue   = Column(Float, default=0.0)
    planned_expenses  = Column(Float, default=0.0)
    notes             = Column(Text)
    project           = Column(String(20), default="pokos", nullable=False)
