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
