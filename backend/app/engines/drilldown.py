"""CaseWare-style working-paper drill: report line → source fact transactions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.engines.fx import translate_amount
from app.engines.reporting import (
    _iter_fact_lines,
    _period_bounds,
    _signed_amount,
    build_report,
)
from app.models import DimAccount, DimEntity, DimReportLayout
from app.schemas.reports import DrillLine, DrillOut, DrillRequest, ReportFilter


def _period_label(filters: ReportFilter) -> str:
    if filters.report_type == "balance_sheet":
        as_of = filters.as_of_date or filters.date_to
        return f"As of {as_of.isoformat()}" if as_of else "As of today"

    start, end = _period_bounds(filters)
    if filters.period == "monthly":
        return start.strftime("%b %Y")
    if filters.period == "quarterly":
        q = filters.quarter or ((start.month - 1) // 3 + 1)
        return f"Q{q} {start.year}"
    if filters.period == "ytd":
        return f"YTD {start.year} · through {end.isoformat()}"
    return f"{start.isoformat()} → {end.isoformat()}"


def _resolve_accounts(
    db: Session,
    *,
    filters: ReportFilter,
    line_code: str,
    account_id: int | None,
    account_ids: list[int] | None,
    account_type_filter: str | None,
) -> tuple[str, list[int], str | None, str | None]:
    """Return (line_label, account_ids, account_type_filter, wp_ref)."""
    accounts = {a.id: a for a in db.scalars(select(DimAccount)).all()}

    if account_ids:
        labels = [accounts[i].name for i in account_ids if i in accounts]
        label = labels[0] if len(labels) == 1 else f"{len(account_ids)} accounts"
        return label, account_ids, account_type_filter, None
    if account_id:
        acct = accounts.get(account_id)
        return (acct.name if acct else f"Account {account_id}", [account_id], None, None)
    if account_type_filter:
        ids = [a.id for a in accounts.values() if a.account_type == account_type_filter and a.is_active]
        return f"Total {account_type_filter.title()}", ids, account_type_filter, None

    report = build_report(db, filters)
    match = next((line for line in report.lines if line.line_code == line_code), None)
    if match:
        if match.account_ids:
            return match.line_label, list(match.account_ids), match.account_type_filter, match.wp_ref
        if match.account_id:
            return match.line_label, [match.account_id], None, match.wp_ref
        if match.account_type_filter:
            ids = [a.id for a in accounts.values() if a.account_type == match.account_type_filter and a.is_active]
            return match.line_label, ids, match.account_type_filter, match.wp_ref
        if match.line_code in ("NET_INCOME", "NI") or (
            match.is_total and match.section == "totals"
        ):
            ids = [a.id for a in accounts.values() if a.account_type in ("revenue", "expense") and a.is_active]
            return match.line_label, ids, None, match.wp_ref
        return match.line_label, [], None, match.wp_ref

    layout = db.scalar(
        select(DimReportLayout).where(
            DimReportLayout.report_type == filters.report_type,
            DimReportLayout.line_code == line_code,
        )
    )
    if layout:
        if layout.account_id:
            return layout.line_label, [layout.account_id], None, None
        if layout.account_type_filter:
            ids = [a.id for a in accounts.values() if a.account_type == layout.account_type_filter and a.is_active]
            return layout.line_label, ids, layout.account_type_filter, None

    raise ValueError(f"Line '{line_code}' is not drillable")


def drill_report_line(db: Session, payload: DrillRequest) -> DrillOut:
    settings = get_settings()
    filters = payload.filters
    reporting_currency = filters.reporting_currency or settings.default_reporting_currency
    balance_sheet = filters.report_type == "balance_sheet"

    line_label, account_ids, type_filter, wp_ref = _resolve_accounts(
        db,
        filters=filters,
        line_code=payload.line_code,
        account_id=payload.account_id,
        account_ids=payload.account_ids,
        account_type_filter=payload.account_type_filter,
    )
    if not account_ids:
        raise ValueError(f"Line '{payload.line_code}' has no underlying accounts to drill")

    account_id_set = set(account_ids)
    accounts = {a.id: a for a in db.scalars(select(DimAccount)).all()}
    entities = {e.id: e for e in db.scalars(select(DimEntity)).all()}

    if balance_sheet:
        date_from = date(2000, 1, 1)
        date_to = filters.as_of_date or filters.date_to or date.today()
    else:
        date_from, date_to = _period_bounds(filters)

    report = build_report(db, filters)
    report_line = next((line for line in report.lines if line.line_code == payload.line_code), None)
    statement_amount = report_line.amount if report_line else Decimal("0")
    if report_line:
        line_label = report_line.line_label
        wp_ref = wp_ref or report_line.wp_ref

    detail: list[DrillLine] = []
    detail_total = Decimal("0")
    is_net_income_line = payload.line_code in ("NI", "NET_INCOME") or (
        report_line is not None
        and report_line.is_total
        and report_line.section == "totals"
        and "NET" in report_line.line_label.upper()
    )

    for txn, account_id, _dept, amount in _iter_fact_lines(
        db,
        date_from=date_from,
        date_to=date_to,
        scenario_id=filters.scenario_id,
        entity_ids=filters.entity_ids,
        department_ids=filters.department_ids,
    ):
        if account_id not in account_id_set:
            continue
        acct = accounts.get(account_id)
        if not acct:
            continue
        if type_filter and acct.account_type != type_filter:
            continue

        reporting_amt, _ = translate_amount(
            db,
            amount=amount,
            from_currency=txn.currency,
            to_currency=reporting_currency,
            as_of=txn.txn_date,
            rate_type="average" if not balance_sheet else "closing",
        )
        # Net income WP uses economic contribution (bank-signed).
        # Other IS lines use statement presentation (expenses positive).
        if is_net_income_line and filters.report_type == "income_statement":
            signed = reporting_amt
        else:
            signed = _signed_amount(acct, reporting_amt, filters.report_type)
        detail_total += signed

        split_memo = None
        if txn.is_split:
            for split in txn.splits:
                if split.account_id == account_id and Decimal(split.amount) == amount:
                    split_memo = split.memo
                    break

        ent = entities.get(txn.entity_id)
        detail.append(
            DrillLine(
                transaction_id=txn.id,
                txn_date=txn.txn_date,
                description=txn.description,
                entity_id=txn.entity_id,
                entity_code=ent.code if ent else (txn.entity.code if txn.entity else None),
                bank_account_name=txn.bank_account.name if txn.bank_account else None,
                account_id=account_id,
                account_code=acct.code,
                account_name=acct.name,
                department_id=txn.department_id,
                native_amount=amount,
                currency=txn.currency,
                reporting_amount=reporting_amt,
                signed_amount=signed,
                is_split=txn.is_split,
                split_memo=split_memo,
                status=txn.status,
                is_reconciled=txn.is_reconciled,
            )
        )

    detail.sort(key=lambda row: (row.txn_date, row.transaction_id, row.account_code))
    difference = statement_amount - detail_total
    is_tied = abs(difference) < Decimal("0.02")

    return DrillOut(
        line_code=payload.line_code,
        line_label=line_label,
        wp_ref=wp_ref,
        report_type=filters.report_type,
        currency=reporting_currency,
        filters=filters,
        period_label=_period_label(filters),
        statement_amount=statement_amount,
        detail_total=detail_total,
        difference=difference,
        is_tied=is_tied,
        row_count=len(detail),
        lines=detail,
        generated_at=datetime.utcnow().isoformat() + "Z",
    )
