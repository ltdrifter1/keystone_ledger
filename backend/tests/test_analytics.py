from fastapi.testclient import TestClient

from app.database import SessionLocal, init_db
from app.main import app
from app.services.seed import seed_if_empty

client = TestClient(app)


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def test_report_prior_period_columns():
    res = client.post(
        "/api/reports/run",
        json={
            "report_type": "income_statement",
            "period": "monthly",
            "year": 2026,
            "month": 7,
            "scenario_id": 1,
            "reporting_currency": "CAD",
            "compare_prior_period": True,
            "compare_prior_year": True,
            "compare_budget": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "prior_period" in body["columns"]
    assert "prior_year" in body["columns"]
    assert "budget" in body["columns"]
    assert body["prior_period_label"]
    assert any(line.get("prior_period_amount") is not None for line in body["lines"])
    # Flux may be empty if nothing is material vs a silent June, but field exists
    assert "flux" in body


def test_analytics_pack_and_export():
    filters = {
        "report_type": "income_statement",
        "period": "ytd",
        "year": 2026,
        "month": 7,
        "scenario_id": 1,
        "reporting_currency": "CAD",
        "entity_ids": None,
    }
    pack = client.post("/api/reports/analytics", json=filters)
    assert pack.status_code == 200, pack.text
    body = pack.json()
    assert len(body["statements"]) == 2
    assert {s["report_type"] for s in body["statements"]} == {
        "income_statement",
        "balance_sheet",
    }
    assert body["kpis"]
    assert "materiality_amount" in body

    xlsx = client.post("/api/reports/export", json=filters)
    assert xlsx.status_code == 200, xlsx.text
    assert xlsx.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert xlsx.content[:2] == b"PK"
