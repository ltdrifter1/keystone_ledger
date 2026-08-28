"""Monthly rec: entity close files, GL lock + PCA, CAN↔USA IC."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.engines.binder import get_binder_document, upsert_binder_document
from app.engines.cash_wp import build_cash_recon_schedule
from app.engines.entity_close import is_journal_led_entity, lock_entity_month
from app.engines.intercompany import apply_intercompany_match, find_intercompany_candidates, ic_mirror
from app.engines.journals import post_journal
from app.engines.period_locks import PeriodLockedError, assert_txn_editable
from app.main import app
from app.models import DimAccount, DimEntity, Transaction
from app.services.seed import seed_if_empty

client = TestClient(app)


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def test_binder_signoff_is_entity_scoped():
    db = SessionLocal()
    try:
        can = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
        usa = db.scalar(select(DimEntity).where(DimEntity.code == "USA"))
        assert can and usa
        year, month = 2098, 4
        can_doc = upsert_binder_document(
            db,
            year=year,
            month=month,
            key="pnl_analysis",
            status="reviewed",
            preparer="AC",
            reviewer="RP",
            entity_id=can.id,
        )
        db.commit()
        assert can_doc["status"] == "reviewed"
        usa_doc = get_binder_document(db, year, month, "pnl_analysis", entity_id=usa.id)
        assert usa_doc["status"] != "reviewed"
        assert usa_doc.get("preparer") in (None, "")
    finally:
        db.close()


def test_month_lock_blocks_journal_allows_pca():
    db = SessionLocal()
    try:
        can = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
        expense = db.scalar(select(DimAccount).where(DimAccount.account_type == "expense"))
        ap = db.scalar(select(DimAccount).where(DimAccount.code == "2000"))
        assert can and expense and ap
        year, month = 2097, 5
        lock_entity_month(db, entity_id=can.id, year=year, month=month, actor="AC")
        db.commit()
        try:
            post_journal(
                db,
                txn_date=date(year, month, 31),
                entity_id=can.id,
                description="Too late",
                lines=[
                    {"account_id": expense.id, "debit": "40.00", "credit": "0"},
                    {"account_id": ap.id, "debit": "0", "credit": "40.00"},
                ],
                actor="AC",
            )
            db.commit()
            raised = False
        except PeriodLockedError:
            raised = True
            db.rollback()
        except ValueError as exc:
            raised = "locked" in str(exc).lower()
            db.rollback()
        assert raised

        pca = post_journal(
            db,
            txn_date=date(year, month, 31),
            entity_id=can.id,
            description="Late AP",
            lines=[
                {"account_id": expense.id, "debit": "40.00", "credit": "0"},
                {"account_id": ap.id, "debit": "0", "credit": "40.00"},
            ],
            actor="AC",
            post_close=True,
            reverse_next_month=True,
        )
        db.commit()
        assert pca.source_type == "post_close_adj"
        assert pca.reference.startswith("PCA-2097-05-")
        reverse = db.scalar(select(Transaction).where(Transaction.reference == f"R-{pca.reference}"))
        assert reverse is not None
        assert reverse.txn_date == date(2097, 6, 1)
        loaded = db.get(Transaction, pca.id)
        assert_txn_editable(db, loaded)
    finally:
        db.close()


def test_month_lock_api_and_pca_roundtrip():
    entities = {e["code"]: e for e in client.get("/api/entities").json()}
    accounts = client.get("/api/accounts").json()
    can_id = entities["CAN"]["id"]
    exp = next(a for a in accounts if a["account_type"] == "expense")
    liab = next(a for a in accounts if a["code"] == "2000")
    locked = client.post(
        f"/api/period-locks/lock?entity_id={can_id}&year=2096&month=8",
        headers={"X-Keystone-Actor": "alex"},
    )
    assert locked.status_code == 200, locked.text
    assert locked.json()["is_locked"] is True

    blocked = client.post(
        "/api/journals",
        json={
            "txn_date": "2096-08-31",
            "entity_id": can_id,
            "description": "Should fail",
            "lines": [
                {"account_id": exp["id"], "debit": "12", "credit": "0"},
                {"account_id": liab["id"], "debit": "0", "credit": "12"},
            ],
        },
        headers={"X-Keystone-Actor": "alex"},
    )
    assert blocked.status_code == 400

    pca = client.post(
        "/api/journals",
        json={
            "txn_date": "2096-08-31",
            "entity_id": can_id,
            "description": "PCA after lock",
            "post_close": True,
            "reverse_next_month": False,
            "lines": [
                {"account_id": exp["id"], "debit": "12", "credit": "0"},
                {"account_id": liab["id"], "debit": "0", "credit": "12"},
            ],
        },
        headers={"X-Keystone-Actor": "alex"},
    )
    assert pca.status_code == 200, pca.text
    assert pca.json()["source_type"] == "post_close_adj"
    assert pca.json()["voucher"].startswith("PCA-")


def test_ic_split_legs_match_across_fx():
    db = SessionLocal()
    try:
        can = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
        usa = db.scalar(select(DimEntity).where(DimEntity.code == "USA"))
        ar = db.scalar(select(DimAccount).where(DimAccount.code == "1100"))
        ap = db.scalar(select(DimAccount).where(DimAccount.code == "2000"))
        rev = db.scalar(select(DimAccount).where(DimAccount.code == "4000"))
        exp = db.scalar(select(DimAccount).where(DimAccount.account_type == "expense"))
        assert can and usa and ar and ap and rev and exp
        year, month = 2026, 4
        usa_j = post_journal(
            db,
            txn_date=date(year, month, 20),
            entity_id=usa.id,
            description="Interco AR · monthly rec test",
            lines=[
                {"account_id": ar.id, "debit": "7777.00", "credit": "0"},
                {"account_id": rev.id, "debit": "0", "credit": "7777.00"},
            ],
            actor="AC",
            currency="USD",
            counter_entity_id=can.id,
            working_paper_key="interco",
        )
        # 7777 USD * 1.372 closing = 10,670.44 CAD
        can_j = post_journal(
            db,
            txn_date=date(year, month, 21),
            entity_id=can.id,
            description="Interco AP · monthly rec test",
            lines=[
                {"account_id": exp.id, "debit": "10670.44", "credit": "0"},
                {"account_id": ap.id, "debit": "0", "credit": "10670.44"},
            ],
            actor="AC",
            currency="CAD",
            counter_entity_id=usa.id,
            working_paper_key="interco",
        )
        db.flush()
        matches = find_intercompany_candidates(db)
        pair = next(
            (m for m in matches if {m.left_id, m.right_id} == {usa_j.id, can_j.id}),
            None,
        )
        assert pair is not None
        apply_intercompany_match(db, pair.left_id, pair.right_id, actor="AC")
        db.commit()
        db.refresh(usa_j)
        db.refresh(can_j)
        assert usa_j.intercompany_match_id == can_j.id
        assert can_j.intercompany_match_id == usa_j.id
        mirror = ic_mirror(db, entity_id=usa.id, year=year, month=month)
        assert mirror["currency"] == "CAD"
        assert mirror["is_mirrored"] is True
        assert abs(mirror["difference"]) <= 50
    finally:
        db.close()


def test_usa_cash_wp_na_for_journal_led_month():
    db = SessionLocal()
    try:
        usa = db.scalar(select(DimEntity).where(DimEntity.code == "USA"))
        assert usa
        assert is_journal_led_entity(db, usa.id)
        schedule = build_cash_recon_schedule(db, 2026, 7, entity_id=usa.id)
        assert schedule["journal_led"] is True
        assert schedule["not_applicable"] is True
        assert schedule["is_tied"] is True
        assert schedule["can_prepare"] is True
        assert schedule["reporting_currency"] == "USD"
    finally:
        db.close()


def test_usa_home_is_journal_led_monthly_queue():
    entities = {e["code"]: e for e in client.get("/api/entities").json()}
    usa_id = entities["USA"]["id"]
    home = client.get(f"/api/engagement/home?year=2026&month=7&entity_id={usa_id}")
    assert home.status_code == 200, home.text
    body = home.json()
    assert body["journal_led"] is True
    keys = {q["key"] for q in body["queue"]}
    assert "connect-feeds" not in keys
    assert "lock-month" in keys
    assert any(k.startswith("review-journals") or k == "review-journals" for k in keys)
    assert "daily" not in body["queue"][0]["detail"].lower()
    assert "daily" not in body["queue"][0]["title"].lower()
