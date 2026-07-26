from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.engines.dashboard import build_dashboard
from app.schemas.reports import DashboardOut

router = APIRouter()


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(reporting_currency: str = "CAD", db: Session = Depends(get_db)) -> DashboardOut:
    return build_dashboard(db, reporting_currency=reporting_currency)
