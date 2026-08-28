from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_actor
from app.database import get_db
from app.engines.journals import list_journals, post_journal, serialize_journal
from app.models import Transaction
from app.schemas.journals import JournalCreate, JournalOut

router = APIRouter(prefix="/journals", tags=["journals"])


@router.get("", response_model=list[JournalOut])
def get_journals(
    year: int | None = None,
    month: int | None = Query(None, ge=1, le=12),
    entity_id: int | None = None,
    working_paper_key: str | None = None,
    db: Session = Depends(get_db),
) -> list[JournalOut]:
    rows = list_journals(
        db,
        year=year,
        month=month,
        entity_id=entity_id,
        working_paper_key=working_paper_key,
    )
    return [JournalOut.model_validate(r) for r in rows]


@router.post("", response_model=JournalOut)
def create_journal(
    payload: JournalCreate,
    db: Session = Depends(get_db),
    actor: str = Depends(get_actor),
) -> JournalOut:
    try:
        txn = post_journal(
            db,
            txn_date=payload.txn_date,
            entity_id=payload.entity_id,
            description=payload.description,
            lines=[line.model_dump() for line in payload.lines],
            actor=actor,
            memo=payload.memo,
            working_paper_key=payload.working_paper_key,
            source_transaction_id=payload.source_transaction_id,
            currency=payload.currency or "",
            scenario_id=payload.scenario_id,
        )
        db.commit()
        loaded = db.get(Transaction, txn.id)
        return JournalOut.model_validate(serialize_journal(db, loaded))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
