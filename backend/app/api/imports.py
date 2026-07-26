from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.engines.importing import import_bank_file
from app.schemas.transactions import ImportResult

router = APIRouter(prefix="/imports")


@router.post("/bank-statement", response_model=ImportResult)
async def import_bank_statement(
    bank_account_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> ImportResult:
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    try:
        result = import_bank_file(
            db,
            file_bytes=content,
            filename=file.filename or "upload.csv",
            bank_account_id=bank_account_id,
            actor="controller",
        )
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
