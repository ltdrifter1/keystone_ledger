from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.engines.audit import write_audit
from app.models import BankAccount, Reconciliation, ReconciliationItem, Transaction


def period_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def period_start(year: int, month: int) -> date:
    return date(year, month, 1)


def beginning_balance(db: Session, bank_account_id: int, year: int, month: int) -> Decimal:
    """
    Statement beginning balance for a period:
    - prior locked reconciliation's statement ending balance, else
    - bank opening balance + all transactions before period start.
    """
    prior = db.scalar(
        select(Reconciliation)
        .where(
            Reconciliation.bank_account_id == bank_account_id,
            Reconciliation.status == "locked",
            or_(
                Reconciliation.period_year < year,
                and_(Reconciliation.period_year == year, Reconciliation.period_month < month),
            ),
        )
        .order_by(Reconciliation.period_year.desc(), Reconciliation.period_month.desc())
        .limit(1)
    )
    if prior:
        return Decimal(prior.statement_ending_balance)

    bank = db.get(BankAccount, bank_account_id)
    if not bank:
        raise ValueError("Bank account not found")
    start = period_start(year, month)
    prior_activity = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.bank_account_id == bank_account_id,
            Transaction.txn_date < start,
            Transaction.status != "void",
        )
    )
    return Decimal(bank.opening_balance) + Decimal(prior_activity or 0)


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

    # Disallow creating a period before an open prior period for same account
    open_prior = db.scalar(
        select(Reconciliation).where(
            Reconciliation.bank_account_id == bank_account_id,
            Reconciliation.status.in_(["open", "in_progress", "completed"]),
            or_(
                Reconciliation.period_year < period_year,
                and_(
                    Reconciliation.period_year == period_year,
                    Reconciliation.period_month < period_month,
                ),
            ),
        )
    )
    if open_prior:
        raise ValueError(
            f"Lock prior period {open_prior.period_year}-{open_prior.period_month:02d} before creating a newer one."
        )

    beg = beginning_balance(db, bank_account_id, period_year, period_month)
    recon = Reconciliation(
        bank_account_id=bank_account_id,
        period_year=period_year,
        period_month=period_month,
        statement_ending_balance=statement_ending_balance,
        calculated_balance=beg,
        difference=statement_ending_balance - beg,
        status="in_progress",
        notes=notes,
    )
    db.add(recon)
    db.flush()
    sync_reconciliation_items(db, recon)
    refresh_reconciliation_totals(db, recon)

    write_audit(
        db,
        entity_table="reconciliations",
        entity_id=recon.id,
        action="create",
        actor=actor,
        meta={
            "period": f"{period_year}-{period_month:02d}",
            "beginning_balance": str(beg),
            "statement_ending_balance": str(statement_ending_balance),
        },
    )
    return recon


def sync_reconciliation_items(db: Session, recon: Reconciliation) -> int:
    """Attach any missing unreconciled transactions through period end."""
    if recon.status == "locked":
        return 0

    start = period_start(recon.period_year, recon.period_month)
    end = period_end(recon.period_year, recon.period_month)
    existing_ids = set(
        db.scalars(
            select(ReconciliationItem.transaction_id).where(
                ReconciliationItem.reconciliation_id == recon.id
            )
        ).all()
    )

    # Include prior-period uncleared (timing differences) + current period activity
    txns = db.scalars(
        select(Transaction).where(
            Transaction.bank_account_id == recon.bank_account_id,
            Transaction.txn_date <= end,
            Transaction.status != "void",
        )
    ).all()
    txns = [t for t in txns if not t.is_reconciled]

    added = 0
    for txn in txns:
        if txn.id in existing_ids:
            continue
        db.add(
            ReconciliationItem(
                reconciliation_id=recon.id,
                transaction_id=txn.id,
                is_cleared=False,
            )
        )
        added += 1
    if added:
        db.flush()

    # Drop items that somehow became reconciled elsewhere
    stale = (
        db.scalars(
            select(ReconciliationItem)
            .options(joinedload(ReconciliationItem.transaction))
            .where(ReconciliationItem.reconciliation_id == recon.id)
        )
        .unique()
        .all()
    )
    for item in stale:
        txn = item.transaction
        if txn and txn.is_reconciled and txn.reconciliation_id not in (None, recon.id):
            db.delete(item)

    if added and recon.status == "open":
        recon.status = "in_progress"
    return added


def refresh_reconciliation_totals(db: Session, recon: Reconciliation) -> Reconciliation:
    db.flush()
    beg = beginning_balance(db, recon.bank_account_id, recon.period_year, recon.period_month)
    # Aggregate in Python — SQLite boolean filtering is unreliable across drivers
    items = (
        db.scalars(
            select(ReconciliationItem)
            .options(joinedload(ReconciliationItem.transaction))
            .where(ReconciliationItem.reconciliation_id == recon.id)
        )
        .unique()
        .all()
    )
    cleared_sum = Decimal("0")
    for item in items:
        txn = item.transaction
        if item.is_cleared and txn is not None and txn.status != "void":
            cleared_sum += Decimal(txn.amount)
    calc = beg + cleared_sum
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

    # Ensure items exist for requested transactions
    sync_reconciliation_items(db, recon)
    items = db.scalars(
        select(ReconciliationItem).where(
            ReconciliationItem.reconciliation_id == recon.id,
            ReconciliationItem.transaction_id.in_(list(transaction_ids)),
        )
    ).all()
    if not items:
        raise ValueError("No reconciliation items found for those transactions")

    for item in items:
        item.is_cleared = is_cleared
        item.cleared_at = datetime.utcnow() if is_cleared else None
        db.flush()
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


def clear_all(
    db: Session,
    recon: Reconciliation,
    *,
    only_categorized: bool = True,
    actor: str = "controller",
) -> Reconciliation:
    if recon.status == "locked":
        raise ValueError("Reconciliation is locked")

    items = db.scalars(
        select(ReconciliationItem)
        .options(joinedload(ReconciliationItem.transaction))
        .where(ReconciliationItem.reconciliation_id == recon.id)
    ).unique().all()

    ids: list[int] = []
    for item in items:
        txn = item.transaction
        if not txn or txn.status == "void":
            continue
        if only_categorized and txn.status == "uncategorized" and not txn.is_split:
            continue
        ids.append(txn.id)
    return set_cleared(db, recon, ids, True, actor=actor)


def uncleared_uncategorized_count(db: Session, recon: Reconciliation) -> int:
    """Count cleared-but-uncategorized items (Python-side for SQLite bool safety)."""
    items = (
        db.scalars(
            select(ReconciliationItem)
            .options(joinedload(ReconciliationItem.transaction))
            .where(ReconciliationItem.reconciliation_id == recon.id)
        )
        .unique()
        .all()
    )
    return sum(
        1
        for item in items
        if item.is_cleared
        and item.transaction is not None
        and not item.transaction.is_split
        and item.transaction.status == "uncategorized"
    )


def complete_reconciliation(
    db: Session,
    recon: Reconciliation,
    actor: str = "controller",
    lock: bool = True,
    require_categorized: bool = True,
) -> Reconciliation:
    if recon.status == "locked":
        raise ValueError("Reconciliation is already locked")

    sync_reconciliation_items(db, recon)
    refresh_reconciliation_totals(db, recon)

    if recon.difference != Decimal("0"):
        raise ValueError(
            f"Cannot complete: difference is {recon.difference}. "
            "Cleared book balance must equal statement ending balance."
        )

    if require_categorized:
        bad = uncleared_uncategorized_count(db, recon)
        # name is misleading — counts cleared-but-uncategorized
        if bad:
            raise ValueError(
                f"Cannot lock: {bad} cleared transaction(s) are still uncategorized. "
                "Categorize them before locking the period."
            )

    cleared_items = db.scalars(
        select(ReconciliationItem).where(
            ReconciliationItem.reconciliation_id == recon.id,
            ReconciliationItem.is_cleared == True,
        )
    )
    for item in cleared_items:
        txn = db.get(Transaction, item.transaction_id)
        if txn:
            txn.is_reconciled = True
            txn.reconciliation_id = recon.id

    # Uncleared items remain open for the next period (timing differences)
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
        meta={"difference": str(recon.difference), "calculated_balance": str(recon.calculated_balance)},
    )
    return recon


def lock_reconciliation(db: Session, recon: Reconciliation, actor: str = "controller") -> Reconciliation:
    if recon.status == "locked":
        return recon
    return complete_reconciliation(db, recon, actor=actor, lock=True)


def recon_workspace(db: Session, recon: Reconciliation) -> dict:
    """Full tie-out payload for the reconciliation UI."""
    sync_reconciliation_items(db, recon)
    refresh_reconciliation_totals(db, recon)
    beg = beginning_balance(db, recon.bank_account_id, recon.period_year, recon.period_month)

    items = (
        db.scalars(
            select(ReconciliationItem)
            .options(joinedload(ReconciliationItem.transaction).joinedload(Transaction.account))
            .where(ReconciliationItem.reconciliation_id == recon.id)
        )
        .unique()
        .all()
    )

    rows = []
    cleared_total = Decimal("0")
    uncleared_total = Decimal("0")
    uncategorized_cleared = 0
    for item in items:
        t = item.transaction
        if not t:
            continue
        amt = Decimal(t.amount)
        if item.is_cleared:
            cleared_total += amt
            if t.status == "uncategorized" and not t.is_split:
                uncategorized_cleared += 1
        else:
            uncleared_total += amt
        rows.append(
            {
                "id": item.id,
                "transaction_id": t.id,
                "is_cleared": item.is_cleared,
                "txn_date": t.txn_date.isoformat(),
                "description": t.description,
                "amount": float(amt),
                "currency": t.currency,
                "status": t.status,
                "is_split": t.is_split,
                "account_id": t.account_id,
                "account_code": t.account.code if t.account else None,
                "account_name": t.account.name if t.account else None,
                "in_period": period_start(recon.period_year, recon.period_month)
                <= t.txn_date
                <= period_end(recon.period_year, recon.period_month),
            }
        )

    rows.sort(key=lambda r: (r["is_cleared"], r["txn_date"], r["transaction_id"]))

    return {
        "id": recon.id,
        "bank_account_id": recon.bank_account_id,
        "period_year": recon.period_year,
        "period_month": recon.period_month,
        "status": recon.status,
        "beginning_balance": float(beg),
        "statement_ending_balance": float(recon.statement_ending_balance),
        "cleared_total": float(cleared_total),
        "uncleared_total": float(uncleared_total),
        "calculated_balance": float(recon.calculated_balance or 0),
        "difference": float(recon.difference or 0),
        "cleared_count": sum(1 for r in rows if r["is_cleared"]),
        "uncleared_count": sum(1 for r in rows if not r["is_cleared"]),
        "uncategorized_cleared_count": uncategorized_cleared,
        "can_lock": (
            recon.status != "locked"
            and Decimal(str(recon.difference or 0)) == Decimal("0")
            and uncategorized_cleared == 0
        ),
        "locked_at": recon.locked_at.isoformat() if recon.locked_at else None,
        "locked_by": recon.locked_by,
        "notes": recon.notes,
        "items": rows,
    }


def unreconciled_transactions(db: Session, bank_account_id: int | None = None) -> list[Transaction]:
    q = select(Transaction).where(
        Transaction.is_reconciled == False,
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
