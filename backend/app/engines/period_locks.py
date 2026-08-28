"""Hard gates for locked reconciliation periods."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Reconciliation, Transaction


PROTECTED_FIELDS = {
    "txn_date",
    "amount",
    "currency",
    "entity_id",
    "bank_account_id",
    "description",
    "status",
}


class PeriodLockedError(ValueError):
    """Raised when an edit would mutate a locked period."""


def locked_recon_for_txn(db: Session, txn: Transaction) -> Reconciliation | None:
    """Return the locked reconciliation covering this transaction, if any."""
    if not txn.bank_account_id:
        return None

    # Direct link wins
    if txn.reconciliation_id and txn.is_reconciled:
        recon = db.get(Reconciliation, txn.reconciliation_id)
        if recon and recon.status == "locked":
            return recon

    # Also block edits inside any locked period for the bank account/date
    locked = db.scalars(
        select(Reconciliation).where(
            Reconciliation.bank_account_id == txn.bank_account_id,
            Reconciliation.status == "locked",
        )
    ).all()
    for recon in locked:
        start = date(recon.period_year, recon.period_month, 1)
        # period_end imported lazily to avoid circular import issues in typing
        from app.engines.reconciliation import period_end

        end = period_end(recon.period_year, recon.period_month)
        if start <= txn.txn_date <= end:
            return recon
    return None


def assert_txn_editable(
    db: Session,
    txn: Transaction,
    *,
    changing_fields: set[str] | None = None,
    allow_categorization_when_uncleared: bool = True,
) -> None:
    """
    Hard gate: locked periods cannot be silently edited.

    Categorization fields may still be edited for uncleared items in open periods.
    Anything in a locked period is fully frozen.
    """
    locked = locked_recon_for_txn(db, txn)
    if locked:
        raise PeriodLockedError(
            f"Period {locked.period_year}-{locked.period_month:02d} is locked "
            f"(reconciliation #{locked.id}). Unlock is not available — post a post-close adjusting journal."
        )
    if txn.entity_id and txn.source_type != "post_close_adj":
        from app.engines.entity_close import is_entity_month_locked

        gl_lock = is_entity_month_locked(db, txn.entity_id, txn.txn_date)
        if gl_lock:
            raise PeriodLockedError(
                f"{gl_lock.period_year}-{gl_lock.period_month:02d} is locked for this company. "
                "Post a post-close adjusting journal (PCA)."
            )

    if txn.is_reconciled and changing_fields:
        protected = changing_fields & PROTECTED_FIELDS
        if protected:
            raise PeriodLockedError(
                f"Transaction #{txn.id} is reconciled; cannot change {', '.join(sorted(protected))}."
            )
        # categorization-only changes on reconciled-but-unlocked are blocked too for integrity
        if not allow_categorization_when_uncleared:
            raise PeriodLockedError(f"Transaction #{txn.id} is reconciled and cannot be edited.")


def assert_bank_period_open(db: Session, bank_account_id: int, txn_date: date) -> None:
    locked = db.scalars(
        select(Reconciliation).where(
            Reconciliation.bank_account_id == bank_account_id,
            Reconciliation.status == "locked",
        )
    ).all()
    from app.engines.reconciliation import period_end

    for recon in locked:
        start = date(recon.period_year, recon.period_month, 1)
        end = period_end(recon.period_year, recon.period_month)
        if start <= txn_date <= end:
            raise PeriodLockedError(
                f"Cannot post into locked period {recon.period_year}-{recon.period_month:02d} "
                f"for bank account #{bank_account_id}."
            )
