"""Official simple reporting pack: one entity, P&L + BS + equity roll + TB + notes."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines.entity_close import is_journal_led_entity
from app.engines.ledger import SUSPENSE_CODE, aggregate_ledger
from app.engines.reporting import (
    CASH_LINE_CODE,
    CURRENT_EARNINGS_CODE,
    EQUITY_CODE,
    NIL_TOLERANCE,
    _as_of_date,
    build_report,
    fiscal_year_start,
    period_label,
    prior_year_filters,
)
from app.models import DimAccount, DimEntity, DimReportLayout, Transaction
from app.schemas.reports import (
    ReportFilter,
    ReportLine,
    ReportOut,
    ReportingNote,
    StatementDiagnostics,
    StatementPlug,
    TrialBalanceOut,
    TrialBalanceRow,
)

SCOPE_ERROR = (
    "Select one entity. WBC CAN and WBC USA stay separate — this pack does not "
    "consolidate or eliminate intercompany."
)
PACK_DISCLAIMER = "Unaudited — management pack. Not a cash flow statement and not a group consolidation."


def assert_statement_scope(db: Session, filters: ReportFilter) -> int:
    ids = list(filters.entity_ids or [])
    if len(ids) > 1:
        raise ValueError(SCOPE_ERROR)
    if len(ids) == 1:
        return ids[0]
    entities = list(db.scalars(select(DimEntity)).all())
    if len(entities) != 1:
        raise ValueError(SCOPE_ERROR)
    if not entities:
        raise ValueError("No entity in this file.")
    return entities[0].id


def _entity(db: Session, entity_id: int) -> DimEntity:
    row = db.get(DimEntity, entity_id)
    if not row:
        raise ValueError("Entity not found")
    return row


def scoped_statement_filters(db: Session, filters: ReportFilter) -> ReportFilter:
    entity_id = assert_statement_scope(db, filters)
    entity = _entity(db, entity_id)
    return filters.model_copy(
        update={
            "entity_ids": [entity_id],
            "consolidate": False,
            "reporting_currency": entity.functional_currency or filters.reporting_currency,
        }
    )


def budget_is_illustrative(db: Session) -> bool:
    row = db.scalar(
        select(Transaction.id).where(Transaction.source_type == "budget_seed").limit(1)
    )
    return row is not None


def build_reporting_notes(db: Session, filters: ReportFilter) -> tuple[str, list[ReportingNote], str]:
    entity_id = assert_statement_scope(db, filters)
    entity = _entity(db, entity_id)
    year = filters.year or (_as_of_date(filters).year)
    as_of = _as_of_date(filters)
    fy_start = fiscal_year_start(year, filters.month or as_of.month)
    basis = (
        f"{entity.name} is a double-entry ledger. Bank activity posts to the cash GL and the "
        "other side (uncategorized items to 9999 suspense). Current earnings are not closed "
        "to retained earnings."
    )
    basis_heading = "Double-entry ledger"
    notes = [
        ReportingNote(heading=basis_heading, body=basis),
        ReportingNote(
            heading="Fiscal year",
            body=(
                f"Year-end is 31 July (FYE month {int(getattr(entity, 'fiscal_year_end_month', None) or 7)}). "
                f"Fiscal YTD for this pack runs from {fy_start.isoformat()} through {as_of.isoformat()}. "
                "Quarters are fiscal (Q1 starts 1 August)."
            ),
        ),
        ReportingNote(
            heading="Foreign exchange",
            body=(
                f"Amounts are in {filters.reporting_currency}. "
                "P&L uses average rates; the balance sheet and bank book use closing rates. "
                "Missing pairs are flagged — amounts are not translated 1:1."
            ),
        ),
        ReportingNote(
            heading="Intercompany",
            body=(
                "Due to / from intercompany is presented on its own line. "
                "Trade AR/AP exclude IC legs. CAN and USA are not combined and IC is not eliminated."
            ),
        ),
        ReportingNote(
            heading="Unaudited",
            body=PACK_DISCLAIMER,
        ),
    ]
    return basis_heading, notes, PACK_DISCLAIMER


def _layout_account_map(db: Session) -> dict[int, tuple[str, str]]:
    """account_id → (line_code, line_label); specific mappings win over type filters."""
    accounts = {a.id: a for a in db.scalars(select(DimAccount)).all()}
    layouts = list(db.scalars(select(DimReportLayout)).all())
    by_type: dict[str, tuple[str, str]] = {}
    by_id: dict[int, tuple[str, str]] = {}
    for layout in layouts:
        if layout.report_type not in ("income_statement", "balance_sheet"):
            continue
        if layout.is_total or not layout.line_code:
            continue
        if layout.account_id:
            by_id[layout.account_id] = (layout.line_code, layout.line_label)
        elif layout.account_type_filter:
            by_type[layout.account_type_filter] = (layout.line_code, layout.line_label)
    mapped: dict[int, tuple[str, str]] = {}
    for acct in accounts.values():
        if acct.id in by_id:
            mapped[acct.id] = by_id[acct.id]
        elif acct.is_cash:
            mapped[acct.id] = (CASH_LINE_CODE, "Cash")
        elif acct.account_type in by_type:
            mapped[acct.id] = by_type[acct.account_type]
    return mapped


def _dr_cr(account: DimAccount, amount: Decimal) -> tuple[Decimal, Decimal]:
    if account.account_type in ("asset", "expense"):
        if amount >= 0:
            return amount, Decimal("0")
        return Decimal("0"), -amount
    if amount >= 0:
        return Decimal("0"), amount
    return -amount, Decimal("0")


def _uncategorized(db: Session, filters: ReportFilter, entity_id: int) -> tuple[int, Decimal]:
    as_of = _as_of_date(filters)
    q = select(Transaction).where(
        Transaction.entity_id == entity_id,
        Transaction.scenario_id == filters.scenario_id,
        Transaction.txn_date <= as_of,
        Transaction.status.notin_(["void", "excluded"]),
    )
    count = 0
    total = Decimal("0")
    for txn in db.scalars(q).all():
        if txn.account_id is None or txn.status == "uncategorized":
            if txn.is_split and txn.splits:
                continue
            count += 1
            total += Decimal(txn.amount)
    return count, total


def _cashbook_journals(db: Session, filters: ReportFilter, entity_id: int) -> int:
    if is_journal_led_entity(db, entity_id):
        return 0
    as_of = _as_of_date(filters)
    n = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(
            Transaction.entity_id == entity_id,
            Transaction.scenario_id == filters.scenario_id,
            Transaction.source_type.in_(("journal", "post_close_adj")),
            Transaction.status.notin_(["void", "excluded"]),
            Transaction.txn_date <= as_of,
        )
    )
    return int(n or 0)


def attach_pack_notes(db: Session, filters: ReportFilter, report: ReportOut) -> ReportOut:
    basis, notes, disclaimer = build_reporting_notes(db, filters)
    report.accounting_basis = basis
    report.notes = notes
    report.pack_disclaimer = disclaimer
    return report


def build_official_report(db: Session, filters: ReportFilter) -> ReportOut:
    filters = scoped_statement_filters(db, filters)
    if filters.report_type == "cash_flow":
        raise ValueError("Cash flow is not part of this pack. Print P&L, the balance sheet, and the equity roll.")
    if filters.report_type == "trial_balance":
        raise ValueError("Use the trial-balance endpoint for the mapped trial balance.")
    if filters.report_type == "equity":
        report = build_equity_roll(db, filters)
    else:
        report = build_report(db, filters)
    return attach_pack_notes(db, filters, report)


def build_equity_roll(db: Session, filters: ReportFilter) -> ReportOut:
    """Opening equity + draws + current earnings = closing equity."""
    entity_id = assert_statement_scope(db, filters)
    as_of = _as_of_date(filters)
    year = filters.year or as_of.year
    month = filters.month or as_of.month
    bs_filters = filters.model_copy(
        update={
            "report_type": "balance_sheet",
            "year": year,
            "month": month,
            "as_of_date": as_of,
            "date_to": as_of,
            "compare_prior_year": True,
            "compare_prior_period": False,
            "compare_budget": False,
            "entity_ids": [entity_id],
            "consolidate": False,
        }
    )
    bs = build_report(db, bs_filters)
    by_code = {line.line_code: line for line in bs.lines}

    def _copy(code: str, fallback_label: str, section: str, *, total: bool = False) -> ReportLine:
        src = by_code.get(code)
        if src:
            return ReportLine(
                line_code=code if code != EQUITY_CODE else "EQ_OPENING",
                line_label=src.line_label if code != EQUITY_CODE else "Opening equity",
                section=section,
                amount=src.amount,
                prior_year_amount=src.prior_year_amount,
                prior_year_variance=(src.amount - src.prior_year_amount) if src.prior_year_amount is not None else None,
                indent_level=0 if total else 1,
                is_bold=total or src.is_bold,
                is_total=total,
                drillable=src.drillable,
                account_id=src.account_id,
                account_ids=list(src.account_ids or []),
                wp_ref="E.1",
            )
        return ReportLine(
            line_code=code,
            line_label=fallback_label,
            section=section,
            amount=Decimal("0"),
            indent_level=1,
            wp_ref="E.1",
        )

    opening = _copy(EQUITY_CODE, "Opening equity", "equity")
    opening.line_code = "EQ_OPENING"
    opening.line_label = "Opening equity"
    draws = _copy("BS_DRAWS", "Owner contributions / draws", "equity")
    draws.line_code = "EQ_DRAWS"
    earnings = _copy(CURRENT_EARNINGS_CODE, "Current earnings", "equity")
    earnings.line_code = "EQ_EARNINGS"
    closing_amt = opening.amount + draws.amount + earnings.amount
    tot = by_code.get("BS_TOT_EQUITY")
    if tot:
        closing_amt = tot.amount
        prior_close = tot.prior_year_amount
    else:
        prior_close = None
        if opening.prior_year_amount is not None:
            prior_close = (
                (opening.prior_year_amount or Decimal("0"))
                + (draws.prior_year_amount or Decimal("0"))
                + (earnings.prior_year_amount or Decimal("0"))
            )
    closing = ReportLine(
        line_code="EQ_CLOSING",
        line_label="Closing equity",
        section="equity",
        amount=closing_amt,
        prior_year_amount=prior_close,
        prior_year_variance=(closing_amt - prior_close) if prior_close is not None else None,
        is_bold=True,
        is_total=True,
        drillable=True,
        account_ids=list(earnings.account_ids or []) + list(opening.account_ids or []),
        wp_ref="E.1",
    )
    eq_filters = bs_filters.model_copy(update={"report_type": "equity", "period": "ytd"})
    report = ReportOut(
        report_type="equity",
        title="Statement of Changes in Equity",
        filters=eq_filters,
        lines=[opening, draws, earnings, closing],
        generated_at=datetime.utcnow().isoformat() + "Z",
        currency=filters.reporting_currency,
        period_label=f"Fiscal YTD ended {as_of.day} {as_of.strftime('%B %Y')}",
        prior_year_label=period_label(prior_year_filters(eq_filters)),
        columns=["amount", "prior_year"],
        cover_title=None,
        entity_name=bs.entity_name,
        is_balanced=bs.is_balanced,
        balance_difference=bs.balance_difference,
        fx_missing=bs.fx_missing,
        fx_missing_pairs=list(bs.fx_missing_pairs or []),
    )
    report.cover_title = (
        f"{bs.entity_name} · {report.title} · {report.period_label} · {report.currency}"
    )
    return report


def build_trial_balance(db: Session, filters: ReportFilter) -> TrialBalanceOut:
    scoped = scoped_statement_filters(db, filters)
    entity_id = scoped.entity_ids[0]
    entity = _entity(db, entity_id)
    as_of = _as_of_date(scoped)
    period_start = date(as_of.year, as_of.month, 1)
    opening_end = period_start - timedelta(days=1)
    currency = scoped.reporting_currency
    accounts = {a.id: a for a in db.scalars(select(DimAccount).where(DimAccount.is_active.is_(True))).all()}
    mapping = _layout_account_map(db)

    common = dict(
        scenario_id=scoped.scenario_id,
        entity_ids=[entity_id],
        department_ids=scoped.department_ids,
        reporting_currency=currency,
        rate_type="closing",
        ic_predicate=None,
    )
    opening = aggregate_ledger(
        db, date_from=date(2000, 1, 1), date_to=opening_end, include_openings=True, **common
    )
    period = aggregate_ledger(
        db, date_from=period_start, date_to=as_of, include_openings=False, **common
    )
    closing = aggregate_ledger(
        db, date_from=date(2000, 1, 1), date_to=as_of, include_openings=True, **common
    )

    rows: list[TrialBalanceRow] = []
    for acct in sorted(accounts.values(), key=lambda a: (a.sort_order, a.code)):
        o = opening.by_account.get(acct.id)
        p = period.by_account.get(acct.id)
        c = closing.by_account.get(acct.id)
        od, oc = (o.debit if o else Decimal("0")), (o.credit if o else Decimal("0"))
        pd, pc = (p.debit if p else Decimal("0")), (p.credit if p else Decimal("0"))
        cd, cc = (c.debit if c else Decimal("0")), (c.credit if c else Decimal("0"))
        net = cd - cc
        mapped = acct.id in mapping
        line_code, line_label = mapping.get(acct.id, (None, None))
        if (
            abs(od) <= NIL_TOLERANCE
            and abs(oc) <= NIL_TOLERANCE
            and abs(pd) <= NIL_TOLERANCE
            and abs(pc) <= NIL_TOLERANCE
            and abs(cd) <= NIL_TOLERANCE
            and abs(cc) <= NIL_TOLERANCE
            and not mapped
        ):
            continue
        exception = None if mapped else "Unmapped — will not hit P&L or BS"
        if acct.code == SUSPENSE_CODE and (abs(cd) > NIL_TOLERANCE or abs(cc) > NIL_TOLERANCE):
            exception = "Uncategorized activity — recode before issuing the pack"
        rows.append(
            TrialBalanceRow(
                account_id=acct.id,
                account_code=acct.code,
                account_name=acct.name,
                account_type=acct.account_type,
                statement=acct.statement,
                line_code=line_code,
                line_label=line_label,
                mapped=mapped,
                opening_debit=od,
                opening_credit=oc,
                period_debit=pd,
                period_credit=pc,
                debit=cd,
                credit=cc,
                amount=net,
                exception=exception,
            )
        )

    uncat_n, uncat_amt = _uncategorized(db, scoped, entity_id)
    unmapped = [r for r in rows if not r.mapped]
    total_debit = sum((r.debit for r in rows), Decimal("0"))
    total_credit = sum((r.credit for r in rows), Decimal("0"))
    difference = total_debit - total_credit
    is_balanced = abs(difference) < Decimal("0.02")
    basis, notes, _disc = build_reporting_notes(db, scoped)
    complete = uncat_n == 0 and len(unmapped) == 0 and is_balanced
    return TrialBalanceOut(
        title="Trial Balance",
        cover_title=(
            f"{entity.name} · Trial Balance · As at {as_of.day} {as_of.strftime('%B %Y')} · {currency}"
        ),
        entity_name=entity.name,
        period_label=f"As at {as_of.day} {as_of.strftime('%B %Y')}",
        currency=currency,
        as_of_date=as_of,
        accounting_basis=basis,
        rows=rows,
        total_debit=total_debit,
        total_credit=total_credit,
        unmapped_count=len(unmapped),
        uncategorized_count=uncat_n,
        uncategorized_amount=uncat_amt,
        is_complete=complete,
        is_balanced=is_balanced,
        balance_difference=difference,
        notes=notes,
        generated_at=datetime.utcnow().isoformat() + "Z",
    )


def build_statement_diagnostics(db: Session, filters: ReportFilter) -> StatementDiagnostics:
    entity_id = assert_statement_scope(db, filters)
    entity = _entity(db, entity_id)
    as_of = _as_of_date(filters)
    year = filters.year or as_of.year
    month = filters.month or as_of.month
    scoped = filters.model_copy(
        update={
            "report_type": "balance_sheet",
            "entity_ids": [entity_id],
            "consolidate": False,
            "year": year,
            "month": month,
            "as_of_date": as_of,
            "date_to": as_of,
            "include_zero_lines": True,
        }
    )
    bs = build_report(db, scoped)
    tb = build_trial_balance(db, scoped)
    uncat_n, uncat_amt = tb.uncategorized_count, tb.uncategorized_amount
    journals = _cashbook_journals(db, scoped, entity_id)
    unmapped_codes = [r.account_code for r in tb.rows if not r.mapped and not r.synthetic]
    basis, notes, disclaimer = build_reporting_notes(db, scoped)
    plugs: list[StatementPlug] = []
    href_bs = f"/statements?year={year}&month={month}&tab=bs"
    href_tb = f"/statements?year={year}&month={month}&tab=tb"
    href_work = f"/work?year={year}&month={month}&filter=uncategorized"

    if bs.is_balanced is False:
        plugs.append(
            StatementPlug(
                key="out-of-balance",
                title="Statement will not balance",
                detail=f"Assets minus liabilities & equity = {bs.balance_difference}",
                amount=bs.balance_difference,
                href=href_bs,
                blocking=True,
            )
        )
    if uncat_n:
        plugs.append(
            StatementPlug(
                key="uncategorized",
                title=f"{uncat_n} uncategorized transaction(s)",
                detail="Items without a GL account post to 9999 suspense — recode before issuing the pack.",
                amount=uncat_amt,
                href=href_work,
                blocking=True,
            )
        )
    if unmapped_codes:
        plugs.append(
            StatementPlug(
                key="unmapped",
                title=f"{len(unmapped_codes)} unmapped account(s)",
                detail="Codes with activity that are not on the P&L or BS: " + ", ".join(unmapped_codes[:8]),
                href=href_tb,
                blocking=True,
            )
        )
    if bs.fx_missing:
        plugs.append(
            StatementPlug(
                key="fx-missing",
                title="Missing FX rates",
                detail="Pairs " + ", ".join(bs.fx_missing_pairs or []) + " were not translated.",
                href=href_bs,
                blocking=True,
            )
        )

    can_print = bool(bs.is_balanced) and uncat_n == 0 and not unmapped_codes and not bs.fx_missing
    return StatementDiagnostics(
        entity_id=entity_id,
        entity_code=entity.code,
        entity_name=entity.name,
        period_label=bs.period_label or f"As at {as_of.isoformat()}",
        currency=bs.currency,
        accounting_basis=basis,
        is_balanced=bool(bs.is_balanced),
        balance_difference=bs.balance_difference,
        fx_missing=bs.fx_missing,
        fx_missing_pairs=list(bs.fx_missing_pairs or []),
        uncategorized_count=uncat_n,
        uncategorized_amount=uncat_amt,
        unmapped_count=len(unmapped_codes),
        unmapped_codes=unmapped_codes,
        cashbook_journals_count=journals,
        plugs=plugs,
        can_print=can_print,
        notes=notes,
        pack_disclaimer=disclaimer,
        statements_href=href_bs,
        trial_balance_href=href_tb,
    )
