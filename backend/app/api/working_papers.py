from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.engines.working_papers import (
    ensure_working_paper_foundation,
    get_template,
    list_templates,
)
from app.schemas.working_papers import WorkingPaperTemplateListOut, WorkingPaperTemplateOut

router = APIRouter(prefix="/working-papers")


@router.get("", response_model=WorkingPaperTemplateListOut)
def list_working_paper_templates() -> WorkingPaperTemplateListOut:
    templates = [WorkingPaperTemplateOut(**t.to_dict()) for t in list_templates()]
    return WorkingPaperTemplateListOut(templates=templates, count=len(templates))


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
