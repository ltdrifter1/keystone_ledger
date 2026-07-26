from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.engines.audit import write_audit
from app.engines.categorization import categorize_transaction, split_transaction
from app.engines.intercompany import auto_match_intercompany, find_intercompany_candidates
from app.engines.rules import apply_rules_batch
from app.models import BankAccount, DimAccount, DimEntity, Transaction
from app.schemas.transactions import (
    BulkCategorizeRequest,
    CategorizeRequest,
    IntercompanyMatchOut,
    SplitRequest,
    TransactionCreate,
    TransactionOut,
    TransactionUpdate,
)

router = APIRouter(prefix="/transactions")


def _to_out(txn: Transaction) -> TransactionOut:
    data = TransactionOut.model_validate(txn)
    if txn.entity:
        data.entity_code = txn.entity.code
    if txn.account:
        data.account_code = txn.account.code
        data.account_name = txn.account.name
    if txn.bank_account:
        data.bank_account_name = txn.bank_account.name
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
        q = q.where(Transaction.status == "uncategorized", Transaction.is_split.is_(False))
    if unreconciled_only:
        q = q.where(Transaction.is_reconciled.is_(False), Transaction.bank_account_id.is_not(None))
    if duplicates_only:
        q = q.where(Transaction.is_duplicate.is_(True))
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
    return [_to_out(t) for t in rows]


@router.post("", response_model=TransactionOut)
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_db)) -> TransactionOut:
    from app.engines.importing import ensure_date_dimension

    txn = Transaction(**payload.model_dump())
    txn.date_key = ensure_date_dimension(db, txn.txn_date)
    if txn.account_id:
        txn.status = "categorized"
    db.add(txn)
    db.flush()
    write_audit(db, entity_table="transactions", entity_id=txn.id, action="create", actor="controller")
    db.commit()
    db.refresh(txn)
    txn = db.scalars(
        select(Transaction)
        .options(
            joinedload(Transaction.entity),
            joinedload(Transaction.account),
            joinedload(Transaction.bank_account),
            joinedload(Transaction.splits),
        )
        .where(Transaction.id == txn.id)
    ).first()
    return _to_out(txn)


@router.patch("/{txn_id}", response_model=TransactionOut)
def update_transaction(txn_id: int, payload: TransactionUpdate, db: Session = Depends(get_db)) -> TransactionOut:
    txn = db.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")

    data = payload.model_dump(exclude_unset=True, exclude={"create_rule", "rule_name"})
    for k, v in data.items():
        setattr(txn, k, v)
    if "account_id" in data and data["account_id"]:
        txn.status = "categorized"

    if payload.create_rule and txn.account_id:
        from app.engines.rules import create_rule_from_transaction

        create_rule_from_transaction(db, txn, name=payload.rule_name, actor="controller")

    write_audit(db, entity_table="transactions", entity_id=txn.id, action="update", actor="controller")
    db.commit()

    txn = db.scalars(
        select(Transaction)
        .options(
            joinedload(Transaction.entity),
            joinedload(Transaction.account),
            joinedload(Transaction.bank_account),
            joinedload(Transaction.splits),
        )
        .where(Transaction.id == txn_id)
    ).first()
    return _to_out(txn)


@router.post("/{txn_id}/categorize", response_model=TransactionOut)
def categorize(txn_id: int, payload: CategorizeRequest, db: Session = Depends(get_db)) -> TransactionOut:
    txn = db.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")
    categorize_transaction(db, txn, payload, actor="controller")
    db.commit()
    txn = db.scalars(
        select(Transaction)
        .options(
            joinedload(Transaction.entity),
            joinedload(Transaction.account),
            joinedload(Transaction.bank_account),
            joinedload(Transaction.splits),
        )
        .where(Transaction.id == txn_id)
    ).first()
    return _to_out(txn)


@router.post("/bulk-categorize")
def bulk_categorize(payload: BulkCategorizeRequest, db: Session = Depends(get_db)) -> dict:
    from app.schemas.transactions import CategorizeRequest

    count = 0
    for txn_id in payload.transaction_ids:
        txn = db.get(Transaction, txn_id)
        if not txn:
            continue
        categorize_transaction(
            db,
            txn,
            CategorizeRequest(
                account_id=payload.account_id,
                department_id=payload.department_id,
                create_rule=payload.create_rule and count == 0,
            ),
            actor="controller",
        )
        count += 1
    db.commit()
    return {"categorized": count}


@router.post("/{txn_id}/split", response_model=TransactionOut)
def split(txn_id: int, payload: SplitRequest, db: Session = Depends(get_db)) -> TransactionOut:
    txn = db.get(Transaction, txn_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")
    try:
        split_transaction(db, txn, payload.splits, actor="controller")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    txn = db.scalars(
        select(Transaction)
        .options(
            joinedload(Transaction.entity),
            joinedload(Transaction.account),
            joinedload(Transaction.bank_account),
            joinedload(Transaction.splits),
        )
        .where(Transaction.id == txn_id)
    ).first()
    return _to_out(txn)


@router.post("/apply-rules")
def apply_rules(db: Session = Depends(get_db)) -> dict:
    txns = list(db.scalars(select(Transaction).where(Transaction.status == "uncategorized")))
    count = apply_rules_batch(db, txns, actor="controller")
    db.commit()
    return {"categorized": count}


@router.get("/intercompany/candidates", response_model=list[IntercompanyMatchOut])
def ic_candidates(db: Session = Depends(get_db)) -> list[IntercompanyMatchOut]:
    return find_intercompany_candidates(db)


@router.post("/intercompany/auto-match")
def ic_auto_match(db: Session = Depends(get_db)) -> dict:
    count = auto_match_intercompany(db, actor="controller")
    db.commit()
    return {"matched": count}
