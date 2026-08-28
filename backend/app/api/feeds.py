from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_actor
from app.database import get_db
from app.engines.bank_feeds import connect_feed, disconnect_feed, list_feeds, sync_feed
from app.schemas.feeds import BankFeedOut, FeedSyncOut

router = APIRouter(prefix="/bank-feeds", tags=["bank-feeds"])


@router.get("", response_model=list[BankFeedOut])
def get_feeds(entity_id: int | None = None, db: Session = Depends(get_db)) -> list[BankFeedOut]:
    rows = list_feeds(db, entity_id=entity_id, include_pending=True)
    db.commit()
    return [BankFeedOut.model_validate(r) for r in rows]


@router.post("/{bank_account_id}/connect", response_model=BankFeedOut)
def connect(
    bank_account_id: int, db: Session = Depends(get_db), actor: str = Depends(get_actor)
) -> BankFeedOut:
    try:
        row = connect_feed(db, bank_account_id, actor=actor)
        db.commit()
        return BankFeedOut.model_validate(row)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.post("/{bank_account_id}/disconnect", response_model=BankFeedOut)
def disconnect(
    bank_account_id: int, db: Session = Depends(get_db), actor: str = Depends(get_actor)
) -> BankFeedOut:
    try:
        row = disconnect_feed(db, bank_account_id, actor=actor)
        db.commit()
        return BankFeedOut.model_validate(row)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.post("/{bank_account_id}/sync", response_model=FeedSyncOut)
def sync(
    bank_account_id: int,
    year: int | None = None,
    month: int | None = None,
    db: Session = Depends(get_db),
    actor: str = Depends(get_actor),
) -> FeedSyncOut:
    try:
        row = sync_feed(
            db,
            bank_account_id,
            actor=actor,
            period_year=year,
            period_month=month,
        )
        db.commit()
        return FeedSyncOut.model_validate(row)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
