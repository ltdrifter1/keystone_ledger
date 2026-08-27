from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.engines.bank_feeds import connect_feed, pending_rows, sync_feed
from app.engines.close_pack import run_close_pack_from_feed
from app.main import app
from app.models import BankAccount, DimAccount, DimEntity, Transaction
from app.services.seed import seed_if_empty

client = TestClient(app)


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def _fresh_bank(db) -> BankAccount:
    entity = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
    cash = db.scalar(select(DimAccount).where(DimAccount.code == "1000"))
    suf = uuid4().hex[:8]
    bank = BankAccount(
        entity_id=entity.id,
        name=f"Feed {suf}",
        account_number=f"FEED-{suf}",
        currency="CAD",
        institution="WBC",
        gl_account_id=cash.id if cash else None,
        opening_balance=Decimal("5000.00"),
        is_active=True,
    )
    db.add(bank)
    db.flush()
    return bank


def test_list_feeds_auto_connects():
    res = client.get("/api/bank-feeds")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body) >= 1
    assert all(row["provider"] == "keystone_open_banking" for row in body)
    assert any(row["status"] == "connected" for row in body)
    assert "pending_count" in body[0]


def test_sync_feed_imports_then_is_idempotent():
    db = SessionLocal()
    try:
        bank = _fresh_bank(db)
        connect_feed(db, bank.id)
        pending = pending_rows(db, bank)
        assert len(pending) >= 1
        first = sync_feed(db, bank.id, period_year=2026, period_month=7)
        db.commit()
        assert first["imported"] == len(pending)
        assert first["statement_ending_balance"] is not None
        feed_txns = list(
            db.scalars(
                select(Transaction).where(
                    Transaction.bank_account_id == bank.id,
                    Transaction.source_type == "bank_feed",
                )
            )
        )
        assert len(feed_txns) == first["imported"]
        assert all(t.txn_date == date(2026, 7, 28) or t.txn_date.month == 7 for t in feed_txns)
        second = sync_feed(db, bank.id, period_year=2026, period_month=7)
        db.commit()
        assert second["imported"] == 0
        assert second["pending_remaining"] == 0
    finally:
        db.close()


def test_close_pack_from_feed_uses_bank_balance():
    db = SessionLocal()
    try:
        bank = _fresh_bank(db)
        connect_feed(db, bank.id)
        db.commit()
        result = run_close_pack_from_feed(
            db,
            bank_account_id=bank.id,
            period_year=2026,
            period_month=7,
        )
        db.commit()
        assert result["reconciliation_id"]
        assert result["feed_imported"] >= 1
        assert result["statement_ending_balance"] is not None
        assert result["feed_status"] == "connected"
    finally:
        db.close()

    banks = client.get("/api/bank-feeds").json()
    target = next(b for b in banks if b["account_number"].startswith("1010") or b["account_number"] == "1050")
    fd = {
        "bank_account_id": str(target["bank_account_id"]),
        "period_year": "2026",
        "period_month": "7",
    }
    res = client.post("/api/close-pack/run-from-feed", data=fd)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["bank_account_id"] == target["bank_account_id"]
    assert body["statement_ending_balance"] is not None
