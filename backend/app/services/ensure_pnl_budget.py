"""Synthesize monthly P&L BUDGET facts from ACTUAL so variance views work."""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines.fingerprint import transaction_fingerprint
from app.engines.importing import ensure_date_dimension
from app.models import DimAccount, DimScenario, Transaction

# Revenue stretch / expense hold so the Budget tab shows meaningful variance.
_REVENUE_FACTOR = Decimal("1.08")
_EXPENSE_FACTOR = Decimal("0.92")


def ensure_pnl_budget_targets(db: Session) -> int:
    """
    Idempotently create one BUDGET journal row per entity/account/month from ACTUAL.

    Skips if any BUDGET transactions already exist (controller-owned budgets win).
    """
    budget = db.scalar(select(DimScenario).where(DimScenario.code == "BUDGET"))
    actual = db.scalar(select(DimScenario).where(DimScenario.code == "ACTUAL"))
    if not budget or not actual:
        return 0

    existing = db.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.scenario_id == budget.id)
    )
    if existing and int(existing) > 0:
        return 0

    accounts = {
        a.id: a
        for a in db.scalars(select(DimAccount).where(DimAccount.is_active == True)).all()
    }

    # Pull ACTUAL categorized (non-split) rows and aggregate in Python for DB portability
    actual_rows = db.scalars(
        select(Transaction).where(
            Transaction.scenario_id == actual.id,
            Transaction.status != "void",
            Transaction.account_id.is_not(None),
            Transaction.is_split == False,  # noqa: E712
        )
    ).all()

    buckets: dict[tuple[int, int, str, int, int], dict] = defaultdict(
        lambda: {"amount": Decimal("0"), "reporting": Decimal("0"), "has_reporting": False}
    )
    for txn in actual_rows:
        key = (txn.entity_id, txn.account_id, txn.currency or "CAD", txn.txn_date.year, txn.txn_date.month)
        buckets[key]["amount"] += Decimal(txn.amount)
        if txn.amount_reporting is not None:
            buckets[key]["reporting"] += Decimal(txn.amount_reporting)
            buckets[key]["has_reporting"] = True

    created = 0
    for (entity_id, account_id, currency, year, month), totals in buckets.items():
        acct = accounts.get(account_id)
        if not acct or acct.account_type not in ("revenue", "expense"):
            continue
        day = monthrange(year, month)[1]
        txn_date = date(year, month, day)
        factor = _REVENUE_FACTOR if acct.account_type == "revenue" else _EXPENSE_FACTOR
        amount = (totals["amount"] * factor).quantize(Decimal("0.01"))
        if amount == 0:
            continue
        reporting = None
        if totals["has_reporting"]:
            reporting = (totals["reporting"] * factor).quantize(Decimal("0.01"))

        external_id = f"budget:{entity_id}:{account_id}:{year}-{month:02d}"
        fp = transaction_fingerprint(
            txn_date=txn_date,
            amount=amount,
            description=f"BUDGET {acct.code} {year}-{month:02d}",
            currency=currency,
            bank_account_id=None,
            external_id=external_id,
        )
        db.add(
            Transaction(
                external_id=external_id,
                fingerprint=fp,
                txn_date=txn_date,
                post_date=txn_date,
                description=f"Budget target · {acct.code} {acct.name}",
                memo="Auto-synthesized from ACTUAL for Budget overview",
                amount=amount,
                currency=currency,
                amount_reporting=reporting,
                entity_id=entity_id,
                bank_account_id=None,
                account_id=account_id,
                scenario_id=budget.id,
                date_key=ensure_date_dimension(db, txn_date),
                source_type="budget_seed",
                status="categorized",
                created_by="system",
                updated_by="system",
            )
        )
        created += 1

    if created:
        db.commit()
    return created
