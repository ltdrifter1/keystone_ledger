from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.engines.audit import audit_field_changes, write_audit
from app.engines.rules import create_rule_from_transaction
from app.models import Transaction, TransactionSplit
from app.schemas.transactions import CategorizeRequest, SplitIn


def categorize_transaction(
    db: Session,
    txn: Transaction,
    payload: CategorizeRequest,
    actor: str = "controller",
) -> Transaction:
    old_account = txn.account_id
    txn.account_id = payload.account_id
    if payload.department_id is not None:
        txn.department_id = payload.department_id
    if payload.counter_entity_id is not None:
        txn.counter_entity_id = payload.counter_entity_id
    txn.status = "categorized"
    txn.categorized_by_rule_id = None

    audit_field_changes(
        db,
        entity_table="transactions",
        entity_id=txn.id,
        changes={"account_id": (old_account, payload.account_id)},
        actor=actor,
        action="categorize",
    )

    if payload.create_rule:
        create_rule_from_transaction(
            db,
            txn,
            name=payload.rule_name,
            remember_description=payload.remember_description,
            actor=actor,
        )
    return txn


def split_transaction(
    db: Session,
    txn: Transaction,
    splits: list[SplitIn],
    actor: str = "controller",
) -> Transaction:
    if not splits:
        raise ValueError("At least one split line is required")

    total = sum((s.amount for s in splits), Decimal("0"))
    if total != txn.amount:
        raise ValueError(f"Split amounts ({total}) must equal transaction amount ({txn.amount})")

    txn.splits.clear()
    db.flush()

    for s in splits:
        txn.splits.append(
            TransactionSplit(
                account_id=s.account_id,
                department_id=s.department_id,
                amount=s.amount,
                memo=s.memo,
                sort_order=s.sort_order,
            )
        )

    txn.is_split = True
    txn.account_id = None  # reporting uses splits
    txn.status = "categorized"
    write_audit(
        db,
        entity_table="transactions",
        entity_id=txn.id,
        action="split",
        actor=actor,
        meta={"lines": len(splits), "total": str(total)},
    )
    return txn


def clear_splits(db: Session, txn: Transaction, account_id: int, actor: str = "controller") -> Transaction:
    txn.splits.clear()
    txn.is_split = False
    txn.account_id = account_id
    txn.status = "categorized"
    write_audit(
        db,
        entity_table="transactions",
        entity_id=txn.id,
        action="unsplit",
        new_value=account_id,
        actor=actor,
    )
    return txn
