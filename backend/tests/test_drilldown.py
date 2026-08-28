from fastapi.testclient import TestClient

from app.database import SessionLocal, init_db
from app.main import app
from app.services.seed import seed_if_empty

client = TestClient(app)


def setup_module():
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def test_report_lines_are_drillable():
    res = client.get("/api/reports/income-statement?period=ytd&year=2026&month=7")
    assert res.status_code == 200
    body = res.json()
    drillable = [line for line in body["lines"] if line.get("drillable")]
    assert len(drillable) >= 1
    assert any(line.get("wp_ref") for line in drillable)


def test_drill_ties_to_statement_line():
    report = client.get("/api/reports/income-statement?period=ytd&year=2026&month=7").json()
    line = next(item for item in report["lines"] if item["drillable"] and item.get("account_id"))
    drill = client.post(
        "/api/reports/drill",
        json={
            "line_code": line["line_code"],
            "account_id": line["account_id"],
            "account_ids": line.get("account_ids") or [line["account_id"]],
            "filters": {
                "report_type": "income_statement",
                "period": "ytd",
                "scenario_id": 1,
                "reporting_currency": "CAD",
                "year": 2026,
                "month": 7,
            },
        },
    )
    assert drill.status_code == 200, drill.text
    body = drill.json()
    assert body["line_code"] == line["line_code"]
    assert body["is_tied"] is True
    assert abs(float(body["statement_amount"]) - float(line["amount"])) < 0.02
    assert abs(float(body["detail_total"]) - float(body["statement_amount"])) < 0.02
    assert body["row_count"] == len(body["lines"])


def test_drill_net_income():
    report = client.get("/api/reports/income-statement?period=ytd&year=2026&month=7").json()
    ni = next(item for item in report["lines"] if item["line_code"] in ("NI", "NET_INCOME"))
    drill = client.post(
        "/api/reports/drill",
        json={
            "line_code": ni["line_code"],
            "account_ids": ni.get("account_ids"),
            "filters": {
                "report_type": "income_statement",
                "period": "ytd",
                "year": 2026,
                "month": 7,
                "scenario_id": 1,
                "reporting_currency": "CAD",
            },
        },
    )
    assert drill.status_code == 200, drill.text
    body = drill.json()
    assert body["is_tied"] is True
    assert body["row_count"] >= 1
