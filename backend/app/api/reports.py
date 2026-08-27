from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.engines.drilldown import drill_report_line
from app.engines.reporting import build_analytics_pack, build_report, export_statement_pack_xlsx
from app.schemas.reports import AnalyticsPack, DrillOut, DrillRequest, ReportFilter, ReportOut

router = APIRouter(prefix="/reports")


@router.post("/run", response_model=ReportOut)
def run_report(filters: ReportFilter, db: Session = Depends(get_db)) -> ReportOut:
    return build_report(db, filters)


@router.post("/analytics", response_model=AnalyticsPack)
def analytics(filters: ReportFilter, db: Session = Depends(get_db)) -> AnalyticsPack:
    return build_analytics_pack(db, filters)


@router.post("/export")
def export_pack(filters: ReportFilter, db: Session = Depends(get_db)) -> StreamingResponse:
    payload = export_statement_pack_xlsx(db, filters)
    year = filters.year or 0
    month = filters.month or 0
    filename = f"keystone-statements-{year}-{month:02d}.xlsx"
    return StreamingResponse(
        iter([payload]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
        consolidate=entity_id is None,
    )
    return build_report(db, filters)


@router.get("/balance-sheet", response_model=ReportOut)
def balance_sheet(
    as_of_date: str | None = None,
    scenario_id: int = 1,
    entity_id: int | None = None,
    reporting_currency: str = "CAD",
    db: Session = Depends(get_db),
) -> ReportOut:
    from datetime import date

    filters = ReportFilter(
        report_type="balance_sheet",
        as_of_date=date.fromisoformat(as_of_date) if as_of_date else date.today(),
        scenario_id=scenario_id,
        entity_ids=[entity_id] if entity_id else None,
        reporting_currency=reporting_currency,
        consolidate=entity_id is None,
    )
    return build_report(db, filters)


@router.get("/cash-flow", response_model=ReportOut)
def cash_flow(
    year: int | None = None,
    period: str = "ytd",
    scenario_id: int = 1,
    entity_id: int | None = None,
    reporting_currency: str = "CAD",
    db: Session = Depends(get_db),
) -> ReportOut:
    filters = ReportFilter(
        report_type="cash_flow",
        year=year,
        period=period,
        scenario_id=scenario_id,
        entity_ids=[entity_id] if entity_id else None,
        reporting_currency=reporting_currency,
        consolidate=entity_id is None,
    )
    return build_report(db, filters)
