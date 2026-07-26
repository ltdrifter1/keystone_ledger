"""Idempotent defaults for bank budget targets used by recon health."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BankAccount, Transaction


def ensure_bank_budget_targets(db: Session) -> int:
    """
    Fill missing budget_balance for active banks.

    Uses opening balance as a baseline target when none is set so the dashboard
    health summary is useful on upgraded databases.
    """
    banks = list(db.scalars(select(BankAccount).where(BankAccount.is_active == True)).all())
    updated = 0
    for bank in banks:
        if bank.budget_balance is not None:
            continue
        # Prefer a soft target near current book balance so demo isn't all "below"
        activity = db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.bank_account_id == bank.id,
                Transaction.status != "void",
            )
        )
        book = Decimal(bank.opening_balance) + Decimal(activity or 0)
        # Round-ish operating target: 95% of current book (or opening if empty)
        baseline = book if book != 0 else Decimal(bank.opening_balance)
        bank.budget_balance = (baseline * Decimal("0.95")).quantize(Decimal("0.01"))
        updated += 1
    if updated:
        db.commit()
    return updated
