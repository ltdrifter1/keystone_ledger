from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.engines.reconciliation import (
    complete_reconciliation,
    create_reconciliation,
    lock_reconciliation,
    reconciliation_status_summary,
    set_cleared,
    unreconciled_transactions,
)
from app.models import Reconciliation, ReconciliationItem, Transaction
from app.schemas.transactions import (
    ReconciliationClearRequest,
    ReconciliationCreate,
    ReconciliationOut,
    TransactionOut,
)

router = APIRouter(prefix="/reconciliations")


def _to_out(db: Session, recon: Reconciliation) -> ReconciliationOut:
    cleared = db.scalar(
        select(func.count()).where(
            ReconciliationItem.reconciliation_id == recon.id,
            ReconciliationItem.is_cleared.is_(True),
        )
    ) or 0
    uncleared = db.scalar(
        select(func.count()).where(
            ReconciliationItem.reconciliation_id == recon.id,
            ReconciliationItem.is_cleared.is_(False),
        )
    ) or 0
    out = ReconciliationOut.model_validate(recon)
    out.cleared_count = int(cleared)
    out.uncleared_count = int(uncleared)
    return out


@router.get("", response_model=list[ReconciliationOut])
def list_reconciliations(db: Session = Depends(get_db)) -> list[ReconciliationOut]:
    rows = db.scalars(
        select(Reconciliation).order_by(
            Reconciliation.period_year.desc(),
            Reconciliation.period_month.desc(),
        )
    ).all()
    return [_to_out(db, r) for r in rows]


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> list[dict]:
    return reconciliation_status_summary(db)


@router.get("/unreconciled", response_model=list[TransactionOut])
def list_unreconciled(bank_account_id: int | None = None, db: Session = Depends(get_db)) -> list[TransactionOut]:
    txns = unreconciled_transactions(db, bank_account_id)
    return [TransactionOut.model_validate(t) for t in txns]


@router.post("", response_model=ReconciliationOut)
def create(payload: ReconciliationCreate, db: Session = Depends(get_db)) -> ReconciliationOut:
    try:
        recon = create_reconciliation(
            db,
            bank_account_id=payload.bank_account_id,
            period_year=payload.period_year,
            period_month=payload.period_month,
            statement_ending_balance=payload.statement_ending_balance,
            notes=payload.notes,
            actor="controller",
        )
        db.commit()
        db.refresh(recon)
        return _to_out(db, recon)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.get("/{recon_id}", response_model=ReconciliationOut)
def get_one(recon_id: int, db: Session = Depends(get_db)) -> ReconciliationOut:
    recon = db.get(Reconciliation, recon_id)
    if not recon:
        raise HTTPException(404, "Not found")
    return _to_out(db, recon)


@router.get("/{recon_id}/items")
def get_items(recon_id: int, db: Session = Depends(get_db)) -> list[dict]:
    items = db.scalars(
        select(ReconciliationItem)
        .options(joinedload(ReconciliationItem.transaction))
        .where(ReconciliationItem.reconciliation_id == recon_id)
    ).unique().all()
    result = []
    for item in items:
        t = item.transaction
        result.append(
            {
                "id": item.id,
                "transaction_id": item.transaction_id,
                "is_cleared": item.is_cleared,
                "txn_date": t.txn_date.isoformat() if t else None,
                "description": t.description if t else None,
                "amount": float(t.amount) if t else None,
                "currency": t.currency if t else None,
            }
        )
    return result


@router.post("/{recon_id}/clear", response_model=ReconciliationOut)
def clear_items(recon_id: int, payload: ReconciliationClearRequest, db: Session = Depends(get_db)) -> ReconciliationOut:
    recon = db.get(Reconciliation, recon_id)
    if not recon:
        raise HTTPException(404, "Not found")
    try:
        set_cleared(db, recon, payload.transaction_ids, payload.is_cleared, actor="controller")
        db.commit()
        db.refresh(recon)
        return _to_out(db, recon)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{recon_id}/complete", response_model=ReconciliationOut)
def complete(recon_id: int, lock: bool = True, db: Session = Depends(get_db)) -> ReconciliationOut:
    recon = db.get(Reconciliation, recon_id)
    if not recon:
        raise HTTPException(404, "Not found")
    try:
        complete_reconciliation(db, recon, actor="controller", lock=lock)
        db.commit()
        db.refresh(recon)
        return _to_out(db, recon)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{recon_id}/lock", response_model=ReconciliationOut)
def lock(recon_id: int, db: Session = Depends(get_db)) -> ReconciliationOut:
    recon = db.get(Reconciliation, recon_id)
    if not recon:
        raise HTTPException(404, "Not found")
    lock_reconciliation(db, recon, actor="controller")
    db.commit()
    db.refresh(recon)
    return _to_out(db, recon)
