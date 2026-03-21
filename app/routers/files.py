# GrassCRM — app/routers/files.py v8.0.1

import importlib.util
import secrets
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DBSession, joinedload

from app.database import get_db
from app.models import CRMFile
from app.security import get_current_user, is_admin
from app.config import UPLOAD_DIR, MAX_FILE_SIZE

router = APIRouter()

ALLOWED_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.jpg', '.jpeg', '.png', '.gif', '.webp',
    '.txt', '.csv', '.zip', '.rar',
    '.mp4', '.mov', '.avi',
}
HAS_MULTIPART = (
    importlib.util.find_spec("multipart") is not None or
    importlib.util.find_spec("python_multipart") is not None
)


def _fmt_size(b: int) -> str:
    if b is None: return "—"
    if b < 1024:    return f"{b} Б"
    if b < 1024**2: return f"{b/1024:.1f} КБ"
    return f"{b/1024**2:.1f} МБ"


@router.get("/api/files")
def get_files(
    contact_id: Optional[int] = None,
    deal_id:    Optional[int] = None,
    db: DBSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(CRMFile).options(joinedload(CRMFile.contact), joinedload(CRMFile.deal)).order_by(CRMFile.created_at.desc())
    if contact_id: q = q.filter(CRMFile.contact_id == contact_id)
    if deal_id:    q = q.filter(CRMFile.deal_id == deal_id)
    return [
        {
            "id": f.id, "filename": f.filename, "size": f.size or 0,
            "size_fmt": _fmt_size(f.size), "mime_type": f.mime_type,
            "contact_id": f.contact_id, "deal_id": f.deal_id,
            "uploaded_by_name": f.uploaded_by_name or "—",
            "file_kind": f.file_kind or "general",
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "contact_name": f.contact.name if f.contact else None,
            "deal_title": f.deal.title if f.deal else None,
        }
        for f in q.all()
    ]


if HAS_MULTIPART:
    @router.post("/api/files", status_code=201)
    async def upload_file(
        file:       UploadFile       = FastAPIFile(...),
        contact_id: Optional[int]   = Form(None),
        deal_id:    Optional[int]   = Form(None),
        file_kind:  Optional[str]   = Form(None),
        db:         DBSession       = Depends(get_db),
        user:       dict            = Depends(get_current_user),
    ):
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, f"Тип файла не разрешён: {ext}")
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(400, "Файл слишком большой (макс. 20 МБ)")

        stored_name = f"{secrets.token_hex(12)}{ext}"
        (UPLOAD_DIR / stored_name).write_bytes(content)

        kind = (file_kind or "").strip().lower() or "general"
        if kind not in ("before", "after", "general"):
            kind = "general"

        rec = CRMFile(
            filename=file.filename, stored_name=stored_name,
            size=len(content), mime_type=file.content_type,
            contact_id=contact_id, deal_id=deal_id,
            uploaded_by=user.get("sub"), uploaded_by_name=user.get("name"),
            file_kind=kind,
        )
        db.add(rec); db.commit(); db.refresh(rec)
        return {"id": rec.id, "filename": rec.filename, "size": rec.size, "size_fmt": _fmt_size(rec.size), "mime_type": rec.mime_type}
else:
    @router.post("/api/files", status_code=503)
    async def upload_file_unavailable(_=Depends(get_current_user)):
        raise HTTPException(503, "Загрузка файлов временно недоступна: установите python-multipart")


@router.get("/api/files/{file_id}/download")
def download_file(file_id: int, db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    rec = db.query(CRMFile).filter(CRMFile.id == file_id).first()
    if not rec: raise HTTPException(404, "Файл не найден")
    path = UPLOAD_DIR / rec.stored_name
    if not path.exists(): raise HTTPException(404, "Файл удалён с диска")
    return FileResponse(str(path), filename=rec.filename, media_type=rec.mime_type or "application/octet-stream")


@router.delete("/api/files/{file_id}", status_code=204)
def delete_file(file_id: int, db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    rec = db.query(CRMFile).filter(CRMFile.id == file_id).first()
    if not rec: raise HTTPException(404, "Файл не найден")
    if rec.uploaded_by != user.get("sub") and not is_admin(user):
        raise HTTPException(403, "Нет доступа")
    path = UPLOAD_DIR / rec.stored_name
    if path.exists(): path.unlink()
    db.delete(rec); db.commit()
    return None
