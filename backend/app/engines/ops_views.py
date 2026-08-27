"""Controller quick-views: Sales, Expenses, Budget overview."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines.dashboard import _target_status
from app.engines.reporting import build_report
from app.models import BankAccount, DimAccount, DimEntity, DimScenario, Transaction
from app.schemas.reports import ReportFilter


def _period_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _scenario_id(db: Session, code: str) -> int | None:
    row = db.scalar(select(DimScenario).where(DimScenario.code == code))
    return row.id if row else None


def _entity(db: Session, entity_id: int | None) -> DimEntity | None:
    if not entity_id:
        return None
    return db.get(DimEntity, entity_id)


def _base_filters(
    *,
    year: int,
    month: int,
    entity_id: int | None,
    scenario_id: int,
    compare_scenario_id: int | None = None,
    period: str = "ytd",
) -> ReportFilter:
    end = _period_end(year, month)
    return ReportFilter(
        report_type="income_statement",
        period=period,
        year=year,
        month=month,
        scenario_id=scenario_id,
        compare_scenario_id=compare_scenario_id,
        reporting_currency="CAD",
        consolidate=entity_id is None,
        entity_ids=[entity_id] if entity_id else None,
        as_of_date=end,
        date_to=end,
    )


def _line_dict(line, *, year: int | None = None, month: int | None = None) -> dict:
    href = f"/statements?tab=statement&type=income_statement&line={line.line_code}"
    if year and month:
        href += f"&year={year}&month={month}"
    return {
        "line_code": line.line_code,
        "line_label": line.line_label,
        "section": line.section,
        "amount": float(line.amount),
        "compare_amount": float(line.compare_amount) if line.compare_amount is not None else None,
        "variance": float(line.variance) if line.variance is not None else None,
        "variance_pct": float(line.variance_pct) if line.variance_pct is not None else None,
        "indent_level": line.indent_level,
        "is_bold": line.is_bold,
        "is_total": line.is_total,
        "drillable": line.drillable,
        "account_id": line.account_id,
        "account_ids": list(line.account_ids or []),
        "account_type_filter": line.account_type_filter,
        "wp_ref": line.wp_ref,
        "href": href,
    }


def _pick_lines(
    report,
    *,
    year: int | None = None,
    month: int | None = None,
    prefixes: tuple[str, ...] = (),
    codes: set[str] | None = None,
    sections: set[str] | None = None,
):
    out = []
    for line in report.lines:
        if codes and line.line_code in codes:
            out.append(_line_dict(line, year=year, month=month))
            continue
        if prefixes and any(line.line_code.startswith(p) for p in prefixes):
            out.append(_line_dict(line, year=year, month=month))
            continue
        if sections and line.section in sections and (line.account_id or line.is_total or line.is_bold):
            out.append(_line_dict(line, year=year, month=month))
            continue
    return out


def _kpi_from_line(report, code: str, label: str, *, good_if_positive_variance: bool | None = None) -> dict | None:
    line = next((l for l in report.lines if l.line_code == code), None)
    if not line:
        return None
    tone = "neutral"
    if line.variance is not None and good_if_positive_variance is not None:
        if good_if_positive_variance:
            tone = "ok" if line.variance >= 0 else "warn"
        else:
            tone = "ok" if line.variance <= 0 else "warn"
    return {
        "key": code.lower(),
        "label": label,
        "amount": float(line.amount),
        "compare_amount": float(line.compare_amount) if line.compare_amount is not None else None,
        "variance": float(line.variance) if line.variance is not None else None,
        "variance_pct": float(line.variance_pct) if line.variance_pct is not None else None,
        "tone": tone,
    }


def _top_revenue_channels(db: Session, *, year: int, month: int, entity_id: int | None, scenario_id: int) -> list[dict]:
    """Department/channel roll-up for sales (NOBL, LBNA_XM, etc.)."""
    end = _period_end(year, month)
    start = date(year, 1, 1)
    q = (
        select(
            Transaction.department_id,
            func.coalesce(func.sum(Transaction.amount_reporting), func.sum(Transaction.amount)),
        )
        .join(DimAccount, DimAccount.id == Transaction.account_id)
        .where(
            Transaction.scenario_id == scenario_id,
            Transaction.status != "void",
            DimAccount.account_type == "revenue",
            Transaction.txn_date >= start,
            Transaction.txn_date <= end,
        )
        .group_by(Transaction.department_id)
    )
    if entity_id:
        q = q.where(Transaction.entity_id == entity_id)
    rows = db.execute(q).all()
    from app.models import DimDepartment

    depts = {d.id: d for d in db.scalars(select(DimDepartment)).all()}
    channels = []
    for dept_id, total in rows:
        if total is None or Decimal(total) == 0:
            continue
        dept = depts.get(dept_id) if dept_id else None
        label = dept.name if dept else "Unassigned"
        channels.append(
            {
                "line_code": f"CH_{dept.code if dept else 'NONE'}",
                "line_label": label,
                "section": "channel",
                "amount": float(total),
                "compare_amount": None,
                "variance": None,
                "variance_pct": None,
                "indent_level": 0,
                "is_bold": False,
                "is_total": False,
                "drillable": False,
                "account_id": None,
                "account_ids": [],
                "account_type_filter": "revenue",
                "wp_ref": None,
                "href": "/transactions?uncategorized_only=false",
            }
        )
    channels.sort(key=lambda r: abs(r["amount"]), reverse=True)
    return channels[:8]


def build_sales_view(
    db: Session,
    *,
    year: int,
    month: int,
    entity_id: int | None = None,
    period: str = "ytd",
) -> dict:
    actual_id = _scenario_id(db, "ACTUAL") or 1
    budget_id = _scenario_id(db, "BUDGET")
    ent = _entity(db, entity_id)
    filters = _base_filters(
        year=year,
        month=month,
        entity_id=entity_id,
        scenario_id=actual_id,
        compare_scenario_id=budget_id,
        period=period,
    )
    report = build_report(db, filters)
    lines = _pick_lines(
        report,
        year=year,
        month=month,
        prefixes=("REV", "TOT_REV", "GP"),
        codes={"REV", "TOT_REV", "GP", "REV_PROD", "REV_SVC", "REV_SHIP", "REV_RET"},
    )
    # Prefer layout revenue section if prefixes missed custom layouts
    if len(lines) < 2:
        lines = _pick_lines(report, year=year, month=month, sections={"revenue", "totals"})
        lines = [l for l in lines if "REV" in l["line_code"] or l["line_code"] in ("GP", "TOT_REV")]

    kpis = []
    for code, label, good in (
        ("TOT_REV", "Total sales", True),
        ("REV_PROD", "Product sales", True),
        ("REV_SVC", "Service revenue", True),
        ("GP", "Gross profit", True),
    ):
        kpi = _kpi_from_line(report, code, label, good_if_positive_variance=good)
        if kpi:
            kpis.append(kpi)

    return {
        "title": "Sales",
        "period_label": f"{year}-{month:02d}",
        "period_year": year,
        "period_month": month,
        "currency": report.currency,
        "entity_id": entity_id,
        "entity_code": ent.code if ent else None,
        "kpis": kpis,
        "lines": lines,
        "top_channels": _top_revenue_channels(
            db, year=year, month=month, entity_id=entity_id, scenario_id=actual_id
        ),
        "report_filters": filters.model_dump(mode="json"),
    }


def build_expenses_view(
    db: Session,
    *,
    year: int,
    month: int,
    entity_id: int | None = None,
    period: str = "ytd",
) -> dict:
    actual_id = _scenario_id(db, "ACTUAL") or 1
    budget_id = _scenario_id(db, "BUDGET")
    ent = _entity(db, entity_id)
    filters = _base_filters(
        year=year,
        month=month,
        entity_id=entity_id,
        scenario_id=actual_id,
        compare_scenario_id=budget_id,
        period=period,
    )
    report = build_report(db, filters)
    keep_prefixes = ("COGS", "TOT_COGS", "OPEX", "EXP_", "TOT_OPEX", "TOT_EXP", "BTL", "TOT_BTL")
    lines = [
        _line_dict(l, year=year, month=month)
        for l in report.lines
        if any(l.line_code.startswith(p) for p in keep_prefixes) or l.line_code in {"COGS", "OPEX", "BTL"}
    ]
    kpis = []
    for code, label in (
        ("TOT_EXP", "Total expenses"),
        ("TOT_COGS", "COGS"),
        ("TOT_OPEX", "Operating expenses"),
        ("EXP_OTH", "Other OpEx"),
    ):
        kpi = _kpi_from_line(report, code, label, good_if_positive_variance=False)
        if kpi:
            kpis.append(kpi)

    return {
        "title": "Expenses",
        "period_label": f"{year}-{month:02d}",
        "period_year": year,
        "period_month": month,
        "currency": report.currency,
        "entity_id": entity_id,
        "entity_code": ent.code if ent else None,
        "kpis": kpis,
        "lines": lines,
        "report_filters": filters.model_dump(mode="json"),
    }


def _cash_budget_rows(db: Session, *, entity_id: int | None, year: int, month: int) -> list[dict]:
    banks = list(db.scalars(select(BankAccount).where(BankAccount.is_active == True)).all())
    if entity_id:
        banks = [b for b in banks if b.entity_id == entity_id]
    entities = {e.id: e for e in db.scalars(select(DimEntity)).all()}
    end = _period_end(year, month)
    rows = []
    for bank in banks:
        activity = db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.bank_account_id == bank.id,
                Transaction.status != "void",
                Transaction.txn_date <= end,
                Transaction.scenario_id == (_scenario_id(db, "ACTUAL") or 1),
            )
        )
        book = Decimal(bank.opening_balance) + Decimal(activity or 0)
        budget = Decimal(bank.budget_balance) if bank.budget_balance is not None else None
        status, _on, variance, variance_pct = _target_status(book, budget)
        ent = entities.get(bank.entity_id)
        rows.append(
            {
                "bank_account_id": bank.id,
                "bank_account_name": bank.name,
                "entity_code": ent.code if ent else None,
                "currency": bank.currency,
                "book_balance": float(book),
                "budget_balance": float(budget) if budget is not None else None,
                "variance": float(variance) if variance is not None else None,
                "variance_pct": float(variance_pct) if variance_pct is not None else None,
                "status": status,
                "href": f"/work?year={year}&month={month}&bank={bank.id}",
            }
        )
    return rows


def build_budget_view(
    db: Session,
    *,
    year: int,
    month: int,
    entity_id: int | None = None,
    period: str = "ytd",
) -> dict:
    actual_id = _scenario_id(db, "ACTUAL") or 1
    budget_id = _scenario_id(db, "BUDGET")
    ent = _entity(db, entity_id)
    budget_ready = False
    if budget_id:
        count = db.scalar(
            select(func.count()).select_from(Transaction).where(Transaction.scenario_id == budget_id)
        )
        budget_ready = bool(count and int(count) > 0)

    filters = _base_filters(
        year=year,
        month=month,
        entity_id=entity_id,
        scenario_id=actual_id,
        compare_scenario_id=budget_id if budget_ready else None,
        period=period,
    )
    report = build_report(db, filters)

    focus_codes = {
        "TOT_REV",
        "TOT_COGS",
        "TOT_OPEX",
        "TOT_EXP",
        "GP",
        "OI",
        "NI",
        "REV_PROD",
        "EXP_OTH",
        "EXP_ADM",
        "EXP_MKT",
    }
    pnl_lines = [
        _line_dict(l, year=year, month=month)
        for l in report.lines
        if l.line_code in focus_codes or l.is_total
    ]
    # Deduplicate while preserving order
    seen = set()
    unique_lines = []
    for line in pnl_lines:
        if line["line_code"] in seen:
            continue
        seen.add(line["line_code"])
        unique_lines.append(line)

    pnl_kpis = []
    for code, label, good in (
        ("TOT_REV", "Sales vs budget", True),
        ("TOT_EXP", "Expenses vs budget", False),
        ("GP", "Gross profit vs budget", True),
        ("NI", "Net income vs budget", True),
    ):
        kpi = _kpi_from_line(report, code, label, good_if_positive_variance=good)
        if kpi:
            pnl_kpis.append(kpi)

    return {
        "title": "Budget overview",
        "period_label": f"{year}-{month:02d}",
        "period_year": year,
        "period_month": month,
        "currency": report.currency,
        "entity_id": entity_id,
        "entity_code": ent.code if ent else None,
        "pnl_kpis": pnl_kpis,
        "pnl_lines": unique_lines,
        "cash_rows": _cash_budget_rows(db, entity_id=entity_id, year=year, month=month),
        "budget_facts_ready": budget_ready,
        "report_filters": filters.model_dump(mode="json"),
    }
