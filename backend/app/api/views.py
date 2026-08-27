from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.engines.ops_views import build_budget_view, build_expenses_view, build_sales_view
from app.schemas.ops_views import BudgetViewOut, ExpensesViewOut, SalesViewOut

router = APIRouter(prefix="/views")


@router.get("/sales", response_model=SalesViewOut)
def sales_view(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    entity_id: int | None = None,
    period: str = Query("ytd"),
    db: Session = Depends(get_db),
) -> SalesViewOut:
    data = build_sales_view(db, year=year, month=month, entity_id=entity_id, period=period)
    return SalesViewOut.model_validate(data)


@router.get("/expenses", response_model=ExpensesViewOut)
def expenses_view(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    entity_id: int | None = None,
    period: str = Query("ytd"),
    db: Session = Depends(get_db),
) -> ExpensesViewOut:
    data = build_expenses_view(db, year=year, month=month, entity_id=entity_id, period=period)
    return ExpensesViewOut.model_validate(data)


@router.get("/budget", response_model=BudgetViewOut)
def budget_view(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    entity_id: int | None = None,
    period: str = Query("ytd"),
    db: Session = Depends(get_db),
) -> BudgetViewOut:
    data = build_budget_view(db, year=year, month=month, entity_id=entity_id, period=period)
    return BudgetViewOut.model_validate(data)
