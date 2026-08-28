from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.auth import get_actor
from app.database import get_db
from app.engines.audit import write_audit
from app.engines.categorization import categorize_transaction, split_transaction
from app.engines.inbox import mark_bank_transfer, mark_intercompany
from app.engines.intercompany import auto_match_intercompany, find_intercompany_candidates
from app.engines.period_locks import PeriodLockedError, assert_bank_period_open, assert_txn_editable, locked_recon_for_txn
from app.engines.rules import apply_rules_batch
from app.models import Transaction
from app.schemas.transactions import (
    BulkCategorizeRequest,
    CategorizeRequest,
    IntercompanyMatchOut,
    MarkIntercompanyRequest,
    MarkTransferRequest,
    SplitRequest,
    TransactionCreate,
    TransactionOut,
    TransactionUpdate,
)

router = APIRouter(prefix="/transactions")


def _load_txn(db: Session, txn_id: int) -> Transaction | None:
    return db.scalars(
        select(Transaction)
        .options(
            joinedload(Transaction.entity),
            joinedload(Transaction.account),
            joinedload(Transaction.bank_account),
            joinedload(Transaction.splits),
        )
        .where(Transaction.id == txn_id)
    ).first()


def _to_out(db: Session, txn: Transaction) -> TransactionOut:
    data = TransactionOut.model_validate(txn)
    if txn.entity:
        data.entity_code = txn.entity.code
    if txn.account:
        data.account_code = txn.account.code
        data.account_name = txn.account.name
    if txn.bank_account:
        data.bank_account_name = txn.bank_account.name
    locked = locked_recon_for_txn(db, txn)
    data.is_period_locked = locked is not None
    data.is_editable = locked is None and not txn.is_reconciled
    return data


@router.get("", response_model=list[TransactionOut])
def list_transactions(
    entity_id: Optional[int] = None,
    bank_account_id: Optional[int] = None,
    account_id: Optional[int] = None,
    department_id: Optional[int] = None,
    scenario_id: Optional[int] = None,
    status: Optional[str] = None,
    currency: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    uncategorized_only: bool = False,
    unreconciled_only: bool = False,
    duplicates_only: bool = False,
    unmatched_ic_only: bool = False,
    limit: int = Query(200, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[TransactionOut]:
    q = (
        select(Transaction)
        .options(
            joinedload(Transaction.entity),
            joinedload(Transaction.account),
            joinedload(Transaction.bank_account),
            joinedload(Transaction.splits),
        )
        .order_by(Transaction.txn_date.desc(), Transaction.id.desc())
    )
    if entity_id:
        q = q.where(Transaction.entity_id == entity_id)
    if bank_account_id:
        q = q.where(Transaction.bank_account_id == bank_account_id)
    if account_id:
        q = q.where(Transaction.account_id == account_id)
    if department_id:
        q = q.where(Transaction.department_id == department_id)
    if scenario_id:
        q = q.where(Transaction.scenario_id == scenario_id)
    if status:
        q = q.where(Transaction.status == status)
    if currency:
        q = q.where(Transaction.currency == currency)
    if date_from:
        q = q.where(Transaction.txn_date >= date_from)
    if date_to:
        q = q.where(Transaction.txn_date <= date_to)
    if uncategorized_only:
        q = q.where(Transaction.status == "uncategorized", Transaction.is_split == False)
    if unreconciled_only:
        q = q.where(Transaction.is_reconciled == False, Transaction.bank_account_id.is_not(None))
    if duplicates_only:
        q = q.where(Transaction.is_duplicate == True)
    if unmatched_ic_only:
        q = q.where(Transaction.counter_entity_id.is_not(None), Transaction.intercompany_match_id.is_(None))
    if search:
        like = f"%{search}%"
        q = q.where(
            or_(
                Transaction.description.ilike(like),
                Transaction.counterparty.ilike(like),
                Transaction.reference.ilike(like),
                Transaction.memo.ilike(like),
            )
        )

    rows = db.scalars(q.offset(offset).limit(limit)).unique().all()
    return [_to_out(db, t) for t in rows]


@router.post("", response_model=TransactionOut)
def create_transaction(
    payload: TransactionCreate, db: Session = Depends(get_db), actor: str = Depends(get_actor)
) -> TransactionOut:
    from app.engines.importing import ensure_date_dimension

    try:
        if payload.bank_account_id:
            assert_bank_period_open(db, payload.bank_account_id, payload.txn_date)
    except PeriodLockedError as exc:
        raise HTTPException(409, str(exc)) from exc

    txn = Transaction(**payload.model_dump())
    txn.date_key = ensure_date_dimension(db, txn.txn_date)
    if txn.account_id:
        txn.status = "categorized"
    db.add(txn)
    db.flush()
    write_audit(db, entity_table="transactions", entity_id=txn.id, action="create", actor=actor)
    db.commit()
    loaded = _load_txn(db, txn.id)
    return _to_out(db, loaded)


@router.patch("/{txn_id}", response_model=TransactionOut)
def update_transaction(
    txn_id: int, payload: TransactionUpdate, db: Session = Depends(get_db), actor: str = Depends(get_actor)
) -> TransactionOut:
    txn = db.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")

    data = payload.model_dump(exclude_unset=True, exclude={"create_rule", "rule_name"})
    try:
        assert_txn_editable(db, txn, changing_fields=set(data.keys()))
        if "txn_date" in data or "bank_account_id" in data:
            bank_id = data.get("bank_account_id", txn.bank_account_id)
            txn_date = data.get("txn_date", txn.txn_date)
            if bank_id:
                assert_bank_period_open(db, bank_id, txn_date)
    except PeriodLockedError as exc:
        raise HTTPException(409, str(exc)) from exc

    for k, v in data.items():
        setattr(txn, k, v)
    if "account_id" in data and data["account_id"]:
        txn.status = "categorized"
        txn.is_split = False
        txn.splits.clear()

    if payload.create_rule and txn.account_id:
        from app.engines.rules import create_rule_from_transaction

        create_rule_from_transaction(db, txn, name=payload.rule_name, actor=actor)

    write_audit(db, entity_table="transactions", entity_id=txn.id, action="update", actor=actor)
    db.commit()
    loaded = _load_txn(db, txn_id)
    return _to_out(db, loaded)


@router.post("/{txn_id}/mark-transfer", response_model=TransactionOut)
def mark_transfer(
    txn_id: int,
    payload: MarkTransferRequest,
    db: Session = Depends(get_db),
    actor: str = Depends(get_actor),
) -> TransactionOut:
    txn = db.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")
    try:
        mark_bank_transfer(
            db,
            txn,
            other_bank_account_id=payload.other_bank_account_id,
            create_rule=payload.create_rule,
            actor=actor,
        )
        db.commit()
    except PeriodLockedError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    loaded = _load_txn(db, txn_id)
    return _to_out(db, loaded)


@router.post("/{txn_id}/mark-intercompany", response_model=TransactionOut)
def mark_ic(
    txn_id: int,
    payload: MarkIntercompanyRequest,
    db: Session = Depends(get_db),
    actor: str = Depends(get_actor),
) -> TransactionOut:
    txn = db.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")
    try:
        mark_intercompany(
            db,
            txn,
            counter_entity_id=payload.counter_entity_id,
            create_rule=payload.create_rule,
            actor=actor,
        )
        db.commit()
    except PeriodLockedError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    loaded = _load_txn(db, txn_id)
    return _to_out(db, loaded)


@router.post("/{txn_id}/categorize", response_model=TransactionOut)
def categorize(
    txn_id: int, payload: CategorizeRequest, db: Session = Depends(get_db), actor: str = Depends(get_actor)
) -> TransactionOut:
    txn = db.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")
    try:
        categorize_transaction(db, txn, payload, actor=actor)
        db.commit()
    except PeriodLockedError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    loaded = _load_txn(db, txn_id)
    return _to_out(db, loaded)


@router.post("/bulk-categorize")
def bulk_categorize(
    payload: BulkCategorizeRequest, db: Session = Depends(get_db), actor: str = Depends(get_actor)
) -> dict:
    count = 0
    skipped_locked = 0
    for txn_id in payload.transaction_ids:
        txn = db.get(Transaction, txn_id)
        if not txn:
            continue
        try:
            categorize_transaction(
                db,
                txn,
                CategorizeRequest(
                    account_id=payload.account_id,
                    department_id=payload.department_id,
                    create_rule=payload.create_rule and count == 0,
                ),
                actor=actor,
            )
            count += 1
        except PeriodLockedError:
            skipped_locked += 1
    db.commit()
    return {"categorized": count, "skipped_locked": skipped_locked}


@router.post("/{txn_id}/split", response_model=TransactionOut)
def split(
    txn_id: int, payload: SplitRequest, db: Session = Depends(get_db), actor: str = Depends(get_actor)
) -> TransactionOut:
    txn = db.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")
    try:
        split_transaction(db, txn, payload.splits, actor=actor)
        db.commit()
    except PeriodLockedError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    loaded = _load_txn(db, txn_id)
    return _to_out(db, loaded)


@router.post("/apply-rules")
def apply_rules(db: Session = Depends(get_db), actor: str = Depends(get_actor)) -> dict:
    txns = list(db.scalars(select(Transaction).where(Transaction.status == "uncategorized")))
    editable = []
    skipped_locked = 0
    for txn in txns:
        try:
            assert_txn_editable(db, txn, changing_fields={"account_id", "status"})
            editable.append(txn)
        except PeriodLockedError:
            skipped_locked += 1
    count = apply_rules_batch(db, editable, actor=actor)
    db.commit()
    return {"categorized": count, "skipped_locked": skipped_locked}


@router.get("/intercompany/candidates", response_model=list[IntercompanyMatchOut])
def ic_candidates(db: Session = Depends(get_db)) -> list[IntercompanyMatchOut]:
    return find_intercompany_candidates(db)


@router.post("/intercompany/auto-match")
def ic_auto_match(db: Session = Depends(get_db), actor: str = Depends(get_actor)) -> dict:
    count = auto_match_intercompany(db, actor=actor)
    db.commit()
    return {"matched": count}
