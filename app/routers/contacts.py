# GrassCRM — app/routers/contacts.py v8.0.1

import json as _json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession, joinedload

from app.database import get_db
from app.models import Contact, Deal, Stage
from app.schemas import ContactCreate, ContactUpdate
from app.security import get_current_user, is_won_stage
from app.cache import _cache

router = APIRouter()


@router.get("/api/contacts")
def get_contacts(search: str = None, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    q = db.query(Contact).order_by(Contact.name)
    if search and search.strip():
        s = f"%{search.strip()}%"
        q = q.filter(
            Contact.name.ilike(s) |
            Contact.phone.ilike(s) |
            Contact.source.ilike(s)
        )
    result = []
    for c in q.all():
        d = {col.name: getattr(c, col.name) for col in c.__table__.columns}
        try:
            d["addresses"] = _json.loads(c.addresses) if c.addresses else []
        except Exception:
            d["addresses"] = []
        result.append(d)
    return result


@router.post("/api/contacts", status_code=201)
def create_contact(contact_data: ContactCreate, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    if contact_data.phone and contact_data.phone.strip():
        if db.query(Contact).filter(Contact.phone == contact_data.phone).first():
            raise HTTPException(409, "Контакт с таким телефоном уже существует")
    data      = contact_data.model_dump()
    addresses = data.pop("addresses", None) or []
    new_contact = Contact(**data, addresses=_json.dumps(addresses, ensure_ascii=False))
    db.add(new_contact); db.commit(); db.refresh(new_contact)
    _cache.invalidate("contacts")
    result             = {col.name: getattr(new_contact, col.name) for col in new_contact.__table__.columns}
    result["addresses"] = addresses
    return result


@router.patch("/api/contacts/{contact_id}")
def update_contact(contact_id: int, contact_data: ContactUpdate, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(404, "Контакт не найден")
    update_data = contact_data.model_dump(exclude_unset=True)
    if "phone" in update_data and update_data["phone"] and update_data["phone"].strip():
        if db.query(Contact).filter(Contact.phone == update_data["phone"], Contact.id != contact_id).first():
            raise HTTPException(409, "Контакт с таким телефоном уже существует")
    if "addresses" in update_data:
        contact.addresses = _json.dumps(update_data.pop("addresses") or [], ensure_ascii=False)
    for key, value in update_data.items():
        setattr(contact, key, value)
    db.commit(); db.refresh(contact)
    _cache.invalidate("contacts", "deals")
    result = {col.name: getattr(contact, col.name) for col in contact.__table__.columns}
    try:
        result["addresses"] = _json.loads(contact.addresses) if contact.addresses else []
    except Exception:
        result["addresses"] = []
    return result


@router.get("/api/contacts/{contact_id}/deals")
def get_contact_all_deals(contact_id: int, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    """Все сделки контакта за всё время, от новых к старым."""
    deals     = (db.query(Deal).options(joinedload(Deal.stage))
                 .filter(Deal.contact_id == contact_id)
                 .order_by(Deal.created_at.desc()).all())
    won_names = {s.name for s in db.query(Stage).all() if is_won_stage(s)}
    result    = []
    for d in deals:
        result.append({
            "id":                   d.id,
            "title":                d.title or "",
            "total":                d.total or 0.0,
            "stage":                d.stage.name if d.stage else "",
            "stage_color":          d.stage.color if d.stage else "#6b7280",
            "stage_is_won":         (d.stage.name in won_names) if d.stage else False,
            "stage_is_final":       d.stage.is_final if d.stage else False,
            "deal_date":            d.deal_date.isoformat() if d.deal_date else None,
            "created_at":           (d.created_at or datetime.utcnow()).isoformat(),
            "repeat_interval_days": d.repeat_interval_days,
            "next_repeat_date":     d.next_repeat_date.isoformat() if d.next_repeat_date else None,
        })
    total_revenue = sum(r["total"] for r in result if r["stage_is_won"])
    return {
        "deals":         result,
        "total_count":   len(result),
        "won_count":     sum(1 for r in result if r["stage_is_won"]),
        "total_revenue": round(total_revenue, 2),
    }


@router.delete("/api/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: int, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        return None
    if db.query(Deal).filter(Deal.contact_id == contact_id).count() > 0:
        raise HTTPException(400, "Нельзя удалить контакт, к которому привязаны сделки.")
    db.delete(contact); db.commit()
    _cache.invalidate("contacts")
    return None
