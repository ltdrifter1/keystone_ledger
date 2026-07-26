from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.engines.reconciliation import (
    clear_all,
    complete_reconciliation,
    create_reconciliation,
    lock_reconciliation,
    recon_workspace,
    reconciliation_status_summary,
    set_cleared,
    sync_reconciliation_items,
    unreconciled_transactions,
)
from app.models import Reconciliation, ReconciliationItem
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
            ReconciliationItem.is_cleared == True,
        )
    ) or 0
    uncleared = db.scalar(
        select(func.count()).where(
            ReconciliationItem.reconciliation_id == recon.id,
            ReconciliationItem.is_cleared == False,
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


@router.get("/{recon_id}/workspace")
def workspace(recon_id: int, db: Session = Depends(get_db)) -> dict:
    recon = db.get(Reconciliation, recon_id)
    if not recon:
        raise HTTPException(404, "Not found")
    data = recon_workspace(db, recon)
    db.commit()  # persist sync side-effects
    return data


@router.get("/{recon_id}/items")
def get_items(recon_id: int, db: Session = Depends(get_db)) -> list[dict]:
    recon = db.get(Reconciliation, recon_id)
    if not recon:
        raise HTTPException(404, "Not found")
    data = recon_workspace(db, recon)
    db.commit()
    return data["items"]


@router.post("/{recon_id}/sync")
def sync(recon_id: int, db: Session = Depends(get_db)) -> dict:
    recon = db.get(Reconciliation, recon_id)
    if not recon:
        raise HTTPException(404, "Not found")
    if recon.status == "locked":
        raise HTTPException(409, "Reconciliation is locked")
    added = sync_reconciliation_items(db, recon)
    db.commit()
    return recon_workspace(db, recon) | {"added": added}


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


@router.post("/{recon_id}/clear-all")
def clear_all_items(recon_id: int, only_categorized: bool = True, db: Session = Depends(get_db)) -> dict:
    recon = db.get(Reconciliation, recon_id)
    if not recon:
        raise HTTPException(404, "Not found")
    try:
        clear_all(db, recon, only_categorized=only_categorized, actor="controller")
        db.commit()
        return recon_workspace(db, recon)
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
    try:
        lock_reconciliation(db, recon, actor="controller")
        db.commit()
        db.refresh(recon)
        return _to_out(db, recon)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
