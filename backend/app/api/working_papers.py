from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.engines.binder import build_binder, get_binder_document, upsert_binder_document
from app.engines.working_papers import (
    ensure_working_paper_foundation,
    get_template,
    list_templates,
)
from app.schemas.working_papers import (
    BinderDocumentOut,
    BinderDocumentUpdate,
    BinderOut,
    WorkingPaperTemplateListOut,
    WorkingPaperTemplateOut,
)

router = APIRouter(prefix="/working-papers")


@router.get("", response_model=WorkingPaperTemplateListOut)
def list_working_paper_templates() -> WorkingPaperTemplateListOut:
    templates = [WorkingPaperTemplateOut(**t.to_dict()) for t in list_templates()]
    return WorkingPaperTemplateListOut(templates=templates, count=len(templates))


@router.get("/binder", response_model=BinderOut)
def get_binder(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    entity_id: int | None = None,
    db: Session = Depends(get_db),
) -> BinderOut:
    data = build_binder(db, year, month, entity_id=entity_id)
    # Persist any side-effects from sync inside close overview (totals refresh)
    db.commit()
    return BinderOut.model_validate(data)


@router.get("/binder/{key}", response_model=BinderDocumentOut)
def get_binder_doc(
    key: str,
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    entity_id: int | None = None,
    db: Session = Depends(get_db),
) -> BinderDocumentOut:
    try:
        data = get_binder_document(db, year, month, key, entity_id=entity_id)
        db.commit()
        return BinderDocumentOut.model_validate(data)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/binder/{key}", response_model=BinderDocumentOut)
def update_binder_doc(
    key: str,
    payload: BinderDocumentUpdate,
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    entity_id: int | None = None,
    db: Session = Depends(get_db),
) -> BinderDocumentOut:
    try:
        data = upsert_binder_document(
            db,
            year=year,
            month=month,
            key=key,
            checked=payload.checked,
            notes=payload.notes,
            preparer=payload.preparer,
            reviewer=payload.reviewer,
            status=payload.status,
            actor="controller",
            entity_id=entity_id,
        )
        db.commit()
        return BinderDocumentOut.model_validate(data)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.get("/{key}", response_model=WorkingPaperTemplateOut)
def get_working_paper_template(key: str) -> WorkingPaperTemplateOut:
    tmpl = get_template(key)
    if not tmpl:
        raise HTTPException(404, f"Working paper template '{key}' not found")
    return WorkingPaperTemplateOut(**tmpl.to_dict())


@router.post("/ensure-foundation")
def ensure_foundation(db: Session = Depends(get_db)) -> dict:
    """Idempotent: add missing CoA accounts and BS layout lines for WP sections."""
    return ensure_working_paper_foundation(db)
