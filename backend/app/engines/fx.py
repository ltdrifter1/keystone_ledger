from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DimFx


def get_rate(
    db: Session,
    *,
    from_currency: str,
    to_currency: str,
    as_of: date,
    rate_type: str = "spot",
) -> Decimal:
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

    # Try inverse
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

    return Decimal("1")  # fallback identity — visible in UI as missing FX


def translate_amount(
    db: Session,
    *,
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    as_of: date,
    rate_type: str = "spot",
) -> tuple[Decimal, Decimal]:
    rate = get_rate(
        db,
        from_currency=from_currency,
        to_currency=to_currency,
        as_of=as_of,
        rate_type=rate_type,
    )
    return (amount * rate, rate)


def fx_exposure_by_currency(
    db: Session,
    amounts_by_currency: dict[str, Decimal],
    reporting_currency: str,
    as_of: date,
) -> list[dict]:
    rows = []
    for currency, native in amounts_by_currency.items():
        reporting, rate = translate_amount(
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
                "reporting_balance": float(reporting),
                "rate": float(rate),
                "reporting_currency": reporting_currency,
            }
        )
    return rows
