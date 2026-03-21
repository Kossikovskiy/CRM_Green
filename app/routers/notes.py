# GrassCRM — app/routers/notes.py v8.0.1

import uuid as _uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.database import get_db
from app.models import Note, BotFaq
from app.schemas import NoteCreate, NoteUpdate
from app.security import get_current_user, is_admin

router = APIRouter()


# ── ЗАМЕТКИ ───────────────────────────────────────────────────────────────────
def _note_to_dict(n: Note) -> dict:
    return {
        "id":        n.id,
        "title":     n.title or "",
        "body":      n.body or "",
        "color":     n.color or "",
        "pinned":    n.pinned or False,
        "label":     n.label or "",
        "checklist": n.checklist or [],
        "created":   int(n.created_at.timestamp() * 1000) if n.created_at else 0,
        "updated":   int(n.updated_at.timestamp() * 1000) if n.updated_at else 0,
    }


@router.get("/api/notes")
def get_notes(db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    notes = db.query(Note).filter(Note.user_id == user["sub"]).order_by(Note.updated_at.desc()).all()
    return [_note_to_dict(n) for n in notes]


@router.post("/api/notes", status_code=201)
def create_note(data: NoteCreate, db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    note = Note(
        id=data.id or str(_uuid.uuid4()),
        user_id=user["sub"],
        title=data.title, body=data.body, color=data.color,
        pinned=data.pinned, label=data.label, checklist=data.checklist,
        created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    db.add(note); db.commit(); db.refresh(note)
    return _note_to_dict(note)


@router.patch("/api/notes/{note_id}")
def update_note(note_id: str, data: NoteUpdate, db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user["sub"]).first()
    if not note: raise HTTPException(404, "Заметка не найдена")
    if data.title     is not None: note.title     = data.title
    if data.body      is not None: note.body      = data.body
    if data.color     is not None: note.color     = data.color
    if data.pinned    is not None: note.pinned    = data.pinned
    if data.label     is not None: note.label     = data.label
    if data.checklist is not None: note.checklist = data.checklist
    note.updated_at = datetime.utcnow()
    db.commit(); db.refresh(note)
    return _note_to_dict(note)


@router.delete("/api/notes/{note_id}", status_code=204)
def delete_note(note_id: str, db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user["sub"]).first()
    if not note: raise HTTPException(404, "Заметка не найдена")
    db.delete(note); db.commit()


# ── AUDIT LOG ─────────────────────────────────────────────────────────────────
@router.get("/api/admin/audit-log")
def get_audit_log(
    table_name: Optional[str] = None,
    action:     Optional[str] = None,
    changed_by: Optional[str] = None,
    date_from:  Optional[str] = None,
    date_to:    Optional[str] = None,
    limit:  int = 100,
    offset: int = 0,
    db: DBSession = Depends(get_db),
    user: dict    = Depends(get_current_user),
):
    if not is_admin(user):
        raise HTTPException(403, "Admin only")

    filters = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}
    if table_name:
        filters.append("table_name = :table_name"); params["table_name"] = table_name
    if action:
        filters.append("action = :action"); params["action"] = action
    if changed_by:
        filters.append("user_name ILIKE :changed_by"); params["changed_by"] = f"%{changed_by}%"
    if date_from:
        filters.append("created_at >= :date_from"); params["date_from"] = date_from
    if date_to:
        filters.append("created_at < :date_to"); params["date_to"] = date_to

    where = " AND ".join(filters)
    rows  = db.execute(
        text(f"SELECT id, table_name, record_id, action, user_id, user_name, changes, created_at FROM audit_log WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
        params,
    ).fetchall()
    total = db.execute(
        text(f"SELECT COUNT(*) FROM audit_log WHERE {where}"),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    ).scalar()

    return {
        "total": total,
        "items": [
            {
                "id": r[0], "table_name": r[1], "record_id": r[2],
                "action": r[3], "user_id": r[4], "changed_by": r[5],
                "changes": r[6],
                "changed_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ],
    }


# ── БОТ FAQ ───────────────────────────────────────────────────────────────────
@router.get("/api/bot-faq")
def get_bot_faq(db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    items = db.query(BotFaq).filter(BotFaq.active == True).order_by(BotFaq.priority.desc()).all()
    return [{"id": i.id, "intent": i.intent, "question_example": i.question_example, "answer": i.answer} for i in items]
