from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_actor
from app.database import get_db
from app.engines.entity_close import (
    get_entity_period_lock,
    is_journal_led_entity,
    lock_entity_month,
    serialize_lock,
)
from app.engines.period_locks import PeriodLockedError

router = APIRouter(prefix="/period-locks", tags=["period-locks"])


@router.get("")
def get_lock(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> dict:
    lock = get_entity_period_lock(db, entity_id, year, month)
    data = serialize_lock(lock, entity_id=entity_id, year=year, month=month)
    data["journal_led"] = is_journal_led_entity(db, entity_id)
    return data


@router.post("/lock")
def lock_month(
    entity_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    notes: str | None = None,
    db: Session = Depends(get_db),
    actor: str = Depends(get_actor),
) -> dict:
    try:
        data = lock_entity_month(db, entity_id=entity_id, year=year, month=month, actor=actor, notes=notes)
        data["journal_led"] = is_journal_led_entity(db, entity_id)
        db.commit()
        return data
    except (ValueError, PeriodLockedError) as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
