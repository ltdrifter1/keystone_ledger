from datetime import date
from decimal import Decimal

from app.database import SessionLocal, init_db
from app.engines.close_pack import build_next_actions, month_close_overview, run_statement_close_pack
from app.engines.dashboard import build_dashboard
from app.engines.reconciliation import beginning_balance
from app.models import BankAccount, Transaction
from app.services.seed import seed_if_empty
from sqlalchemy import select


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def test_next_actions_ranks_not_started_banks():
    db = SessionLocal()
    try:
        today = date.today()
        overview = month_close_overview(db, today.year, today.month)
        assert "next_actions" in overview
        assert overview["banks_total"] >= 1
        # Fresh month with no recon should suggest starting banks
        kinds = {a["kind"] for a in overview["next_actions"]}
        assert "not_started" in kinds or overview["banks_locked"] == overview["banks_total"]
        actions = build_next_actions(overview["packs"])
        assert all("href" not in a for a in actions)  # close API shape has no href
        assert all(a["bank_account_id"] for a in actions)
    finally:
        db.close()


def test_dashboard_exposes_close_next_actions():
    db = SessionLocal()
    try:
        dash = build_dashboard(db, "CAD")
        assert dash.close_summary is not None
        assert dash.close_summary.banks_total >= 1
        assert isinstance(dash.next_actions, list)
        job_keys = {k.key for k in dash.kpis}
        assert "uncategorized" in job_keys
        assert "close_progress" in job_keys
        # Job KPIs should appear before pure P&L context
        keys = [k.key for k in dash.kpis]
        assert keys.index("uncategorized") < keys.index("revenue")
    finally:
        db.close()


def test_close_pack_status_includes_cleared_total():
    db = SessionLocal()
    try:
        bank = db.scalar(select(BankAccount).limit(1))
        assert bank is not None
        today = date.today()
        year, month = today.year, today.month
        beg = beginning_balance(db, bank.id, year, month)
        # Use a clean ending = beginning so difference can be zero after auto-clear of zero activity
        # Prefer a real txn month path: run pack with statement = beg + sum of categorized in-period
        txns = list(
            db.scalars(
                select(Transaction).where(
                    Transaction.bank_account_id == bank.id,
                    Transaction.status != "void",
                )
            )
        )
        in_period = [t for t in txns if t.txn_date.year == year and t.txn_date.month == month]
        cleared_candidate = sum(
            (Decimal(t.amount) for t in in_period if t.status == "categorized" or t.is_split),
            Decimal("0"),
        )
        statement = beg + cleared_candidate
        result = run_statement_close_pack(
            db,
            bank_account_id=bank.id,
            period_year=year,
            period_month=month,
            statement_ending_balance=statement,
            actor="test",
        )
        db.commit()
        assert "cleared_total" in result
        assert result["cleared_total"] is not None
        overview = month_close_overview(db, year, month)
        pack = next(p for p in overview["packs"] if p["bank_account_id"] == bank.id)
        assert pack["reconciliation_id"] is not None
        # After run, next actions should not be only not_started for this bank
        bank_actions = [a for a in overview["next_actions"] if a["bank_account_id"] == bank.id]
        assert not any(a["kind"] == "not_started" for a in bank_actions)
    finally:
        db.close()


def test_api_month_overview_next_actions():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    today = date.today()
    res = client.get(f"/api/close-pack/month?year={today.year}&month={today.month}")
    assert res.status_code == 200
    body = res.json()
    assert "next_actions" in body
    dash = client.get("/api/dashboard?reporting_currency=CAD")
    assert dash.status_code == 200
    d = dash.json()
    assert d["close_summary"]["period_label"]
    assert isinstance(d["next_actions"], list)
