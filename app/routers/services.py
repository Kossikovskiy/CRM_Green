# GrassCRM — app/routers/services.py v8.0.1

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.database import get_db, get_public_db
from app.models import Service, DealService, ElectricService, DealElectricService
from app.schemas import ServiceCreate, ServiceUpdate, ElectricServiceCreate, ElectricServiceUpdate
from app.security import get_current_user, require_admin, guard_project
from app.cache import _cache

router = APIRouter()


# ── УСЛУГИ (покос) ────────────────────────────────────────────────────────────
@router.get("/api/services")
def get_services(db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    return db.query(Service).order_by(Service.id).all()


@router.get("/api/public/services")
def get_public_services(db: DBSession = Depends(get_public_db)):
    """Публичный эндпоинт для страницы прайса — без авторизации.
    RLS: CREATE POLICY public_read_services ON services FOR SELECT TO anon USING (true);
    """
    try:
        rows = db.query(Service).order_by(Service.id).all()
        return [
            {"id": s.id, "name": s.name, "price": s.price,
             "unit": s.unit, "min_volume": s.min_volume, "notes": s.notes}
            for s in rows
        ]
    except Exception:
        raise HTTPException(500, "Не удалось получить список услуг")


@router.post("/api/services", status_code=201)
def create_service(data: ServiceCreate, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    new_item = Service(**data.model_dump())
    db.add(new_item); db.commit(); db.refresh(new_item)
    _cache.invalidate("services")
    return new_item


@router.patch("/api/services/{service_id}")
def update_service(service_id: int, data: ServiceUpdate, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    item = db.query(Service).filter(Service.id == service_id).first()
    if not item:
        raise HTTPException(404, "Услуга не найдена")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit(); db.refresh(item)
    _cache.invalidate("services", "deals")
    return item


@router.delete("/api/services/{service_id}", status_code=204)
def delete_service(service_id: int, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    if db.query(DealService).filter(DealService.service_id == service_id).count() > 0:
        raise HTTPException(400, "Нельзя удалить услугу, которая используется в сделках.")
    item = db.query(Service).filter(Service.id == service_id).first()
    if item:
        db.delete(item); db.commit(); _cache.invalidate("services")
    return None


# ── УСЛУГИ (электрика) ────────────────────────────────────────────────────────
@router.get("/api/electric-services")
def get_electric_services(db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    guard_project("electric", user)
    return db.query(ElectricService).order_by(ElectricService.id).all()


@router.post("/api/electric-services", status_code=201)
def create_electric_service(data: ElectricServiceCreate, db: DBSession = Depends(get_db), user: dict = Depends(require_admin)):
    guard_project("electric", user)
    item = ElectricService(**data.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    _cache.invalidate("electric_services")
    return item


@router.patch("/api/electric-services/{service_id}")
def update_electric_service(service_id: int, data: ElectricServiceUpdate, db: DBSession = Depends(get_db), user: dict = Depends(require_admin)):
    guard_project("electric", user)
    item = db.query(ElectricService).filter(ElectricService.id == service_id).first()
    if not item:
        raise HTTPException(404, "Услуга не найдена")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(item, k, v)
    db.commit(); db.refresh(item)
    _cache.invalidate("electric_services")
    return item


@router.delete("/api/electric-services/{service_id}", status_code=204)
def delete_electric_service(service_id: int, db: DBSession = Depends(get_db), user: dict = Depends(require_admin)):
    guard_project("electric", user)
    if db.query(DealElectricService).filter(DealElectricService.electric_service_id == service_id).count() > 0:
        raise HTTPException(400, "Нельзя удалить услугу, которая используется в сделках.")
    item = db.query(ElectricService).filter(ElectricService.id == service_id).first()
    if item:
        db.delete(item); db.commit(); _cache.invalidate("electric_services")
    return None
