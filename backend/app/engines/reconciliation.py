from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.engines.audit import write_audit
from app.models import BankAccount, Reconciliation, ReconciliationItem, Transaction


def period_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def calculated_book_balance(db: Session, bank_account_id: int, as_of: date) -> Decimal:
    bank = db.get(BankAccount, bank_account_id)
    if not bank:
        raise ValueError("Bank account not found")
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.bank_account_id == bank_account_id,
            Transaction.txn_date <= as_of,
            Transaction.status != "void",
        )
    )
    return Decimal(bank.opening_balance) + Decimal(total or 0)


def create_reconciliation(
    db: Session,
    *,
    bank_account_id: int,
    period_year: int,
    period_month: int,
    statement_ending_balance: Decimal,
    notes: str | None = None,
    actor: str = "controller",
) -> Reconciliation:
    existing = db.scalar(
        select(Reconciliation).where(
            Reconciliation.bank_account_id == bank_account_id,
            Reconciliation.period_year == period_year,
            Reconciliation.period_month == period_month,
        )
    )
    if existing:
        raise ValueError("Reconciliation already exists for this period")

    as_of = period_end(period_year, period_month)
    calc = calculated_book_balance(db, bank_account_id, as_of)
    recon = Reconciliation(
        bank_account_id=bank_account_id,
        period_year=period_year,
        period_month=period_month,
        statement_ending_balance=statement_ending_balance,
        calculated_balance=calc,
        difference=statement_ending_balance - calc,
        status="in_progress",
        notes=notes,
    )
    db.add(recon)
    db.flush()

    # Attach uncleared transactions through period end
    txns = db.scalars(
        select(Transaction).where(
            Transaction.bank_account_id == bank_account_id,
            Transaction.txn_date <= as_of,
            Transaction.is_reconciled.is_(False),
            Transaction.status != "void",
        )
    )
    for txn in txns:
        db.add(
            ReconciliationItem(
                reconciliation_id=recon.id,
                transaction_id=txn.id,
                is_cleared=False,
            )
        )

    write_audit(
        db,
        entity_table="reconciliations",
        entity_id=recon.id,
        action="create",
        actor=actor,
        meta={"period": f"{period_year}-{period_month:02d}"},
    )
    return recon


def refresh_reconciliation_totals(db: Session, recon: Reconciliation) -> Reconciliation:
    as_of = period_end(recon.period_year, recon.period_month)
    # Cleared items contribute; uncleared create the reconciling difference vs statement
    cleared_sum = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .join(ReconciliationItem, ReconciliationItem.transaction_id == Transaction.id)
        .where(
            ReconciliationItem.reconciliation_id == recon.id,
            ReconciliationItem.is_cleared.is_(True),
        )
    )
    bank = db.get(BankAccount, recon.bank_account_id)
    # Prior locked reconciliations' ending balances would be ideal; use opening + all cleared historically
    prior_cleared = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.bank_account_id == recon.bank_account_id,
            Transaction.is_reconciled.is_(True),
            Transaction.txn_date <= as_of,
            Transaction.reconciliation_id.is_not(None),
            Transaction.reconciliation_id != recon.id,
        )
    )
    calc = Decimal(bank.opening_balance) + Decimal(prior_cleared or 0) + Decimal(cleared_sum or 0)
    recon.calculated_balance = calc
    recon.difference = Decimal(recon.statement_ending_balance) - calc
    return recon


def set_cleared(
    db: Session,
    recon: Reconciliation,
    transaction_ids: list[int],
    is_cleared: bool,
    actor: str = "controller",
) -> Reconciliation:
    if recon.status == "locked":
        raise ValueError("Reconciliation is locked")

    items = db.scalars(
        select(ReconciliationItem).where(
            ReconciliationItem.reconciliation_id == recon.id,
            ReconciliationItem.transaction_id.in_(transaction_ids),
        )
    )
    for item in items:
        item.is_cleared = is_cleared
        item.cleared_at = datetime.utcnow() if is_cleared else None
        write_audit(
            db,
            entity_table="reconciliation_items",
            entity_id=item.id,
            action="clear" if is_cleared else "unclear",
            actor=actor,
            meta={"transaction_id": item.transaction_id},
        )

    if recon.status == "open":
        recon.status = "in_progress"
    refresh_reconciliation_totals(db, recon)
    return recon


def complete_reconciliation(
    db: Session,
    recon: Reconciliation,
    actor: str = "controller",
    lock: bool = False,
) -> Reconciliation:
    refresh_reconciliation_totals(db, recon)
    if recon.difference != Decimal("0"):
        raise ValueError(f"Cannot complete: difference is {recon.difference}")

    cleared_items = db.scalars(
        select(ReconciliationItem).where(
            ReconciliationItem.reconciliation_id == recon.id,
            ReconciliationItem.is_cleared.is_(True),
        )
    )
    for item in cleared_items:
        txn = db.get(Transaction, item.transaction_id)
        if txn:
            txn.is_reconciled = True
            txn.reconciliation_id = recon.id

    recon.status = "locked" if lock else "completed"
    recon.completed_at = datetime.utcnow()
    if lock:
        recon.locked_at = datetime.utcnow()
        recon.locked_by = actor

    write_audit(
        db,
        entity_table="reconciliations",
        entity_id=recon.id,
        action="lock" if lock else "complete",
        actor=actor,
    )
    return recon


def lock_reconciliation(db: Session, recon: Reconciliation, actor: str = "controller") -> Reconciliation:
    if recon.status not in ("completed", "locked"):
        return complete_reconciliation(db, recon, actor=actor, lock=True)
    recon.status = "locked"
    recon.locked_at = datetime.utcnow()
    recon.locked_by = actor
    write_audit(db, entity_table="reconciliations", entity_id=recon.id, action="lock", actor=actor)
    return recon


def unreconciled_transactions(db: Session, bank_account_id: int | None = None) -> list[Transaction]:
    q = select(Transaction).where(
        Transaction.is_reconciled.is_(False),
        Transaction.status != "void",
        Transaction.bank_account_id.is_not(None),
    )
    if bank_account_id:
        q = q.where(Transaction.bank_account_id == bank_account_id)
    return list(db.scalars(q.order_by(Transaction.txn_date.desc())))


def reconciliation_status_summary(db: Session) -> list[dict]:
    rows = db.execute(
        select(
            Reconciliation.bank_account_id,
            Reconciliation.period_year,
            Reconciliation.period_month,
            Reconciliation.status,
            Reconciliation.difference,
        ).order_by(
            Reconciliation.period_year.desc(),
            Reconciliation.period_month.desc(),
        )
    ).all()
    return [
        {
            "bank_account_id": r.bank_account_id,
            "period": f"{r.period_year}-{r.period_month:02d}",
            "status": r.status,
            "difference": float(r.difference or 0),
        }
        for r in rows
    ]
