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


def _retire(db, *banks: BankAccount) -> None:
    """Keep isolated feed banks out of later all-bank close tests."""
    from app.models import Reconciliation, ReconciliationItem
    from sqlalchemy import delete

    for bank in banks:
        recons = list(db.scalars(select(Reconciliation).where(Reconciliation.bank_account_id == bank.id)))
        for recon in recons:
            db.execute(delete(ReconciliationItem).where(ReconciliationItem.reconciliation_id == recon.id))
            db.delete(recon)
        bank.is_active = False
    db.commit()


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
        _retire(db, bank)
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
        _retire(db, bank)
    finally:
        db.close()

    entities = {e["code"]: e for e in client.get("/api/entities").json()}
    created = client.post(
        "/api/bank-accounts",
        json={
            "entity_id": entities["CAN"]["id"],
            "name": "API Feed Close",
            "account_number": f"API-{uuid4().hex[:8]}",
            "currency": "CAD",
            "institution": "WBC",
            "opening_balance": "2500.00",
        },
    )
    assert created.status_code == 200, created.text
    bank_id = created.json()["id"]
    conn = client.post(f"/api/bank-feeds/{bank_id}/connect")
    assert conn.status_code == 200, conn.text
    res = client.post(
        "/api/close-pack/run-from-feed",
        data={
            "bank_account_id": str(bank_id),
            "period_year": "2026",
            "period_month": "7",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["bank_account_id"] == bank_id
    assert body["statement_ending_balance"] is not None
    assert body["feed_status"] == "connected"
    db = SessionLocal()
    try:
        row = db.get(BankAccount, bank_id)
        if row:
            _retire(db, row)
    finally:
        db.close()
