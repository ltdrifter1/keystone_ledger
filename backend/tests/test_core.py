from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import SessionLocal, init_db
from app.engines.fingerprint import transaction_fingerprint
from app.engines.rules import apply_rules_to_transaction
from app.main import app
from app.models import CategorizationRule, Transaction
from app.services.seed import seed_if_empty


def setup_module():
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_dashboard_and_income_statement():
    dash = client.get("/api/dashboard")
    assert dash.status_code == 200
    body = dash.json()
    assert len(body["kpis"]) >= 5
    assert len(body["cash_by_account"]) >= 1

    entities = {e["code"]: e for e in client.get("/api/entities").json()}
    can_id = entities["CAN"]["id"]
    report = client.get(f"/api/reports/income-statement?period=ytd&entity_id={can_id}")
    assert report.status_code == 200
    assert report.json()["title"] == "Profit & Loss"
    assert len(report.json()["lines"]) > 0


def test_transactions_list_and_categorize():
    entities = client.get("/api/entities").json()
    banks = client.get("/api/bank-accounts").json()
    created = client.post(
        "/api/transactions",
        json={
            "txn_date": "2026-07-01",
            "description": "CORE TEST UNCATEGORIZED",
            "amount": "-12.34",
            "currency": "CAD",
            "entity_id": entities[0]["id"],
            "bank_account_id": banks[0]["id"],
            "scenario_id": 1,
        },
    )
    assert created.status_code == 200
    txn_id = created.json()["id"]

    accounts = client.get("/api/accounts").json()
    expense = next(a for a in accounts if a["account_type"] == "expense")
    res = client.post(
        f"/api/transactions/{txn_id}/categorize",
        json={"account_id": expense["id"], "create_rule": True, "rule_name": "Test rule"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "categorized"
    assert res.json()["account_id"] == expense["id"]


def test_fingerprint_stable():
    from datetime import date

    a = transaction_fingerprint(
        txn_date=date(2026, 1, 1),
        amount=Decimal("-10.00"),
        description="AWS MONTHLY",
        currency="CAD",
        bank_account_id=1,
    )
    b = transaction_fingerprint(
        txn_date=date(2026, 1, 1),
        amount=Decimal("-10.00"),
        description="aws   monthly",
        currency="CAD",
        bank_account_id=1,
    )
    assert a == b


def test_rule_match():
    db = SessionLocal()
    try:
        rule = CategorizationRule(
            name="Temp AWS",
            priority=1,
            match_description_contains="AWS",
            assign_account_id=1,
        )
        txn = Transaction(
            txn_date=__import__("datetime").date.today(),
            description="AWS Invoice 99",
            amount=Decimal("-1.00"),
            currency="CAD",
            entity_id=1,
            scenario_id=1,
            status="uncategorized",
        )
        assert apply_rules_to_transaction(db, txn, rules=[rule]) is True
        assert txn.account_id == 1
        assert txn.status == "categorized"
    finally:
        db.rollback()
        db.close()
