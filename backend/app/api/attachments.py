from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_actor
from app.config import get_settings
from app.database import get_db
from app.engines.audit import write_audit
from app.models import Attachment, WorkingPaperDocument

router = APIRouter(prefix="/attachments", tags=["attachments"])


def _serialize(row: Attachment) -> dict:
    path = Path(row.storage_path)
    size = path.stat().st_size if path.exists() else None
    return {
        "id": row.id,
        "entity_table": row.entity_table,
        "entity_id": row.entity_id,
        "filename": row.filename,
        "content_type": row.content_type,
        "uploaded_by": row.uploaded_by,
        "uploaded_at": row.uploaded_at,
        "size_bytes": size,
    }


@router.get("")
def list_attachments(
    entity_table: str,
    entity_id: int,
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = list(
        db.scalars(
            select(Attachment)
            .where(Attachment.entity_table == entity_table, Attachment.entity_id == entity_id)
            .order_by(Attachment.uploaded_at.desc())
        )
    )
    return [_serialize(r) for r in rows]


@router.post("")
async def upload_attachment(
    entity_table: str = Form(...),
    entity_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: str = Depends(get_actor),
) -> dict:
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    if entity_table == "working_paper_documents":
        doc = db.get(WorkingPaperDocument, entity_id)
        if not doc:
            raise HTTPException(404, "Working paper document not found")
    settings = get_settings()
    dest_dir = Path(settings.attachments_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "evidence.bin").name.replace("/", "_")
    row = Attachment(
        entity_table=entity_table,
        entity_id=entity_id,
        filename=safe_name,
        content_type=file.content_type or "application/octet-stream",
        storage_path="",
        uploaded_by=actor,
    )
    db.add(row)
    db.flush()
    path = dest_dir / f"{row.id}_{safe_name}"
    path.write_bytes(content)
    row.storage_path = str(path)
    write_audit(
        db,
        entity_table="attachments",
        entity_id=row.id,
        action="create",
        actor=actor,
        meta={"filename": safe_name, "parent": f"{entity_table}:{entity_id}"},
    )
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.get("/{attachment_id}/file")
def download_attachment(attachment_id: int, db: Session = Depends(get_db)) -> FileResponse:
    row = db.get(Attachment, attachment_id)
    if not row:
        raise HTTPException(404, "Not found")
    path = Path(row.storage_path)
    if not path.exists():
        raise HTTPException(404, "File missing")
    return FileResponse(path, filename=row.filename, media_type=row.content_type)


@router.delete("/{attachment_id}")
def delete_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(get_actor),
) -> dict:
    row = db.get(Attachment, attachment_id)
    if not row:
        raise HTTPException(404, "Not found")
    path = Path(row.storage_path)
    if path.exists():
        path.unlink()
    write_audit(
        db,
        entity_table="attachments",
        entity_id=row.id,
        action="delete",
        actor=actor,
        meta={"filename": row.filename},
    )
    db.delete(row)
    db.commit()
    return {"deleted": attachment_id}
