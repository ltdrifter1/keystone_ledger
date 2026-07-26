from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.engines.fx import translate_amount
from app.config import get_settings
from app.models import DimAccount, DimReportLayout, Transaction, TransactionSplit
from app.schemas.reports import ReportFilter, ReportLine, ReportOut


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _period_bounds(filters: ReportFilter) -> tuple[date, date]:
    today = date.today()
    year = filters.year or today.year

    if filters.period == "monthly":
        month = filters.month or today.month
        return date(year, month, 1), _month_end(year, month)

    if filters.period == "quarterly":
        q = filters.quarter or ((today.month - 1) // 3 + 1)
        start_month = (q - 1) * 3 + 1
        end_month = start_month + 2
        return date(year, start_month, 1), _month_end(year, end_month)

    if filters.period == "ytd":
        end = filters.date_to or filters.as_of_date or today
        return date(year, 1, 1), end

    # custom
    start = filters.date_from or date(year, 1, 1)
    end = filters.date_to or filters.as_of_date or today
    return start, end


def _iter_fact_lines(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    scenario_id: int,
    entity_ids: Optional[list[int]],
    department_ids: Optional[list[int]],
) -> Iterable[tuple[Transaction, int, Optional[int], Decimal]]:
    """
    Yield (source_txn, account_id, department_id, amount) fact grains.
    Split transactions explode into multiple fact lines.
    """
    q = (
        select(Transaction)
        .options(
            joinedload(Transaction.splits),
            joinedload(Transaction.bank_account),
            joinedload(Transaction.entity),
        )
        .where(
            Transaction.scenario_id == scenario_id,
            Transaction.txn_date >= date_from,
            Transaction.txn_date <= date_to,
            Transaction.status.notin_(["void", "excluded"]),
        )
    )
    if entity_ids:
        q = q.where(Transaction.entity_id.in_(entity_ids))
    if department_ids:
        # Filter parent dept OR any split dept — applied below for splits
        pass

    txns = db.scalars(q).unique().all()
    for txn in txns:
        if txn.is_split and txn.splits:
            for split in txn.splits:
                if department_ids and split.department_id not in department_ids:
                    continue
                yield txn, split.account_id, split.department_id, Decimal(split.amount)
        else:
            if txn.account_id is None:
                continue
            if department_ids and txn.department_id not in department_ids:
                continue
            yield txn, txn.account_id, txn.department_id, Decimal(txn.amount)


def aggregate_by_account(
    db: Session,
    filters: ReportFilter,
    *,
    balance_sheet: bool = False,
) -> dict[int, Decimal]:
    """Return {account_id: amount} in reporting currency."""
    settings = get_settings()
    reporting_currency = filters.reporting_currency or settings.default_reporting_currency

    if balance_sheet:
        # Cumulative through as_of
        date_from = date(2000, 1, 1)
        date_to = filters.as_of_date or filters.date_to or date.today()
    else:
        date_from, date_to = _period_bounds(filters)

    totals: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))

    for txn, account_id, _dept, amount in _iter_fact_lines(
        db,
        date_from=date_from,
        date_to=date_to,
        scenario_id=filters.scenario_id,
        entity_ids=filters.entity_ids,
        department_ids=filters.department_ids,
    ):
        translated, _ = translate_amount(
            db,
            amount=amount,
            from_currency=txn.currency,
            to_currency=reporting_currency,
            as_of=txn.txn_date,
            rate_type="average" if not balance_sheet else "closing",
        )
        totals[account_id] += translated

    return dict(totals)


def _signed_amount(account: DimAccount, amount: Decimal, report_type: str) -> Decimal:
    """Normalize bank-signed amounts into statement presentation."""
    # Bank convention: +inflow / -outflow
    # For P&L: revenue inflows positive, expenses outflows as positive expense
    if report_type == "income_statement":
        if account.account_type == "revenue":
            return amount  # inflows already positive
        if account.account_type == "expense":
            return -amount  # outflows negative → show as positive expense
        return amount
    if report_type == "balance_sheet":
        if account.normal_balance == "credit":
            return -amount
        return amount
    return amount


def build_report(db: Session, filters: ReportFilter) -> ReportOut:
    report_type = filters.report_type
    balance_sheet = report_type == "balance_sheet"
    totals = aggregate_by_account(db, filters, balance_sheet=balance_sheet)

    compare_totals: dict[int, Decimal] = {}
    if filters.compare_scenario_id:
        compare_filters = filters.model_copy(update={"scenario_id": filters.compare_scenario_id})
        compare_totals = aggregate_by_account(db, compare_filters, balance_sheet=balance_sheet)

    accounts = {a.id: a for a in db.scalars(select(DimAccount)).all()}
    layouts = list(
        db.scalars(
            select(DimReportLayout)
            .where(DimReportLayout.report_type == report_type)
            .order_by(DimReportLayout.sort_order.asc())
        )
    )

    # If no layout seeded, synthesize from accounts
    if not layouts:
        return _synthesize_report(db, filters, totals, compare_totals, accounts)

    line_amounts: dict[str, Decimal] = {}
    lines: list[ReportLine] = []
    section_refs = {"revenue": "A", "expense": "B", "asset": "C", "liability": "D", "equity": "E", "totals": "Z"}
    section_counters: dict[str, int] = defaultdict(int)

    for layout in layouts:
        amount = Decimal("0")
        drill_ids: list[int] = []
        type_filter = layout.account_type_filter

        if layout.account_id:
            raw = totals.get(layout.account_id, Decimal("0"))
            acct = accounts.get(layout.account_id)
            amount = _signed_amount(acct, raw, report_type) if acct else raw
            if layout.sign_flip:
                amount = -amount
            drill_ids = [layout.account_id]
        elif layout.account_type_filter:
            for acct_id, raw in totals.items():
                acct = accounts.get(acct_id)
                if acct and acct.account_type == layout.account_type_filter:
                    amount += _signed_amount(acct, raw, report_type)
                    drill_ids.append(acct_id)
            # Also include zero-activity accounts of that type for completeness of filter
            if not drill_ids:
                drill_ids = [a.id for a in accounts.values() if a.account_type == layout.account_type_filter]
        elif layout.calc_formula:
            amount = _eval_formula(layout.calc_formula, line_amounts)
            # Expand formula components into drillable account sets
            if layout.line_code in ("NI", "NET_INCOME") or "NET" in layout.line_label.upper():
                drill_ids = [
                    a.id for a in accounts.values() if a.account_type in ("revenue", "expense") and a.is_active
                ]
            elif layout.section in ("revenue", "expense", "asset", "liability", "equity"):
                drill_ids = [a.id for a in accounts.values() if a.account_type == layout.section and a.is_active]
                type_filter = layout.section

        line_amounts[layout.line_code] = amount

        compare_amount = None
        variance = None
        variance_pct = None
        if filters.compare_scenario_id:
            if layout.account_id:
                acct = accounts.get(layout.account_id)
                raw_c = compare_totals.get(layout.account_id, Decimal("0"))
                compare_amount = _signed_amount(acct, raw_c, report_type) if acct else raw_c
            elif layout.account_type_filter:
                compare_amount = Decimal("0")
                for acct_id, raw_c in compare_totals.items():
                    acct = accounts.get(acct_id)
                    if acct and acct.account_type == layout.account_type_filter:
                        compare_amount += _signed_amount(acct, raw_c, report_type)
            elif layout.calc_formula:
                compare_amount = None
            if compare_amount is not None:
                variance = amount - compare_amount
                if compare_amount != 0:
                    variance_pct = (variance / abs(compare_amount)) * Decimal("100")

        section_counters[layout.section] += 1
        prefix = section_refs.get(layout.section, "X")
        wp_ref = f"{prefix}.{section_counters[layout.section]}"
        drillable = bool(drill_ids)

        lines.append(
            ReportLine(
                line_code=layout.line_code,
                line_label=layout.line_label,
                section=layout.section,
                amount=amount,
                compare_amount=compare_amount,
                variance=variance,
                variance_pct=variance_pct,
                indent_level=layout.indent_level,
                is_bold=layout.is_bold,
                is_total=layout.is_total,
                account_id=layout.account_id,
                drillable=drillable,
                account_ids=drill_ids,
                account_type_filter=type_filter,
                wp_ref=wp_ref if drillable else None,
            )
        )

    title_map = {
        "income_statement": "Income Statement",
        "balance_sheet": "Balance Sheet",
        "cash_flow": "Cash Flow Statement",
    }
    return ReportOut(
        report_type=report_type,
        title=title_map.get(report_type, report_type),
        filters=filters,
        lines=lines,
        generated_at=datetime.utcnow().isoformat() + "Z",
        currency=filters.reporting_currency,
    )


def _eval_formula(formula: str, line_amounts: dict[str, Decimal]) -> Decimal:
    """
    Safe subset: LINE_A + LINE_B - LINE_C
    """
    tokens = formula.replace("(", " ").replace(")", " ").replace("+", " + ").replace("-", " - ").split()
    if not tokens:
        return Decimal("0")
    total = Decimal("0")
    op = "+"
    for tok in tokens:
        if tok in ("+", "-"):
            op = tok
            continue
        val = line_amounts.get(tok, Decimal("0"))
        total = total + val if op == "+" else total - val
    return total


def _synthesize_report(
    db: Session,
    filters: ReportFilter,
    totals: dict[int, Decimal],
    compare_totals: dict[int, Decimal],
    accounts: dict[int, DimAccount],
) -> ReportOut:
    type_order = {
        "income_statement": ["revenue", "expense"],
        "balance_sheet": ["asset", "liability", "equity"],
        "cash_flow": ["asset"],
    }
    wanted = type_order.get(filters.report_type, ["revenue", "expense", "asset", "liability", "equity"])
    lines: list[ReportLine] = []
    section_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    section_refs = {"revenue": "A", "expense": "B", "asset": "C", "liability": "D", "equity": "E", "totals": "Z"}
    section_counters: dict[str, int] = defaultdict(int)

    for acct_type in wanted:
        typed = [a for a in accounts.values() if a.account_type == acct_type and a.is_active]
        typed.sort(key=lambda a: (a.sort_order, a.code))
        typed_ids: list[int] = []
        for acct in typed:
            raw = totals.get(acct.id, Decimal("0"))
            amount = _signed_amount(acct, raw, filters.report_type)
            if amount == 0 and acct.id not in totals:
                continue
            compare_amount = None
            variance = None
            if filters.compare_scenario_id:
                raw_c = compare_totals.get(acct.id, Decimal("0"))
                compare_amount = _signed_amount(acct, raw_c, filters.report_type)
                variance = amount - compare_amount
            section_totals[acct_type] += amount
            typed_ids.append(acct.id)
            section_counters[acct_type] += 1
            lines.append(
                ReportLine(
                    line_code=acct.code,
                    line_label=acct.name,
                    section=acct_type,
                    amount=amount,
                    compare_amount=compare_amount,
                    variance=variance,
                    indent_level=1,
                    account_id=acct.id,
                    drillable=True,
                    account_ids=[acct.id],
                    wp_ref=f"{section_refs.get(acct_type, 'X')}.{section_counters[acct_type]}",
                )
            )
        if acct_type in section_totals:
            section_counters[acct_type] += 1
            lines.append(
                ReportLine(
                    line_code=f"TOT_{acct_type.upper()}",
                    line_label=f"Total {acct_type.title()}",
                    section=acct_type,
                    amount=section_totals[acct_type],
                    is_bold=True,
                    is_total=True,
                    drillable=True,
                    account_ids=typed_ids,
                    account_type_filter=acct_type,
                    wp_ref=f"{section_refs.get(acct_type, 'X')}.{section_counters[acct_type]}",
                )
            )

    if filters.report_type == "income_statement":
        ni = section_totals.get("revenue", Decimal("0")) - section_totals.get("expense", Decimal("0"))
        ni_ids = [
            a.id for a in accounts.values() if a.account_type in ("revenue", "expense") and a.is_active
        ]
        lines.append(
            ReportLine(
                line_code="NET_INCOME",
                line_label="Net Income",
                section="totals",
                amount=ni,
                is_bold=True,
                is_total=True,
                drillable=True,
                account_ids=ni_ids,
                wp_ref="Z.1",
            )
        )

    title_map = {
        "income_statement": "Income Statement",
        "balance_sheet": "Balance Sheet",
        "cash_flow": "Cash Flow Statement",
    }
    return ReportOut(
        report_type=filters.report_type,
        title=title_map.get(filters.report_type, filters.report_type),
        filters=filters,
        lines=lines,
        generated_at=datetime.utcnow().isoformat() + "Z",
        currency=filters.reporting_currency,
    )
