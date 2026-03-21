# GrassCRM — app/schemas.py v8.0.1

from datetime import date
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict


# ── УСЛУГИ ─────────────────────────────────────────────────────────────────────
class DealServiceItem(BaseModel):
    service_id:   int
    quantity:     float
    custom_price: Optional[float] = None

class DealElectricServiceItem(BaseModel):
    electric_service_id: int
    quantity:            float
    custom_price:        Optional[float] = None

class DealMaterialItem(BaseModel):
    name:       str
    quantity:   float
    cost_price: float
    sell_price: float

class ServiceCreate(BaseModel):
    name:       str   = Field(..., min_length=1)
    price:      float
    unit:       str
    min_volume: Optional[float] = 1.0
    notes:      Optional[str]  = None

class ServiceUpdate(BaseModel):
    name:       Optional[str]   = Field(None, min_length=1)
    price:      Optional[float] = None
    unit:       Optional[str]   = None
    min_volume: Optional[float] = None
    notes:      Optional[str]   = None

class ElectricServiceCreate(BaseModel):
    name:       str   = Field(..., min_length=1)
    price:      float = 0.0
    unit:       str   = "шт"
    min_volume: Optional[float] = 1.0
    notes:      Optional[str]  = None

class ElectricServiceUpdate(BaseModel):
    name:       Optional[str]   = Field(None, min_length=1)
    price:      Optional[float] = None
    unit:       Optional[str]   = None
    min_volume: Optional[float] = None
    notes:      Optional[str]   = None


# ── СДЕЛКИ ─────────────────────────────────────────────────────────────────────
class DealCreate(BaseModel):
    title:                str
    stage_id:             int
    contact_id:           Optional[int]   = None
    new_contact_name:     Optional[str]   = None
    manager:              Optional[str]   = None
    services:             List[DealServiceItem]        = []
    electric_services:    List[DealElectricServiceItem] = []
    materials:            List[DealMaterialItem]        = []
    tax_rate:             Optional[float] = 4.0
    tax_included:         Optional[bool]  = True
    tax_on_materials:     Optional[bool]  = False
    discount:             Optional[float] = 0.0
    discount_type:        Optional[str]   = "percent"
    work_date:            Optional[str]   = None
    work_time:            Optional[str]   = None
    address:              Optional[str]   = None
    repeat_interval_days: Optional[int]   = None
    next_repeat_date:     Optional[str]   = None
    project:              Optional[str]   = "pokos"
    duration_hours:       Optional[float] = None

class DealUpdate(BaseModel):
    title:                Optional[str]   = None
    stage_id:             Optional[int]   = None
    contact_id:           Optional[int]   = None
    new_contact_name:     Optional[str]   = None
    manager:              Optional[str]   = None
    services:             Optional[List[DealServiceItem]]  = None
    materials:            Optional[List[DealMaterialItem]] = None
    tax_rate:             Optional[float] = None
    tax_included:         Optional[bool]  = None
    tax_on_materials:     Optional[bool]  = None
    discount_type:        Optional[str]   = None
    work_date:            Optional[str]   = None
    work_time:            Optional[str]   = None
    address:              Optional[str]   = None
    repeat_interval_days: Optional[int]   = None
    next_repeat_date:     Optional[str]   = None
    duration_hours:       Optional[float] = None


# ── ЗАДАЧИ ─────────────────────────────────────────────────────────────────────
class TaskCreate(BaseModel):
    title:       str
    description: Optional[str]  = None
    due_date:    Optional[date]  = None
    priority:    Optional[str]   = "Обычный"
    status:      Optional[str]   = "Открыта"
    assignee:    Optional[str]   = None
    contact_id:  Optional[int]   = None
    deal_id:     Optional[int]   = None
    project:     Optional[str]   = "pokos"

class TaskUpdate(BaseModel):
    title:       Optional[str]  = None
    description: Optional[str]  = None
    due_date:    Optional[date]  = None
    priority:    Optional[str]   = None
    status:      Optional[str]   = None
    assignee:    Optional[str]   = None
    is_done:     Optional[bool]  = None
    contact_id:  Optional[int]   = None
    deal_id:     Optional[int]   = None


# ── КОНТАКТЫ ───────────────────────────────────────────────────────────────────
class ContactCreate(BaseModel):
    name:              str   = Field(..., min_length=1)
    phone:             Optional[str]        = None
    source:            Optional[str]        = None
    telegram_id:       Optional[str]        = None
    telegram_username: Optional[str]        = None
    addresses:         Optional[List[str]]  = None
    settlement:        Optional[str]        = None
    plot_area:         Optional[float]      = None

class ContactUpdate(BaseModel):
    name:              Optional[str]        = Field(None, min_length=1)
    phone:             Optional[str]        = None
    source:            Optional[str]        = None
    telegram_id:       Optional[str]        = None
    telegram_username: Optional[str]        = None
    addresses:         Optional[List[str]]  = None
    settlement:        Optional[str]        = None
    plot_area:         Optional[float]      = None


# ── ТЕХНИКА ────────────────────────────────────────────────────────────────────
class EquipmentCreate(BaseModel):
    name:                  str
    model:                 Optional[str]   = None
    serial:                Optional[str]   = None
    purchase_date:         Optional[date]  = None
    purchase_cost:         Optional[float] = None
    status:                Optional[str]   = "active"
    notes:                 Optional[str]   = None
    engine_hours:          Optional[float] = None
    fuel_norm:             Optional[float] = None
    last_maintenance_date: Optional[date]  = None
    next_maintenance_date: Optional[date]  = None

class EquipmentUpdate(BaseModel):
    name:                  Optional[str]   = None
    model:                 Optional[str]   = None
    serial:                Optional[str]   = None
    purchase_date:         Optional[date]  = None
    purchase_cost:         Optional[float] = None
    status:                Optional[str]   = None
    notes:                 Optional[str]   = None
    engine_hours:          Optional[float] = None
    fuel_norm:             Optional[float] = None
    last_maintenance_date: Optional[date]  = None
    next_maintenance_date: Optional[date]  = None

class ConsumableCreate(BaseModel):
    name:           str
    unit:           Optional[str]   = "шт"
    stock_quantity: Optional[float] = 0.0
    price:          Optional[float] = 0.0
    notes:          Optional[str]   = None

class ConsumableUpdate(BaseModel):
    name:           Optional[str]   = None
    unit:           Optional[str]   = None
    stock_quantity: Optional[float] = None
    price:          Optional[float] = None
    notes:          Optional[str]   = None

class MaintenanceConsumableItem(BaseModel):
    consumable_id: int
    quantity:      float

class MaintenanceCreate(BaseModel):
    equipment_id:     int
    date:             date
    work_description: str
    notes:            Optional[str]                         = None
    consumables:      List[MaintenanceConsumableItem]       = []

class MaintenanceUpdate(BaseModel):
    date:             Optional[date]                              = None
    work_description: Optional[str]                              = None
    notes:            Optional[str]                              = None
    consumables:      Optional[List[MaintenanceConsumableItem]]  = None


# ── РАСХОДЫ ────────────────────────────────────────────────────────────────────
class ExpenseCreate(BaseModel):
    name:     str
    amount:   float
    date:     str
    category: str
    project:  Optional[str] = "pokos"

class ExpenseUpdate(BaseModel):
    name:     Optional[str]   = None
    amount:   Optional[float] = None
    date:     Optional[str]   = None  # принимаем строкой, конвертируем вручную
    category: Optional[str]   = None

class TaxPaymentCreate(BaseModel):
    amount: float
    date:   date
    note:   Optional[str] = None
    year:   int

class TaxPaymentUpdate(BaseModel):
    amount: Optional[float] = None
    date:   Optional[date]  = None
    note:   Optional[str]   = None


# ── ВЗАИМОДЕЙСТВИЯ И КОММЕНТАРИИ ───────────────────────────────────────────────
class InteractionCreate(BaseModel):
    type: str = "note"
    text: str = Field(..., min_length=1)

class DealCommentCreate(BaseModel):
    text: str = Field(..., min_length=1)


# ── ПОЛЬЗОВАТЕЛИ ───────────────────────────────────────────────────────────────
class UserTelegramUpdate(BaseModel):
    telegram_id: Optional[str] = None


# ── AI ─────────────────────────────────────────────────────────────────────────
class ServiceAIAgentRequest(BaseModel):
    prompt:       str  = Field(..., min_length=3, max_length=5000)
    year:         Optional[int] = None
    base_url:     Optional[str] = None
    access_id:    Optional[str] = None
    model:        Optional[str] = None
    # Контекст записи (для AI-кнопок внутри сделки/задачи/расхода)
    context_type: Optional[str] = None  # 'deal' | 'task' | 'expense' | 'contact'
    context_id:   Optional[int] = None  # id записи

class AIActionRequest(BaseModel):
    """Запрос на выполнение AI-действия напрямую."""
    action: str
    data:   dict          = {}
    source: Optional[str] = "crm"

class AiMemorySaveRequest(BaseModel):
    chat_id:     str
    role:        str          = "user"      # user | assistant | fact
    content:     str
    memory_type: str          = "message"   # message | fact | preference
    importance:  int          = 1
    metadata:    dict         = {}
    ttl_days:    Optional[int] = None       # сколько дней хранить (None = вечно)


# ── ЗАМЕТКИ ────────────────────────────────────────────────────────────────────
class NoteCreate(BaseModel):
    id:        Optional[str] = None
    title:     str           = ""
    body:      str           = ""
    color:     str           = ""
    pinned:    bool          = False
    label:     str           = ""
    checklist: list          = []

class NoteUpdate(BaseModel):
    title:     Optional[str]  = None
    body:      Optional[str]  = None
    color:     Optional[str]  = None
    pinned:    Optional[bool] = None
    label:     Optional[str]  = None
    checklist: Optional[list] = None


# ── БЮДЖЕТ ─────────────────────────────────────────────────────────────────────
class BudgetCreate(BaseModel):
    year:             int
    period:           str
    name:             str
    planned_revenue:  Optional[float] = 0.0
    planned_expenses: Optional[float] = 0.0
    notes:            Optional[str]   = None
    project:          Optional[str]   = "pokos"

class BudgetUpdate(BaseModel):
    name:             Optional[str]   = None
    planned_revenue:  Optional[float] = None
    planned_expenses: Optional[float] = None
    notes:            Optional[str]   = None


# ── RESPONSE MODELS (предотвращают циклы сериализации) ─────────────────────────
class EquipmentForMaintResponse(BaseModel):
    id:   int
    name: str
    model_config = ConfigDict(from_attributes=True)

class MaintenanceForListResponse(BaseModel):
    id:               int
    date:             date
    work_description: str
    cost:             Optional[float]
    equipment_id:     int
    equipment:        EquipmentForMaintResponse
    model_config = ConfigDict(from_attributes=True)

class ConsumableForMaintResponse(BaseModel):
    id:             int
    name:           str
    unit:           Optional[str]
    stock_quantity: Optional[float] = 0.0
    model_config = ConfigDict(from_attributes=True)

class MaintConsumableForDetailResponse(BaseModel):
    quantity:        float
    price_at_moment: float
    consumable:      ConsumableForMaintResponse
    model_config = ConfigDict(from_attributes=True)

class MaintenanceDetailResponse(BaseModel):
    id:               int
    equipment_id:     int
    date:             date
    work_description: str
    notes:            Optional[str]
    cost:             Optional[float]
    consumables_used: List[MaintConsumableForDetailResponse]
    model_config = ConfigDict(from_attributes=True)

class EquipmentResponse(BaseModel):
    id:                    int
    name:                  str
    model:                 Optional[str]
    serial:                Optional[str]
    purchase_date:         Optional[date]
    purchase_cost:         Optional[float]
    status:                Optional[str]
    notes:                 Optional[str]
    engine_hours:          Optional[float]
    fuel_norm:             Optional[float]
    last_maintenance_date: Optional[date]
    next_maintenance_date: Optional[date]
    model_config = ConfigDict(from_attributes=True)

class BudgetResponse(BaseModel):
    id:               int
    year:             int
    period:           str
    name:             str
    planned_revenue:  Optional[float] = 0.0
    planned_expenses: Optional[float] = 0.0
    notes:            Optional[str]   = None
    model_config = ConfigDict(from_attributes=True)
