"""Cash WP C.1 — live bank-reconciliation workpaper from Close Pack."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.engines.close_pack import month_close_overview
from app.engines.fx import translate_amount
from app.engines.reconciliation import calculated_book_balance
from app.engines.reporting import build_report
from app.schemas.reports import ReportFilter


def _period_end(year: int, month: int):
    from calendar import monthrange
    from datetime import date

    return date(year, month, monthrange(year, month)[1])


def build_cash_recon_schedule(db: Session, year: int, month: int) -> dict:
    """
    Per-bank recon schedule for Cash WP C.1.

    Tied means every bank recon difference is zero (started packs) and
    consolidated BS cash ≈ sum of period-end bank books in reporting currency.
    """
    end = _period_end(year, month)
    close = month_close_overview(db, year, month)
    reporting_currency = "CAD"

    banks = []
    banks_tied = 0
    banks_locked = 0
    banks_ready_or_locked = 0
    book_reporting_total = Decimal("0")
    statement_reporting_total = Decimal("0")
    currencies: set[str] = set()

    for pack in close["packs"]:
        bank_id = pack["bank_account_id"]
        currency = pack.get("currency") or "CAD"
        currencies.add(currency)
        status = pack.get("status") or "not_started"
        is_locked = bool(pack.get("is_locked"))
        can_lock = bool(pack.get("can_lock"))
        diff = pack.get("difference")
        stmt = pack.get("statement_ending_balance")
        book_cleared = pack.get("calculated_balance")
        beg = pack.get("beginning_balance") or 0.0
        uncleared = int(pack.get("uncleared_count") or 0)
        blocking = int(pack.get("blocking_count") or 0)

        book_native = calculated_book_balance(db, bank_id, end)
        book_reporting, _ = translate_amount(
            db,
            amount=book_native,
            from_currency=currency,
            to_currency=reporting_currency,
            as_of=end,
            rate_type="closing",
        )
        book_reporting_total += book_reporting

        stmt_reporting = None
        if stmt is not None:
            stmt_reporting, _ = translate_amount(
                db,
                amount=Decimal(str(stmt)),
                from_currency=currency,
                to_currency=reporting_currency,
                as_of=end,
                rate_type="closing",
            )
            statement_reporting_total += stmt_reporting

        bank_tied = status != "not_started" and diff is not None and abs(float(diff)) < 0.01
        if bank_tied:
            banks_tied += 1
        if is_locked:
            banks_locked += 1
        if is_locked or can_lock:
            banks_ready_or_locked += 1

        # PRIOR / aged uncleared from exceptions
        prior_count = 0
        aged_messages: list[str] = []
        for ex in pack.get("exceptions") or []:
            if not ex.get("in_period") and ex.get("kind") in ("difference", "uncleared", "uncategorized"):
                prior_count += 1
                if len(aged_messages) < 3:
                    aged_messages.append(
                        f"{ex.get('txn_date')} {ex.get('description')} ({ex.get('amount')})"
                    )

        banks.append(
            {
                "bank_account_id": bank_id,
                "bank_account_name": pack.get("bank_account_name"),
                "entity_code": pack.get("entity_code"),
                "currency": currency,
                "reconciliation_id": pack.get("reconciliation_id"),
                "status": status,
                "beginning_balance": float(beg),
                "book_balance": float(book_native),
                "book_balance_reporting": float(book_reporting),
                "book_cleared": float(book_cleared) if book_cleared is not None else None,
                "statement_ending_balance": float(stmt) if stmt is not None else None,
                "statement_reporting": float(stmt_reporting) if stmt_reporting is not None else None,
                "difference": float(diff) if diff is not None else None,
                "uncleared_count": uncleared,
                "blocking_count": blocking,
                "prior_item_count": prior_count,
                "prior_samples": aged_messages,
                "can_lock": can_lock,
                "is_locked": is_locked,
                "is_tied": bank_tied,
                "href": (
                    f"/close?year={year}&month={month}&bank={bank_id}"
                    f"{'&mode=exceptions' if blocking else '&mode=items&filter=uncleared'}"
                ),
            }
        )

    # BS cash lead
    bs = build_report(
        db,
        ReportFilter(
            report_type="balance_sheet",
            as_of_date=end,
            year=year,
            month=month,
            scenario_id=1,
            reporting_currency=reporting_currency,
            consolidate=True,
        ),
    )
    gl_line = next((l for l in bs.lines if l.line_code == "BS_CASH"), None)
    if not gl_line:
        gl_line = next((l for l in bs.lines if l.line_code == "1000"), None)
    gl_amount = Decimal(gl_line.amount) if gl_line else Decimal("0")
    gl_vs_books = gl_amount - book_reporting_total

    banks_total = len(banks)
    all_started = banks_total > 0 and all(b["status"] != "not_started" for b in banks)
    all_bank_tied = banks_total > 0 and banks_tied == banks_total
    all_locked = banks_total > 0 and banks_locked == banks_total
    all_ready_or_locked = banks_total > 0 and banks_ready_or_locked == banks_total
    gl_agrees = abs(gl_vs_books) < Decimal("0.02")

    is_tied = all_bank_tied and gl_agrees
    can_prepare = all_ready_or_locked and all_bank_tied and gl_agrees
    can_review = all_locked and all_bank_tied and gl_agrees

    gate_messages: list[str] = []
    if not all_started:
        not_started = [b["bank_account_name"] for b in banks if b["status"] == "not_started"]
        gate_messages.append(f"Start recon for: {', '.join(str(n) for n in not_started)}")
    untied_banks = [b["bank_account_name"] for b in banks if not b["is_tied"] and b["status"] != "not_started"]
    if untied_banks:
        gate_messages.append(f"Difference still open: {', '.join(str(n) for n in untied_banks)}")
    if all_started and not all_ready_or_locked:
        gate_messages.append("Resolve blocking exceptions so every bank is ready to lock")
    if not gl_agrees:
        gate_messages.append(
            f"BS cash ({float(gl_amount):,.2f} {reporting_currency}) ≠ sum of bank books "
            f"({float(book_reporting_total):,.2f} {reporting_currency})"
        )
    if can_prepare and not can_review:
        gate_messages.append("Lock all bank recons before review sign-off")

    # Auto-check cash procedures when recon evidence supports them
    auto_checked: list[int] = []
    if all_started:
        auto_checked.append(0)  # pulled balances
        auto_checked.append(1)  # statement ending obtained (started packs)
    if all_bank_tied and all_ready_or_locked:
        auto_checked.extend([2, 3])  # recon complete + uncleared investigated
    if len(currencies) == 1 or all_started:
        auto_checked.append(4)  # FX noted (single ccy or packs run with reporting)
    if is_tied and all_ready_or_locked:
        auto_checked.append(5)  # agrees to BS + close status

    return {
        "period_year": year,
        "period_month": month,
        "period_label": f"{year}-{month:02d}",
        "period_end": end.isoformat(),
        "reporting_currency": reporting_currency,
        "banks": banks,
        "gl_statement_amount": float(gl_amount),
        "banks_book_reporting_total": float(book_reporting_total),
        "banks_statement_reporting_total": float(statement_reporting_total),
        "gl_vs_books_difference": float(gl_vs_books),
        "banks_total": banks_total,
        "banks_tied": banks_tied,
        "banks_locked": banks_locked,
        "banks_ready_or_locked": banks_ready_or_locked,
        "all_started": all_started,
        "all_bank_tied": all_bank_tied,
        "all_locked": all_locked,
        "all_ready_or_locked": all_ready_or_locked,
        "gl_agrees": gl_agrees,
        "is_tied": is_tied,
        "can_prepare": can_prepare,
        "can_review": can_review,
        "gate_messages": gate_messages,
        "auto_checked": sorted(set(auto_checked)),
        "close_status": (
            "locked" if all_locked else ("ready" if all_ready_or_locked and all_bank_tied else "in_progress")
        ),
    }


def cash_signoff_allowed(
    schedule: dict,
    *,
    status: str,
    preparer: str | None,
    reviewer: str | None,
) -> None:
    """Raise ValueError if cash prepare/review gates fail."""
    if status == "prepared":
        if not schedule["can_prepare"]:
            msgs = schedule.get("gate_messages") or ["Cash recon is not ready to prepare"]
            raise ValueError("Cannot prepare Cash WP: " + "; ".join(msgs))
    if status == "reviewed":
        if not schedule["can_review"]:
            msgs = schedule.get("gate_messages") or ["Cash recon is not ready to review"]
            raise ValueError("Cannot review Cash WP: " + "; ".join(msgs))
        prep = (preparer or "").strip().upper()
        rev = (reviewer or "").strip().upper()
        if prep and rev and prep == rev:
            raise ValueError("Cannot review Cash WP: preparer and reviewer must be different")
