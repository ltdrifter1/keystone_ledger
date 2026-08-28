"""CaseWare-style working-paper drill: report line → source fact transactions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.engines.fx import translate_amount
from app.engines.intercompany import account_is_ic_leg
from app.engines.reporting import (
    CASH_LINE_CODE,
    CASH_XFER_CODE,
    CURRENT_EARNINGS_CODE,
    IC_LINE_CODE,
    TRADE_AP_CODE,
    TRADE_AR_CODE,
    _as_of_date,
    _cashbook_signed_amount,
    _entity_banks,
    _iter_fact_lines,
    _period_bounds,
    _signed_amount,
    _translate_closing,
    _ytd_filters,
    build_report,
    period_label,
    use_cashbook_presentation,
)
from app.engines.working_papers import find_template
from app.models import DimAccount, DimEntity, DimReportLayout, Transaction
from app.schemas.reports import (
    DrillLine,
    DrillOut,
    DrillRequest,
    ReportFilter,
    WorkingPaperSnippet,
)


def _period_label(filters: ReportFilter) -> str:
    return period_label(filters)


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
        if match.line_code in ("NET_INCOME", "NI", CURRENT_EARNINGS_CODE) or (
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


def _drill_cashbook_cash(
    db: Session,
    payload: DrillRequest,
    *,
    filters: ReportFilter,
    reporting_currency: str,
    line_label: str,
    wp_ref: str | None,
    statement_amount: Decimal,
    accounts: dict[int, DimAccount],
    entities: dict[int, DimEntity],
) -> DrillOut:
    as_of = _as_of_date(filters)
    cash_acct = next((a for a in accounts.values() if a.code == "1000"), None)
    cash_id = cash_acct.id if cash_acct else 0
    detail: list[DrillLine] = []
    detail_total = Decimal("0")

    for bank in _entity_banks(db, filters.entity_ids):
        opening = Decimal(bank.opening_balance)
        if abs(opening) > Decimal("0.005"):
            amount, _, _ = _translate_closing(
                db,
                amount=opening,
                from_currency=bank.currency,
                to_currency=reporting_currency,
                as_of=as_of,
            )
            detail_total += amount
            ent = entities.get(bank.entity_id)
            detail.append(
                DrillLine(
                    transaction_id=-bank.id,
                    txn_date=date(2000, 1, 1),
                    description=f"Opening balance — {bank.name}",
                    entity_id=bank.entity_id,
                    entity_code=ent.code if ent else None,
                    bank_account_name=bank.name,
                    account_id=bank.gl_account_id or cash_id,
                    account_code="OPEN",
                    account_name="Opening balance",
                    department_id=None,
                    native_amount=opening,
                    currency=bank.currency,
                    reporting_amount=amount,
                    signed_amount=amount,
                    status="posted",
                    is_reconciled=False,
                )
            )

        txns = db.scalars(
            select(Transaction)
            .options(joinedload(Transaction.bank_account), joinedload(Transaction.entity))
            .where(
                Transaction.bank_account_id == bank.id,
                Transaction.txn_date <= as_of,
                Transaction.scenario_id == filters.scenario_id,
                Transaction.status.notin_(["void", "excluded"]),
            )
        ).unique().all()
        for txn in txns:
            native = Decimal(txn.amount)
            amount, _, _ = _translate_closing(
                db,
                amount=native,
                from_currency=txn.currency,
                to_currency=reporting_currency,
                as_of=as_of,
            )
            detail_total += amount
            acct = accounts.get(txn.account_id) if txn.account_id else cash_acct
            ent = entities.get(txn.entity_id)
            detail.append(
                DrillLine(
                    transaction_id=txn.id,
                    txn_date=txn.txn_date,
                    description=txn.description,
                    entity_id=txn.entity_id,
                    entity_code=ent.code if ent else (txn.entity.code if txn.entity else None),
                    bank_account_name=bank.name,
                    account_id=acct.id if acct else cash_id,
                    account_code=acct.code if acct else "1000",
                    account_name=acct.name if acct else "Cash",
                    department_id=txn.department_id,
                    native_amount=native,
                    currency=txn.currency,
                    reporting_amount=amount,
                    signed_amount=amount,
                    is_split=txn.is_split,
                    split_memo=txn.memo,
                    status=txn.status,
                    is_reconciled=txn.is_reconciled,
                )
            )

    detail.sort(key=lambda row: (row.txn_date, row.transaction_id, row.account_code))
    difference = statement_amount - detail_total
    tmpl = find_template(line_code=CASH_LINE_CODE)
    template_snippet = None
    if tmpl:
        wp_ref = tmpl.wp_ref
        template_snippet = WorkingPaperSnippet(
            key=tmpl.key,
            wp_ref=tmpl.wp_ref,
            title=tmpl.title,
            purpose=tmpl.purpose,
            objective=tmpl.objective,
            tie_out=tmpl.tie_out,
            procedures=list(tmpl.procedures),
            evidence=list(tmpl.evidence),
        )
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
        is_tied=abs(difference) < Decimal("0.02"),
        row_count=len(detail),
        lines=detail,
        generated_at=datetime.utcnow().isoformat() + "Z",
        template=template_snippet,
    )


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

    report = build_report(db, filters)
    report_line = next((line for line in report.lines if line.line_code == payload.line_code), None)
    statement_amount = report_line.amount if report_line else Decimal("0")
    if report_line:
        line_label = report_line.line_label
        wp_ref = wp_ref or report_line.wp_ref

    cashbook = use_cashbook_presentation(db, filters)
    if cashbook and payload.line_code == CASH_LINE_CODE:
        return _drill_cashbook_cash(
            db,
            payload,
            filters=filters,
            reporting_currency=reporting_currency,
            line_label=line_label,
            wp_ref=wp_ref,
            statement_amount=statement_amount,
            accounts=accounts,
            entities=entities,
        )

    is_current_earnings = payload.line_code == CURRENT_EARNINGS_CODE
    is_net_income_line = payload.line_code in ("NI", "NET_INCOME", CURRENT_EARNINGS_CODE) or (
        report_line is not None
        and report_line.is_total
        and report_line.section == "totals"
        and "NET" in report_line.line_label.upper()
    )

    sign_report_type = "income_statement" if is_current_earnings else filters.report_type
    if is_current_earnings:
        date_from, date_to = _period_bounds(_ytd_filters(filters))
        rate_type = "average"
    elif balance_sheet:
        date_from = date(2000, 1, 1)
        date_to = filters.as_of_date or filters.date_to or date.today()
        rate_type = "closing"
    else:
        date_from, date_to = _period_bounds(filters)
        rate_type = "average"

    ic_mode = None
    if payload.line_code in (TRADE_AR_CODE, TRADE_AP_CODE):
        ic_mode = "exclude"
    elif payload.line_code == IC_LINE_CODE:
        ic_mode = "only"

    detail: list[DrillLine] = []
    detail_total = Decimal("0")

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

        extra = ""
        if txn.is_split and txn.splits:
            for split in txn.splits:
                if split.account_id == account_id:
                    extra = split.memo or ""
                    break
        else:
            extra = txn.memo or ""
        is_ic = account_is_ic_leg(acct, txn, extra)
        if ic_mode == "exclude" and is_ic:
            continue
        if ic_mode == "only":
            if acct.code == "2100" or acct.is_intercompany:
                pass
            elif not is_ic:
                continue

        translated = translate_amount(
            db,
            amount=amount,
            from_currency=txn.currency,
            to_currency=reporting_currency,
            as_of=txn.txn_date,
            rate_type=rate_type,
        )
        reporting_amt = translated.amount
        # Net income WP uses economic contribution (bank-signed).
        # Other IS lines use statement presentation (expenses positive).
        if is_net_income_line and sign_report_type == "income_statement":
            signed = reporting_amt
        elif ic_mode == "only" and acct.code == "1100":
            signed = -_signed_amount(acct, reporting_amt, "balance_sheet")
        elif cashbook and sign_report_type == "balance_sheet":
            signed = _cashbook_signed_amount(acct, reporting_amt, payload.line_code)
        else:
            signed = _signed_amount(acct, reporting_amt, sign_report_type)
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

    acct_codes = [accounts[i].code for i in account_ids if i in accounts]
    tmpl = find_template(
        line_code=payload.line_code,
        account_codes=None if payload.line_code == CASH_XFER_CODE else acct_codes,
        wp_ref=wp_ref,
    )
    template_snippet = None
    if tmpl:
        wp_ref = tmpl.wp_ref
        template_snippet = WorkingPaperSnippet(
            key=tmpl.key,
            wp_ref=tmpl.wp_ref,
            title=tmpl.title,
            purpose=tmpl.purpose,
            objective=tmpl.objective,
            tie_out=tmpl.tie_out,
            procedures=list(tmpl.procedures),
            evidence=list(tmpl.evidence),
        )

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
        template=template_snippet,
    )
