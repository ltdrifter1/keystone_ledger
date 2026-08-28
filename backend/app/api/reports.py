from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.engines.drilldown import drill_report_line
from app.engines.reporting import build_analytics_pack, export_statement_pack_xlsx
from app.engines.statement_pack import (
    assert_statement_scope,
    build_official_report,
    build_statement_diagnostics,
    build_trial_balance,
    scoped_statement_filters,
)
from app.schemas.reports import (
    AnalyticsPack,
    DrillOut,
    DrillRequest,
    ReportFilter,
    ReportOut,
    StatementDiagnostics,
    TrialBalanceOut,
)

router = APIRouter(prefix="/reports")

CASH_FLOW_GONE = "Cash flow is not part of this pack. Print P&L, the balance sheet, and the equity roll."


def _official_or_400(db: Session, filters: ReportFilter) -> ReportOut:
    try:
        assert_statement_scope(db, filters)
        return build_official_report(db, filters)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _scoped_filters(db: Session, filters: ReportFilter) -> ReportFilter:
    try:
        return scoped_statement_filters(db, filters)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/run", response_model=ReportOut)
def run_report(filters: ReportFilter, db: Session = Depends(get_db)) -> ReportOut:
    return _official_or_400(db, filters)


@router.post("/analytics", response_model=AnalyticsPack)
def analytics(filters: ReportFilter, db: Session = Depends(get_db)) -> AnalyticsPack:
    filters = _scoped_filters(db, filters)
    return build_analytics_pack(db, filters)


@router.post("/export")
def export_pack(filters: ReportFilter, db: Session = Depends(get_db)) -> StreamingResponse:
    filters = _scoped_filters(db, filters)
    payload = export_statement_pack_xlsx(db, filters)
    year = filters.year or 0
    month = filters.month or 0
    filename = f"keystone-statements-{year}-{month:02d}.xlsx"
    return StreamingResponse(
        iter([payload]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/trial-balance", response_model=TrialBalanceOut)
def trial_balance(filters: ReportFilter, db: Session = Depends(get_db)) -> TrialBalanceOut:
    filters = _scoped_filters(db, filters)
    try:
        return build_trial_balance(db, filters)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/diagnostics", response_model=StatementDiagnostics)
def diagnostics_post(filters: ReportFilter, db: Session = Depends(get_db)) -> StatementDiagnostics:
    filters = _scoped_filters(db, filters)
    try:
        return build_statement_diagnostics(db, filters)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/diagnostics", response_model=StatementDiagnostics)
def diagnostics_get(
    year: int | None = None,
    month: int | None = None,
    entity_id: int | None = None,
    reporting_currency: str = "CAD",
    db: Session = Depends(get_db),
) -> StatementDiagnostics:
    from datetime import date

    filters = ReportFilter(
        report_type="balance_sheet",
        year=year,
        month=month,
        entity_ids=[entity_id] if entity_id else None,
        reporting_currency=reporting_currency,
        consolidate=False,
        as_of_date=date.today() if year is None else None,
    )
    filters = _scoped_filters(db, filters)
    try:
        return build_statement_diagnostics(db, filters)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/drill", response_model=DrillOut)
def drill(payload: DrillRequest, db: Session = Depends(get_db)) -> DrillOut:
    try:
        return drill_report_line(db, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/income-statement", response_model=ReportOut)
def income_statement(
    year: int | None = None,
    month: int | None = None,
    period: str = "ytd",
    scenario_id: int = 1,
    compare_scenario_id: int | None = None,
    entity_id: int | None = None,
    reporting_currency: str = "CAD",
    db: Session = Depends(get_db),
) -> ReportOut:
    filters = ReportFilter(
        report_type="income_statement",
        year=year,
        month=month,
        period=period,
        scenario_id=scenario_id,
        compare_scenario_id=compare_scenario_id,
        entity_ids=[entity_id] if entity_id else None,
        reporting_currency=reporting_currency,
        consolidate=False,
    )
    return _official_or_400(db, filters)


@router.get("/balance-sheet", response_model=ReportOut)
def balance_sheet(
    as_of_date: str | None = None,
    year: int | None = None,
    month: int | None = None,
    scenario_id: int = 1,
    entity_id: int | None = None,
    reporting_currency: str = "CAD",
    db: Session = Depends(get_db),
) -> ReportOut:
    from datetime import date

    filters = ReportFilter(
        report_type="balance_sheet",
        as_of_date=date.fromisoformat(as_of_date) if as_of_date else None,
        year=year,
        month=month,
        scenario_id=scenario_id,
        entity_ids=[entity_id] if entity_id else None,
        reporting_currency=reporting_currency,
        consolidate=False,
    )
    return _official_or_400(db, filters)


@router.get("/equity", response_model=ReportOut)
def equity_statement(
    year: int | None = None,
    month: int | None = None,
    entity_id: int | None = None,
    reporting_currency: str = "CAD",
    db: Session = Depends(get_db),
) -> ReportOut:
    filters = ReportFilter(
        report_type="equity",
        year=year,
        month=month,
        period="ytd",
        entity_ids=[entity_id] if entity_id else None,
        reporting_currency=reporting_currency,
        consolidate=False,
    )
    return _official_or_400(db, filters)


@router.get("/cash-flow")
def cash_flow(
    year: int | None = Query(None),
    period: str = "ytd",
    scenario_id: int = 1,
    entity_id: int | None = None,
    reporting_currency: str = "CAD",
) -> None:
    raise HTTPException(status_code=410, detail=CASH_FLOW_GONE)
