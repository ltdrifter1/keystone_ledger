from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.engines.engagement import build_engagement_home
from app.schemas.engagement import EngagementHomeOut

router = APIRouter(prefix="/engagement")


@router.get("/home", response_model=EngagementHomeOut)
def engagement_home(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    entity_id: int | None = None,
    db: Session = Depends(get_db),
) -> EngagementHomeOut:
    data = build_engagement_home(db, year=year, month=month, entity_id=entity_id)
    return EngagementHomeOut.model_validate(data)
