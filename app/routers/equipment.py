# GrassCRM — app/routers/equipment.py v8.0.1

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import extract, func
from sqlalchemy.orm import Session as DBSession, joinedload

from app.database import get_db
from app.models import Equipment, EquipmentMaintenance, MaintenanceConsumable, Consumable
from app.schemas import (
    EquipmentCreate, EquipmentUpdate, EquipmentResponse,
    ConsumableCreate, ConsumableUpdate,
    MaintenanceCreate, MaintenanceUpdate,
    MaintenanceDetailResponse, MaintenanceForListResponse,
)
from app.security import get_current_user, require_admin
from app.cache import _cache

router = APIRouter()


# ── ВСПОМОГАТЕЛЬНАЯ ───────────────────────────────────────────────────────────
def _update_equipment_last_maintenance(db: DBSession, equipment_id: int):
    item = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not item:
        return
    latest = db.query(func.max(EquipmentMaintenance.date)).filter(
        EquipmentMaintenance.equipment_id == equipment_id
    ).scalar()
    item.last_maintenance_date = latest
    db.commit()
    _cache.invalidate("equipment")


# ── ТЕХНИКА ───────────────────────────────────────────────────────────────────
@router.get("/api/equipment", response_model=List[EquipmentResponse])
def get_equipment(db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    return db.query(Equipment).order_by(Equipment.name).all()


@router.post("/api/equipment", status_code=201, response_model=EquipmentResponse)
def create_equipment(data: EquipmentCreate, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    new_item = Equipment(**data.model_dump())
    db.add(new_item); db.commit(); db.refresh(new_item)
    _cache.invalidate("equipment")
    return new_item


@router.patch("/api/equipment/{eq_id}", response_model=EquipmentResponse)
def update_equipment(eq_id: int, data: EquipmentUpdate, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    item = db.query(Equipment).filter(Equipment.id == eq_id).first()
    if not item:
        raise HTTPException(404, "Техника не найдена")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit(); db.refresh(item)
    _cache.invalidate("equipment")
    return item


@router.delete("/api/equipment/{eq_id}", status_code=204)
def delete_equipment(eq_id: int, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    item = db.query(Equipment).filter(Equipment.id == eq_id).first()
    if item:
        db.delete(item); db.commit(); _cache.invalidate("equipment")
    return None


# ── ТО ────────────────────────────────────────────────────────────────────────
@router.get("/api/maintenance", response_model=List[MaintenanceForListResponse])
def get_all_maintenance(year: Optional[int] = None, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    q = (db.query(EquipmentMaintenance)
         .options(joinedload(EquipmentMaintenance.equipment))
         .order_by(EquipmentMaintenance.date.desc()))
    if year:
        q = q.filter(extract("year", EquipmentMaintenance.date) == year)
    return q.all()


@router.get("/api/maintenance/{m_id}", response_model=MaintenanceDetailResponse)
def get_maintenance_details(m_id: int, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    m_record = (db.query(EquipmentMaintenance)
                .options(
                    joinedload(EquipmentMaintenance.consumables_used).joinedload(MaintenanceConsumable.consumable),
                    joinedload(EquipmentMaintenance.equipment),
                )
                .filter(EquipmentMaintenance.id == m_id).first())
    if not m_record:
        raise HTTPException(404, "Запись о ТО не найдена")
    return m_record


@router.post("/api/maintenance", status_code=201, response_model=MaintenanceDetailResponse)
def create_maintenance_record(data: MaintenanceCreate, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    total_cost = 0
    try:
        for item_data in data.consumables:
            consumable = db.query(Consumable).filter(Consumable.id == item_data.consumable_id).with_for_update().first()
            if not consumable or consumable.stock_quantity < item_data.quantity:
                name = consumable.name if consumable else f"ID:{item_data.consumable_id}"
                raise HTTPException(400, f"Недостаточно '{name}' на складе.")
            consumable.stock_quantity -= item_data.quantity
            total_cost += (consumable.price or 0) * item_data.quantity

        new_item = EquipmentMaintenance(
            equipment_id=data.equipment_id, date=data.date,
            work_description=data.work_description, notes=data.notes, cost=total_cost,
        )
        db.add(new_item); db.flush()

        for item_data in data.consumables:
            consumable = db.query(Consumable).filter(Consumable.id == item_data.consumable_id).first()
            db.add(MaintenanceConsumable(
                maintenance_id=new_item.id, consumable_id=item_data.consumable_id,
                quantity=item_data.quantity, price_at_moment=(consumable.price or 0),
            ))
        db.commit(); db.refresh(new_item)
        _update_equipment_last_maintenance(db, data.equipment_id)
        _cache.invalidate("consumables", "equipment", "maintenance")
        return new_item
    except Exception:
        db.rollback(); raise


@router.patch("/api/maintenance/{m_id}", response_model=MaintenanceDetailResponse)
def update_maintenance_record(m_id: int, data: MaintenanceUpdate, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    try:
        m_record = (db.query(EquipmentMaintenance)
                    .options(joinedload(EquipmentMaintenance.consumables_used))
                    .filter(EquipmentMaintenance.id == m_id).first())
        if not m_record:
            raise HTTPException(404, "Запись о ТО не найдена")

        if data.consumables is not None:
            for old_item in m_record.consumables_used:
                consumable = db.query(Consumable).filter(Consumable.id == old_item.consumable_id).with_for_update().first()
                if consumable:
                    consumable.stock_quantity += old_item.quantity
            db.query(MaintenanceConsumable).filter(MaintenanceConsumable.maintenance_id == m_id).delete(synchronize_session=False)
            db.flush()
            total_cost = 0
            for item_data in data.consumables:
                consumable = db.query(Consumable).filter(Consumable.id == item_data.consumable_id).with_for_update().first()
                if not consumable or consumable.stock_quantity < item_data.quantity:
                    name = consumable.name if consumable else f"ID:{item_data.consumable_id}"
                    raise HTTPException(400, f"Недостаточно '{name}' на складе.")
                consumable.stock_quantity -= item_data.quantity
                total_cost += (consumable.price or 0) * item_data.quantity
                db.add(MaintenanceConsumable(
                    maintenance_id=m_id, consumable_id=item_data.consumable_id,
                    quantity=item_data.quantity, price_at_moment=(consumable.price or 0),
                ))
            m_record.cost = total_cost

        update_data = data.model_dump(exclude_unset=True)
        if "date" in update_data:             m_record.date             = update_data["date"]
        if "work_description" in update_data: m_record.work_description = update_data["work_description"]
        if "notes" in update_data:            m_record.notes            = update_data["notes"]

        db.commit(); db.refresh(m_record)
        _update_equipment_last_maintenance(db, m_record.equipment_id)
        _cache.invalidate("consumables", "equipment", "maintenance")
        return m_record
    except Exception:
        db.rollback(); raise


@router.delete("/api/maintenance/{m_id}", status_code=204)
def delete_maintenance_record(m_id: int, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    try:
        item = (db.query(EquipmentMaintenance)
                .options(joinedload(EquipmentMaintenance.consumables_used))
                .filter(EquipmentMaintenance.id == m_id).first())
        if item:
            equipment_id = item.equipment_id
            for used in item.consumables_used:
                consumable = db.query(Consumable).filter(Consumable.id == used.consumable_id).with_for_update().first()
                if consumable:
                    consumable.stock_quantity += used.quantity
            db.delete(item); db.commit()
            _update_equipment_last_maintenance(db, equipment_id)
            _cache.invalidate("consumables", "equipment", "maintenance")
    except Exception:
        db.rollback(); raise
    return None


# ── РАСХОДНИКИ ────────────────────────────────────────────────────────────────
@router.get("/api/consumables")
def get_consumables(db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    return db.query(Consumable).order_by(Consumable.name).all()


@router.post("/api/consumables", status_code=201)
def create_consumable(data: ConsumableCreate, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    new_item = Consumable(**data.model_dump())
    db.add(new_item); db.commit(); db.refresh(new_item)
    _cache.invalidate("consumables")
    return new_item


@router.patch("/api/consumables/{c_id}")
def update_consumable(c_id: int, data: ConsumableUpdate, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    item = db.query(Consumable).filter(Consumable.id == c_id).first()
    if not item:
        raise HTTPException(404, "Расходник не найден")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit(); db.refresh(item)
    _cache.invalidate("consumables")
    return item


@router.delete("/api/consumables/{c_id}", status_code=204)
def delete_consumable(c_id: int, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    if db.query(MaintenanceConsumable).filter(MaintenanceConsumable.consumable_id == c_id).count() > 0:
        raise HTTPException(400, "Нельзя удалить расходник, который используется в записях о ТО.")
    item = db.query(Consumable).filter(Consumable.id == c_id).first()
    if item:
        db.delete(item); db.commit(); _cache.invalidate("consumables")
