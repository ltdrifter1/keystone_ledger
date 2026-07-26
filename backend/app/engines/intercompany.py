from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.audit import write_audit
from app.models import DimAccount, Transaction
from app.schemas.transactions import IntercompanyMatchOut


def _is_transfer_like(txn: Transaction, transfer_account_ids: set[int]) -> bool:
    if txn.counter_entity_id is not None:
        return True
    if txn.account_id and txn.account_id in transfer_account_ids:
        return True
    desc = (txn.description or "").upper()
    return any(k in desc for k in ("INTERCOMPANY", "IC TRANSFER", "TRANSFER TO", "TRANSFER FROM"))


def find_intercompany_candidates(db: Session, lookback_days: int = 7) -> list[IntercompanyMatchOut]:
    """Match opposite-signed amounts across entities within a date window."""
    transfer_accounts = set(
        db.scalars(
            select(DimAccount.id).where(
                (DimAccount.is_intercompany.is_(True)) | (DimAccount.account_type == "transfer")
            )
        )
    )

    txns = list(
        db.scalars(
            select(Transaction).where(
                Transaction.status != "void",
                Transaction.intercompany_match_id.is_(None),
            )
        )
    )
    candidates = [t for t in txns if _is_transfer_like(t, transfer_accounts)]
    matches: list[IntercompanyMatchOut] = []
    used: set[int] = set()

    for left in candidates:
        if left.id in used:
            continue
        for right in candidates:
            if right.id in used or right.id == left.id:
                continue
            if left.entity_id == right.entity_id:
                continue
            if left.currency != right.currency:
                continue
            if left.amount + right.amount != Decimal("0"):
                continue
            if abs((left.txn_date - right.txn_date).days) > lookback_days:
                continue
            # Prefer explicit counter-entity hints
            confidence = "high"
            if left.counter_entity_id and left.counter_entity_id != right.entity_id:
                continue
            if right.counter_entity_id and right.counter_entity_id != left.entity_id:
                continue
            if not left.counter_entity_id and not right.counter_entity_id:
                confidence = "medium"

            matches.append(
                IntercompanyMatchOut(
                    left_id=left.id,
                    right_id=right.id,
                    amount=abs(left.amount),
                    left_entity_id=left.entity_id,
                    right_entity_id=right.entity_id,
                    confidence=confidence,
                )
            )
            used.add(left.id)
            used.add(right.id)
            break
    return matches


def apply_intercompany_match(
    db: Session,
    left_id: int,
    right_id: int,
    actor: str = "system",
) -> tuple[Transaction, Transaction]:
    left = db.get(Transaction, left_id)
    right = db.get(Transaction, right_id)
    if not left or not right:
        raise ValueError("Transaction not found")
    if left.amount + right.amount != Decimal("0"):
        raise ValueError("Amounts must be equal and opposite")

    left.intercompany_match_id = right.id
    right.intercompany_match_id = left.id
    left.counter_entity_id = right.entity_id
    right.counter_entity_id = left.entity_id
    if left.status == "uncategorized":
        left.status = "matched"
    if right.status == "uncategorized":
        right.status = "matched"

    write_audit(
        db,
        entity_table="transactions",
        entity_id=left.id,
        action="ic_match",
        new_value=right.id,
        actor=actor,
    )
    write_audit(
        db,
        entity_table="transactions",
        entity_id=right.id,
        action="ic_match",
        new_value=left.id,
        actor=actor,
    )
    return left, right


def auto_match_intercompany(db: Session, actor: str = "system") -> int:
    matches = find_intercompany_candidates(db)
    count = 0
    for m in matches:
        if m.confidence in ("high", "medium"):
            apply_intercompany_match(db, m.left_id, m.right_id, actor=actor)
            count += 1
    return count


def unmatched_intercompany_count(db: Session) -> int:
    transfer_accounts = set(
        db.scalars(
            select(DimAccount.id).where(
                (DimAccount.is_intercompany.is_(True)) | (DimAccount.account_type == "transfer")
            )
        )
    )
    txns = list(
        db.scalars(
            select(Transaction).where(
                Transaction.intercompany_match_id.is_(None),
                Transaction.status != "void",
            )
        )
    )
    return sum(1 for t in txns if _is_transfer_like(t, transfer_accounts))
