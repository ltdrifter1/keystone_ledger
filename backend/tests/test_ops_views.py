from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal, init_db
from app.main import app
from app.models import DimScenario, Transaction
from app.services.ensure_pnl_budget import ensure_pnl_budget_targets
from app.services.seed import seed_if_empty


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    ensure_pnl_budget_targets(db)
    db.close()


client = TestClient(app)


def test_pnl_budget_rows_created():
    db = SessionLocal()
    try:
        budget = db.scalar(select(DimScenario).where(DimScenario.code == "BUDGET"))
        assert budget
        count = db.scalar(
            select(func.count()).select_from(Transaction).where(Transaction.scenario_id == budget.id)
        )
        assert count and count > 0
        # Idempotent
        assert ensure_pnl_budget_targets(db) == 0
    finally:
        db.close()


def test_sales_expenses_budget_views_api():
    today = date.today()
    # Synoptic activity is mostly FY26 H1 — use June 2026
    year, month = 2026, 6
    entities = {e["code"]: e for e in client.get("/api/entities").json()}
    can_id = entities["CAN"]["id"]

    sales = client.get(f"/api/views/sales?year={year}&month={month}&entity_id={can_id}&period=ytd")
    assert sales.status_code == 200, sales.text
    body = sales.json()
    assert body["title"] == "Sales"
    assert body["entity_code"] == "CAN"
    assert len(body["kpis"]) >= 1
    assert isinstance(body["lines"], list)

    expenses = client.get(f"/api/views/expenses?year={year}&month={month}&entity_id={can_id}")
    assert expenses.status_code == 200, expenses.text
    assert expenses.json()["title"] == "Expenses"
    assert len(expenses.json()["lines"]) >= 1

    budget = client.get(f"/api/views/budget?year={year}&month={month}&entity_id={can_id}")
    assert budget.status_code == 200, budget.text
    b = budget.json()
    assert b["budget_facts_ready"] is True
    assert len(b["cash_rows"]) >= 1
    assert len(b["pnl_kpis"]) >= 1
