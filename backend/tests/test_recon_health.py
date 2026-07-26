from datetime import date
from decimal import Decimal

from app.database import SessionLocal, init_db
from app.engines.dashboard import build_dashboard, build_recon_health
from app.models import BankAccount, DimEntity
from app.services.ensure_budget import ensure_bank_budget_targets
from app.services.seed import seed_if_empty
from sqlalchemy import select


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    ensure_bank_budget_targets(db)
    db.close()


def test_dashboard_includes_recon_health():
    db = SessionLocal()
    try:
        dash = build_dashboard(db, "CAD")
        assert dash.recon_health
        row = dash.recon_health[0]
        assert row.name
        assert row.balance is not None
        assert row.target_status in ("on_target", "above", "below", "no_budget")
        assert row.recon_freshness in ("current", "prior", "stale", "never")
        assert row.href.startswith("/close?")
        assert "bank=" in row.href
    finally:
        db.close()


def test_budget_target_status_classification():
    db = SessionLocal()
    try:
        bank = db.scalar(select(BankAccount).limit(1))
        assert bank is not None
        ent = {e.id: e for e in db.scalars(select(DimEntity)).all()}
        bank.budget_balance = Decimal("100000")
        db.commit()

        on = build_recon_health(
            db,
            banks=[bank],
            entities=ent,
            balances={bank.id: Decimal("102000")},
            today=date.today(),
        )[0]
        assert on.target_status == "on_target"
        assert on.on_target is True

        below = build_recon_health(
            db,
            banks=[bank],
            entities=ent,
            balances={bank.id: Decimal("80000")},
            today=date.today(),
        )[0]
        assert below.target_status == "below"
        assert below.on_target is False

        bank.budget_balance = None
        db.commit()
        none = build_recon_health(
            db,
            banks=[bank],
            entities=ent,
            balances={bank.id: Decimal("80000")},
            today=date.today(),
        )[0]
        assert none.target_status == "no_budget"
    finally:
        db.close()


def test_api_dashboard_recon_health():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    res = client.get("/api/dashboard?reporting_currency=CAD")
    assert res.status_code == 200
    body = res.json()
    assert "recon_health" in body
    assert len(body["recon_health"]) >= 1
    row = body["recon_health"][0]
    assert "last_reconciled_date" in row
    assert "budget_balance" in row
    assert "target_status" in row
