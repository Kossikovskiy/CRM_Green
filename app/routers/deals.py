# GrassCRM — app/routers/deals.py v8.0.1

from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import extract
from sqlalchemy.orm import Session as DBSession, joinedload

from app.database import get_db
from app.models import (
    Deal, DealService, DealElectricService, DealMaterial,
    Contact, Service, ElectricService, Stage,
    Interaction, DealComment,
)
from app.schemas import (
    DealCreate, DealUpdate,
    DealServiceItem, DealElectricServiceItem, DealMaterialItem,
    InteractionCreate, DealCommentCreate,
)
from app.security import get_current_user, require_admin, guard_project, is_admin, is_lost_stage
from app.cache import _cache

router = APIRouter()


# ── СПИСОК / АРХИВ ────────────────────────────────────────────────────────────
@router.get("/api/deals")
def get_deals(
    year: Optional[int] = None, project: str = "pokos",
    q: Optional[str] = None,
    db: DBSession = Depends(get_db), user: dict = Depends(get_current_user),
):
    guard_project(project, user)
    query = (db.query(Deal)
             .options(joinedload(Deal.contact), joinedload(Deal.stage))
             .order_by(Deal.created_at.desc()))
    if year:
        query = query.filter(extract("year", Deal.deal_date) == year)
    if not is_admin(user):
        query = query.filter(Deal.manager == user["name"])
    query = query.filter(Deal.is_archived == False, Deal.project == project)
    if q and q.strip():
        search = f"%{q.strip()}%"
        query = query.join(Deal.contact).filter(
            Deal.title.ilike(search) | Contact.name.ilike(search) | Contact.phone.ilike(search)
        )
    return {
        "deals": [
            {
                "id": d.id, "title": d.title or "", "total": d.total or 0.0,
                "client": d.contact.name if d.contact else "",
                "contact_id": d.contact_id,
                "stage": d.stage.name if d.stage else "", "stage_id": d.stage_id,
                "created_at": (d.created_at or datetime.utcnow()).isoformat(),
            }
            for d in query.all()
        ]
    }


@router.get("/api/deals/archived")
def get_archived_deals(project: str = "pokos", db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    guard_project(project, user)
    q = (db.query(Deal)
         .options(joinedload(Deal.contact), joinedload(Deal.stage))
         .filter(Deal.is_archived == True, Deal.project == project)
         .order_by(Deal.archived_at.desc()))
    if not is_admin(user):
        q = q.filter(Deal.manager == user["name"])
    result = []
    for d in q.all():
        days_left = None
        if d.archived_at:
            days_left = max(0, 30 - (datetime.utcnow() - d.archived_at).days)
        result.append({
            "id": d.id, "title": d.title or "", "total": d.total or 0.0,
            "client": d.contact.name if d.contact else "",
            "contact_id": d.contact_id,
            "stage": d.stage.name if d.stage else "", "stage_id": d.stage_id,
            "created_at": (d.created_at or datetime.utcnow()).isoformat(),
            "archived_at": d.archived_at.isoformat() if d.archived_at else None,
            "days_left": days_left,
        })
    return {"deals": result}


@router.post("/api/deals/{deal_id}/archive")
def archive_deal(deal_id: int, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if not deal: raise HTTPException(404, "Сделка не найдена")
    deal.is_archived = True
    deal.archived_at = datetime.utcnow()
    db.commit(); _cache.invalidate("deals")
    return {"status": "ok"}


@router.post("/api/deals/{deal_id}/unarchive")
def unarchive_deal(deal_id: int, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if not deal: raise HTTPException(404, "Сделка не найдена")
    deal.is_archived = False
    deal.archived_at = None
    db.commit(); _cache.invalidate("deals")
    return {"status": "ok"}


# ── ВСПОМОГАТЕЛЬНАЯ: пересчёт суммы сделки ────────────────────────────────────
def _calc_deal_totals(
    svc_subtotal: float, mat_sell_total: float,
    tax_on_materials: bool, discount_val: float, discount_type: str,
    tax_rate_percent: float, tax_included: bool, mat_cost_total: float,
):
    taxable   = svc_subtotal + (mat_sell_total if tax_on_materials else 0)
    non_taxable = mat_sell_total if not tax_on_materials else 0
    total_sub = taxable + non_taxable

    if discount_type == "fixed":
        disc_amt = min(discount_val, total_sub)
    else:
        disc_amt = total_sub * (discount_val / 100.0)

    ratio = taxable / (total_sub + 0.0001)
    taxable_after   = taxable    - disc_amt * ratio
    nontaxable_after = non_taxable - disc_amt * (1 - ratio)

    tax_amt = taxable_after * (tax_rate_percent / 100.0)
    final   = taxable_after + nontaxable_after + (0 if tax_included else tax_amt)

    return round(final, 2), round(final - mat_cost_total, 2)


# ── CRUD ──────────────────────────────────────────────────────────────────────
@router.post("/api/deals", status_code=201)
def create_deal(deal_data: DealCreate, db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    guard_project(deal_data.project or "pokos", user)

    contact_id = deal_data.contact_id
    if deal_data.new_contact_name:
        new_contact = Contact(name=deal_data.new_contact_name)
        db.add(new_contact); db.flush(); db.refresh(new_contact)
        contact_id = new_contact.id
    if not contact_id:
        raise HTTPException(400, "Не указан клиент")

    svc_subtotal, svc_items = 0.0, []
    for item in deal_data.services:
        svc = db.query(Service).filter(Service.id == item.service_id).first()
        if not svc: continue
        price = item.custom_price if item.custom_price is not None else (svc.price or 0)
        svc_subtotal += price * item.quantity
        svc_items.append(DealService(service_id=svc.id, quantity=item.quantity, price_at_moment=price))

    esvc_items = []
    for item in (deal_data.electric_services or []):
        esvc = db.query(ElectricService).filter(ElectricService.id == item.electric_service_id).first()
        if not esvc: continue
        price = item.custom_price if item.custom_price is not None else (esvc.price or 0)
        svc_subtotal += price * item.quantity
        esvc_items.append(DealElectricService(electric_service_id=esvc.id, quantity=item.quantity, price_at_moment=price))

    mat_items, mat_sell_total, mat_cost_total = [], 0.0, 0.0
    for mat in (deal_data.materials or []):
        mat_sell_total += mat.sell_price * mat.quantity
        mat_cost_total += mat.cost_price * mat.quantity
        mat_items.append(DealMaterial(name=mat.name, quantity=mat.quantity, cost_price=mat.cost_price, sell_price=mat.sell_price))

    final_total, final_revenue = _calc_deal_totals(
        svc_subtotal, mat_sell_total,
        deal_data.tax_on_materials or False,
        deal_data.discount or 0, deal_data.discount_type or "percent",
        deal_data.tax_rate or 0, deal_data.tax_included if deal_data.tax_included is not None else True,
        mat_cost_total,
    )

    new_deal = Deal(
        title=deal_data.title, stage_id=deal_data.stage_id, contact_id=contact_id,
        deal_date=datetime.utcnow(), manager=deal_data.manager,
        services=svc_items, electric_services=esvc_items, materials=mat_items,
        total=final_total, revenue=final_revenue,
        discount=deal_data.discount or 0, discount_type=deal_data.discount_type or "percent",
        tax_rate=deal_data.tax_rate or 0,
        tax_included=deal_data.tax_included if deal_data.tax_included is not None else True,
        tax_on_materials=deal_data.tax_on_materials or False,
        address=deal_data.address or None,
        project=deal_data.project or "pokos",
        duration_hours=deal_data.duration_hours,
    )

    if deal_data.work_date:
        try:
            dt_str = deal_data.work_date
            if deal_data.work_time:
                dt_str += f"T{deal_data.work_time}"
            new_deal.deal_date = datetime.fromisoformat(dt_str)
        except Exception:
            pass

    if deal_data.repeat_interval_days and deal_data.next_repeat_date:
        try:
            new_deal.repeat_interval_days = deal_data.repeat_interval_days
            new_deal.next_repeat_date = date.fromisoformat(str(deal_data.next_repeat_date)[:10])
        except Exception:
            pass

    db.add(new_deal); db.commit(); db.refresh(new_deal)
    _cache.invalidate("deals", "years")
    return {"status": "ok", "id": new_deal.id}


@router.get("/api/deals/{deal_id}")
def get_deal_details(deal_id: int, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    deal = db.query(Deal).options(
        joinedload(Deal.contact),
        joinedload(Deal.services).joinedload(DealService.service),
        joinedload(Deal.electric_services).joinedload(DealElectricService.service),
        joinedload(Deal.materials),
    ).filter(Deal.id == deal_id).first()
    if not deal:
        raise HTTPException(404, "Сделка не найдена")

    def _svc_info(ds, label="Удаленная услуга"):
        info = {"quantity": ds.quantity, "price_at_moment": ds.price_at_moment}
        if ds.service:
            info["service"] = {"id": ds.service.id, "name": ds.service.name, "price": ds.service.price, "unit": ds.service.unit}
        else:
            info["service"] = {"id": -1, "name": f"[{label}]", "price": ds.price_at_moment, "unit": "?"}
        return info

    return {
        "id": deal.id, "title": deal.title, "total": deal.total,
        "stage_id": deal.stage_id, "manager": deal.manager,
        "project": deal.project or "pokos",
        "contact": {"id": deal.contact.id, "name": deal.contact.name} if deal.contact else None,
        "services":          [_svc_info(ds) for ds in deal.services],
        "electric_services": [_svc_info(ds) for ds in (deal.electric_services or [])],
        "materials": [{"id": m.id, "name": m.name, "quantity": m.quantity, "cost_price": m.cost_price, "sell_price": m.sell_price} for m in (deal.materials or [])],
        "discount": deal.discount, "discount_type": deal.discount_type or "percent",
        "tax_rate": deal.tax_rate, "tax_included": deal.tax_included,
        "tax_on_materials": deal.tax_on_materials if deal.tax_on_materials is not None else False,
        "deal_date": deal.deal_date.isoformat() if deal.deal_date else None,
        "address": deal.address or "",
        "repeat_interval_days": deal.repeat_interval_days,
        "next_repeat_date": deal.next_repeat_date.isoformat() if deal.next_repeat_date else None,
        "duration_hours": deal.duration_hours,
    }


@router.patch("/api/deals/{deal_id}")
def update_deal(deal_id: int, deal_data: DealUpdate, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if not deal: raise HTTPException(404, "Сделка не найдена")

    upd = deal_data.model_dump(exclude_unset=True)

    if "new_contact_name" in upd:
        nc = Contact(name=upd["new_contact_name"])
        db.add(nc); db.flush(); db.refresh(nc)
        deal.contact_id = nc.id
    elif "contact_id" in upd:
        deal.contact_id = upd["contact_id"]

    needs_recalc = any(k in upd for k in ("services", "electric_services", "materials", "discount", "discount_type", "tax_rate", "tax_included", "tax_on_materials"))

    if "services" in upd:
        db.query(DealService).filter(DealService.deal_id == deal_id).delete(synchronize_session=False)
        for item_data in upd["services"]:
            item = DealServiceItem(**item_data)
            svc = db.query(Service).filter(Service.id == item.service_id).first()
            if svc:
                price = item.custom_price if item.custom_price is not None else (svc.price or 0)
                db.add(DealService(deal_id=deal_id, service_id=svc.id, quantity=item.quantity, price_at_moment=price))
        db.flush()

    if "electric_services" in upd:
        db.query(DealElectricService).filter(DealElectricService.deal_id == deal_id).delete(synchronize_session=False)
        for item_data in upd["electric_services"]:
            item = DealElectricServiceItem(**item_data)
            esvc = db.query(ElectricService).filter(ElectricService.id == item.electric_service_id).first()
            if esvc:
                price = item.custom_price if item.custom_price is not None else (esvc.price or 0)
                db.add(DealElectricService(deal_id=deal_id, electric_service_id=esvc.id, quantity=item.quantity, price_at_moment=price))
        db.flush()

    if "materials" in upd:
        db.query(DealMaterial).filter(DealMaterial.deal_id == deal_id).delete(synchronize_session=False)
        for mat_data in upd["materials"]:
            mat = DealMaterialItem(**mat_data)
            db.add(DealMaterial(deal_id=deal_id, name=mat.name, quantity=mat.quantity, cost_price=mat.cost_price, sell_price=mat.sell_price))
        db.flush()

    for field in ("discount", "discount_type", "tax_rate", "tax_included", "tax_on_materials"):
        if field in upd: setattr(deal, field, upd[field])

    if needs_recalc:
        svc_sub  = sum(ds.price_at_moment * ds.quantity for ds in deal.services)
        svc_sub += sum(ds.price_at_moment * ds.quantity for ds in deal.electric_services)
        mat_sell = sum(m.sell_price * m.quantity for m in deal.materials)
        mat_cost = sum((m.cost_price or 0) * (m.quantity or 0) for m in deal.materials)
        deal.total, deal.revenue = _calc_deal_totals(
            svc_sub, mat_sell,
            deal.tax_on_materials or False,
            deal.discount or 0, deal.discount_type or "percent",
            deal.tax_rate or 0, deal.tax_included if deal.tax_included is not None else True,
            mat_cost,
        )

    for field in ("title", "stage_id", "manager", "address", "duration_hours"):
        if field in upd: setattr(deal, field, upd[field])

    if "work_date" in upd or "work_time" in upd:
        work_date = upd.get("work_date") or (deal.deal_date.date().isoformat() if deal.deal_date else None)
        work_time = upd.get("work_time") or (deal.deal_date.strftime("%H:%M") if deal.deal_date else None)
        if work_date:
            try:
                deal.deal_date = datetime.fromisoformat(work_date + (f"T{work_time}" if work_time else ""))
            except Exception:
                pass

    if "repeat_interval_days" in upd:
        deal.repeat_interval_days = upd["repeat_interval_days"] or None
    if "next_repeat_date" in upd:
        raw = upd["next_repeat_date"]
        deal.next_repeat_date = date.fromisoformat(str(raw)[:10]) if raw else None

    if "stage_id" in upd and upd["stage_id"]:
        stage = db.query(Stage).filter(Stage.id == upd["stage_id"]).first()
        if stage and is_lost_stage(stage):
            deal.repeat_interval_days = None
            deal.next_repeat_date = None

    db.commit(); db.refresh(deal)
    _cache.invalidate("deals", "years")
    return {"status": "ok", "id": deal.id}


@router.delete("/api/deals/{deal_id}", status_code=204)
def delete_deal(deal_id: int, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if deal:
        db.query(DealService).filter(DealService.deal_id == deal_id).delete(synchronize_session=False)
        db.delete(deal); db.commit()
        _cache.invalidate("deals", "years")
    return None


@router.post("/api/deals/{deal_id}/duplicate", status_code=201)
def duplicate_deal(deal_id: int, db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    deal = db.query(Deal).options(
        joinedload(Deal.services), joinedload(Deal.electric_services), joinedload(Deal.materials),
    ).filter(Deal.id == deal_id).first()
    if not deal: raise HTTPException(404, "Сделка не найдена")

    first_stage = db.query(Stage).filter(Stage.project == deal.project).order_by(Stage.order).first()
    new_deal = Deal(
        contact_id=deal.contact_id,
        stage_id=first_stage.id if first_stage else deal.stage_id,
        title=deal.title + " (копия)", notes=deal.notes or "",
        manager=deal.manager, address=deal.address,
        tax_rate=deal.tax_rate, tax_included=deal.tax_included,
        tax_on_materials=deal.tax_on_materials,
        discount=deal.discount, discount_type=deal.discount_type,
        total=deal.total, revenue=deal.revenue,
        project=deal.project, duration_hours=deal.duration_hours,
        deal_date=datetime.utcnow(),
    )
    db.add(new_deal); db.flush()
    for ds in deal.services:
        db.add(DealService(deal_id=new_deal.id, service_id=ds.service_id, quantity=ds.quantity, price_at_moment=ds.price_at_moment))
    for ds in deal.electric_services:
        db.add(DealElectricService(deal_id=new_deal.id, electric_service_id=ds.electric_service_id, quantity=ds.quantity, price_at_moment=ds.price_at_moment))
    for m in deal.materials:
        db.add(DealMaterial(deal_id=new_deal.id, name=m.name, quantity=m.quantity, cost_price=m.cost_price, sell_price=m.sell_price))
    db.commit()
    _cache.invalidate("deals")
    return {"status": "ok", "id": new_deal.id}


# ── ВЗАИМОДЕЙСТВИЯ ────────────────────────────────────────────────────────────
@router.get("/api/contacts/{contact_id}/interactions")
def get_interactions(contact_id: int, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    items = db.query(Interaction).filter(Interaction.contact_id == contact_id).order_by(Interaction.created_at.desc()).all()
    return [{"id": i.id, "type": i.type, "text": i.text, "created_at": i.created_at.isoformat() if i.created_at else None, "user_name": i.user_name or "—"} for i in items]


@router.post("/api/contacts/{contact_id}/interactions", status_code=201)
def create_interaction(contact_id: int, data: InteractionCreate, db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    if not db.query(Contact).filter(Contact.id == contact_id).first():
        raise HTTPException(404, "Контакт не найден")
    item = Interaction(contact_id=contact_id, type=data.type, text=data.text, user_id=user.get("sub"), user_name=user.get("name"))
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "type": item.type, "text": item.text, "created_at": item.created_at.isoformat(), "user_name": item.user_name or "—"}


@router.delete("/api/interactions/{interaction_id}", status_code=204)
def delete_interaction(interaction_id: int, db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    item = db.query(Interaction).filter(Interaction.id == interaction_id).first()
    if not item: raise HTTPException(404, "Запись не найдена")
    if item.user_id != user.get("sub") and not is_admin(user):
        raise HTTPException(403, "Нет доступа")
    db.delete(item); db.commit()
    return None


# ── КОММЕНТАРИИ ───────────────────────────────────────────────────────────────
@router.get("/api/deals/{deal_id}/comments")
def get_deal_comments(deal_id: int, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    items = db.query(DealComment).filter(DealComment.deal_id == deal_id).order_by(DealComment.created_at.asc()).all()
    return [{"id": i.id, "text": i.text, "created_at": i.created_at.isoformat() if i.created_at else None, "user_name": i.user_name or "—", "user_id": i.user_id} for i in items]


@router.post("/api/deals/{deal_id}/comments", status_code=201)
def create_deal_comment(deal_id: int, data: DealCommentCreate, db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    if not db.query(Deal).filter(Deal.id == deal_id).first():
        raise HTTPException(404, "Сделка не найдена")
    item = DealComment(deal_id=deal_id, text=data.text, user_id=user.get("sub"), user_name=user.get("name"))
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "text": item.text, "created_at": item.created_at.isoformat(), "user_name": item.user_name or "—", "user_id": item.user_id}


@router.delete("/api/deal-comments/{comment_id}", status_code=204)
def delete_deal_comment(comment_id: int, db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    item = db.query(DealComment).filter(DealComment.id == comment_id).first()
    if not item: raise HTTPException(404, "Комментарий не найден")
    if item.user_id != user.get("sub") and not is_admin(user):
        raise HTTPException(403, "Нет доступа")
    db.delete(item); db.commit()
    return None
