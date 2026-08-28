from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DimFx


@dataclass(frozen=True)
class FxTranslation:
    amount: Decimal
    rate: Decimal
    missing: bool = False

    def __iter__(self):
        yield self.amount
        yield self.rate


def lookup_rate(
    db: Session,
    *,
    from_currency: str,
    to_currency: str,
    as_of: date,
    rate_type: str = "spot",
) -> Optional[Decimal]:
    """Return the FX rate, or None when no pair exists (do not assume 1)."""
    if from_currency == to_currency:
        return Decimal("1")

    rate = db.scalar(
        select(DimFx)
        .where(
            DimFx.from_currency == from_currency,
            DimFx.to_currency == to_currency,
            DimFx.rate_type == rate_type,
            DimFx.rate_date <= as_of,
        )
        .order_by(DimFx.rate_date.desc())
        .limit(1)
    )
    if rate:
        return Decimal(rate.rate)

    inv = db.scalar(
        select(DimFx)
        .where(
            DimFx.from_currency == to_currency,
            DimFx.to_currency == from_currency,
            DimFx.rate_type == rate_type,
            DimFx.rate_date <= as_of,
        )
        .order_by(DimFx.rate_date.desc())
        .limit(1)
    )
    if inv and Decimal(inv.rate) != 0:
        return Decimal("1") / Decimal(inv.rate)

    return None


def get_rate(
    db: Session,
    *,
    from_currency: str,
    to_currency: str,
    as_of: date,
    rate_type: str = "spot",
) -> Decimal:
    rate = lookup_rate(
        db,
        from_currency=from_currency,
        to_currency=to_currency,
        as_of=as_of,
        rate_type=rate_type,
    )
    return rate if rate is not None else Decimal("1")


def translate_amount(
    db: Session,
    *,
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    as_of: date,
    rate_type: str = "spot",
) -> FxTranslation:
    if from_currency == to_currency:
        return FxTranslation(amount, Decimal("1"), False)
    rate = lookup_rate(
        db,
        from_currency=from_currency,
        to_currency=to_currency,
        as_of=as_of,
        rate_type=rate_type,
    )
    if rate is None:
        # Leave native; callers must surface fx_missing rather than silently using 1.
        return FxTranslation(amount, Decimal("1"), True)
    return FxTranslation(amount * rate, rate, False)


def persistable_fx(translated: FxTranslation) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Store rate+reporting only when a pair exists. Never persist a silent 1:1."""
    if translated.missing:
        return None, None
    return translated.amount, translated.rate


def inbox_fx_status(
    db: Session,
    *,
    entity_id: int,
    year: int,
    month: int,
) -> dict:
    """Closing for BS/cash/IC, average for P&L — missing pairs stay missing."""
    from calendar import monthrange

    from app.models import BankAccount, DimEntity, Transaction

    entity = db.get(DimEntity, entity_id)
    if not entity:
        raise ValueError("Entity not found")
    as_of = date(year, month, monthrange(year, month)[1])
    functional = entity.functional_currency
    currencies: set[str] = {functional}
    for bank in db.scalars(select(BankAccount).where(BankAccount.entity_id == entity_id)):
        if bank.currency:
            currencies.add(bank.currency)
    start = date(year, month, 1)
    txn_ccy = db.scalars(
        select(Transaction.currency)
        .where(
            Transaction.entity_id == entity_id,
            Transaction.txn_date >= start,
            Transaction.txn_date <= as_of,
            Transaction.status != "void",
        )
        .distinct()
    )
    currencies.update(c for c in txn_ccy if c)

    pairs = []
    missing_pairs: list[str] = []
    for ccy in sorted(currencies):
        if ccy == functional:
            continue
        for rate_type, used_for in (("closing", "BS / cash / IC"), ("average", "P&L")):
            rate = lookup_rate(
                db,
                from_currency=ccy,
                to_currency=functional,
                as_of=as_of,
                rate_type=rate_type,
            )
            row = db.scalar(
                select(DimFx)
                .where(
                    DimFx.from_currency == ccy,
                    DimFx.to_currency == functional,
                    DimFx.rate_type == rate_type,
                    DimFx.rate_date <= as_of,
                )
                .order_by(DimFx.rate_date.desc())
                .limit(1)
            )
            missing = rate is None
            label = f"{ccy}→{functional} {rate_type}"
            if missing:
                missing_pairs.append(label)
            pairs.append(
                {
                    "from_currency": ccy,
                    "to_currency": functional,
                    "rate_type": rate_type,
                    "rate": str(rate) if rate is not None else None,
                    "rate_date": row.rate_date.isoformat() if row else None,
                    "missing": missing,
                    "used_for": used_for,
                }
            )

    inbox_missing = 0
    txns = list(
        db.scalars(
            select(Transaction).where(
                Transaction.entity_id == entity_id,
                Transaction.txn_date >= start,
                Transaction.txn_date <= as_of,
                Transaction.status == "uncategorized",
            )
        )
    )
    for txn in txns:
        if txn.currency == functional:
            continue
        if lookup_rate(
            db,
            from_currency=txn.currency,
            to_currency=functional,
            as_of=txn.txn_date,
            rate_type="closing",
        ) is None:
            inbox_missing += 1

    return {
        "entity_id": entity_id,
        "entity_code": entity.code,
        "functional_currency": functional,
        "as_of": as_of.isoformat(),
        "pairs": pairs,
        "missing_pairs": missing_pairs,
        "inbox_missing_count": inbox_missing,
        "can_print": len(missing_pairs) == 0,
    }


def fx_exposure_by_currency(
    db: Session,
    amounts_by_currency: dict[str, Decimal],
    reporting_currency: str,
    as_of: date,
) -> list[dict]:
    rows = []
    for currency, native in amounts_by_currency.items():
        translated = translate_amount(
            db,
            amount=native,
            from_currency=currency,
            to_currency=reporting_currency,
            as_of=as_of,
        )
        rows.append(
            {
                "currency": currency,
                "native_balance": float(native),
                "reporting_balance": float(translated.amount),
                "rate": float(translated.rate),
                "reporting_currency": reporting_currency,
                "rate_missing": translated.missing,
            }
        )
    return rows
