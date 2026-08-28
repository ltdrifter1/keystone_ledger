"""Fiscal calendar — FYE is per entity (default 31 July)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

DEFAULT_FYE_MONTH = 7


def resolve_fye_month(entity=None, fye_month: int | None = None) -> int:
    if fye_month:
        return int(fye_month)
    if entity is not None:
        value = getattr(entity, "fiscal_year_end_month", None)
        if value:
            return int(value)
    return DEFAULT_FYE_MONTH


def month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def add_months_date(d: date, delta: int) -> date:
    year, month = add_months(d.year, d.month, delta)
    return date(year, month, 1)


def fiscal_year_start_for(year: int, month: int, fye_month: int = DEFAULT_FYE_MONTH) -> date:
    """First day of the fiscal year that contains year-month."""
    fye_month = int(fye_month or DEFAULT_FYE_MONTH)
    if fye_month == 12:
        return date(year, 1, 1)
    if month <= fye_month:
        return date(year - 1, fye_month + 1, 1)
    return date(year, fye_month + 1, 1)


def fiscal_year_of(d: date, fye_month: int = DEFAULT_FYE_MONTH) -> int:
    """Fiscal year labeled by the calendar year of the year-end date."""
    fye_month = int(fye_month or DEFAULT_FYE_MONTH)
    if d.month <= fye_month:
        return d.year
    return d.year + 1


def fiscal_period_of(d: date, fye_month: int = DEFAULT_FYE_MONTH) -> int:
    """1 = first month after year-end (August when FYE is July)."""
    fye_month = int(fye_month or DEFAULT_FYE_MONTH)
    start_month = 1 if fye_month == 12 else fye_month + 1
    return (d.month - start_month) % 12 + 1


def fiscal_quarter_of(d: date, fye_month: int = DEFAULT_FYE_MONTH) -> int:
    return (fiscal_period_of(d, fye_month) - 1) // 3 + 1


def fiscal_quarter_bounds(
    year: int,
    month: int,
    fye_month: int = DEFAULT_FYE_MONTH,
    quarter: Optional[int] = None,
) -> tuple[date, date]:
    """Start/end dates of the fiscal quarter containing year-month (or `quarter` 1–4)."""
    fy_start = fiscal_year_start_for(year, month, fye_month)
    if quarter:
        q = max(1, min(4, int(quarter)))
    else:
        q = fiscal_quarter_of(date(year, month, 1), fye_month)
    q_start_period = (q - 1) * 3 + 1
    start = add_months_date(fy_start, q_start_period - 1)
    end_month = add_months_date(fy_start, q_start_period + 1)
    return start, month_end(end_month.year, end_month.month)


def is_fiscal_year_end(d: date, fye_month: int = DEFAULT_FYE_MONTH) -> bool:
    return d.month == int(fye_month or DEFAULT_FYE_MONTH) and d == month_end(d.year, d.month)


def is_fiscal_quarter_end(d: date, fye_month: int = DEFAULT_FYE_MONTH) -> bool:
    if d != month_end(d.year, d.month):
        return False
    return fiscal_period_of(d, fye_month) % 3 == 0
