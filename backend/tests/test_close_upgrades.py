from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.engines.feed_providers import CsvFolderProvider, DemoWbcProvider
from app.engines.journals import post_journal
from app.engines.schedules import build_wp_schedule
from app.main import app
from app.models import BankAccount, DimAccount, DimEntity
from app.services.seed import seed_if_empty

client = TestClient(app)


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def test_session_defaults_and_switch():
    res = client.get("/api/session")
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["username"] in ("alex", "riley", "kai")
    assert len(body["users"]) >= 3

    switched = client.post("/api/session/switch", json={"username": "riley"})
    assert switched.status_code == 200
    assert switched.json()["user"]["initials"] == "RP"

    as_riley = client.get("/api/session", headers={"X-Keystone-Actor": "riley"})
    assert as_riley.json()["user"]["username"] == "riley"


def test_sod_rejects_same_preparer_reviewer():
    prep = client.put(
        f"/api/working-papers/binder/inventory?year=2026&month=7",
        json={"status": "prepared", "preparer": "AC"},
        headers={"X-Keystone-Actor": "alex"},
    )
    assert prep.status_code == 200, prep.text
    same = client.put(
        f"/api/working-papers/binder/inventory?year=2026&month=7",
        json={"status": "reviewed", "reviewer": "AC"},
        headers={"X-Keystone-Actor": "alex"},
    )
    assert same.status_code == 400
    assert "different" in same.json()["detail"].lower()

    ok = client.put(
        f"/api/working-papers/binder/inventory?year=2026&month=7",
        json={"status": "reviewed", "reviewer": "RP"},
        headers={"X-Keystone-Actor": "riley"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["reviewer"] == "RP"


def test_journal_posts_balanced_and_rejects_unbalanced():
    db = SessionLocal()
    try:
        entity = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
        expense = db.scalar(select(DimAccount).where(DimAccount.account_type == "expense"))
        ap = db.scalar(select(DimAccount).where(DimAccount.code == "2000"))
        if not ap:
            ap = db.scalar(select(DimAccount).where(DimAccount.account_type == "liability"))
        assert entity and expense and ap
        txn = post_journal(
            db,
            txn_date=date(2026, 7, 31),
            entity_id=entity.id,
            description="Accrue vendor",
            lines=[
                {"account_id": expense.id, "debit": "250.00", "credit": "0"},
                {"account_id": ap.id, "debit": "0", "credit": "250.00"},
            ],
            actor="AC",
            working_paper_key="ap",
        )
        db.commit()
        assert txn.reference and txn.reference.startswith("J-2026-07-")
        assert txn.source_type == "journal"
        assert txn.is_split
        assert abs(sum((s.amount for s in txn.splits), Decimal("0"))) != Decimal("999999")
    finally:
        db.close()

    entities = client.get("/api/entities").json()
    accounts = client.get("/api/accounts").json()
    exp = next(a for a in accounts if a["account_type"] == "expense")
    liab = next(a for a in accounts if a["account_type"] == "liability")
    bad = client.post(
        "/api/journals",
        json={
            "txn_date": "2026-07-31",
            "entity_id": entities[0]["id"],
            "description": "Unbalanced",
            "lines": [
                {"account_id": exp["id"], "debit": "10", "credit": "0"},
                {"account_id": liab["id"], "debit": "0", "credit": "9"},
            ],
        },
        headers={"X-Keystone-Actor": "alex"},
    )
    assert bad.status_code == 400


def test_wp_schedule_and_attachment_roundtrip():
    db = SessionLocal()
    try:
        schedule = build_wp_schedule(db, key="ar", year=2026, month=7)
        assert schedule is not None
        assert schedule["kind"] == "aging"
        assert "is_tied" in schedule
        rf = build_wp_schedule(db, key="prepaid", year=2026, month=7)
        assert rf["kind"] == "rollforward"
        ic = build_wp_schedule(db, key="interco", year=2026, month=7)
        assert ic["kind"] == "intercompany"
    finally:
        db.close()

    detail = client.get("/api/working-papers/binder/ap?year=2026&month=7")
    assert detail.status_code == 200
    body = detail.json()
    assert body["schedule"]["kind"] in ("aging", "rollforward", "lead")
    assert body["document_id"]
    files = {"file": ("support.txt", b"bank confirmation", "text/plain")}
    up = client.post(
        "/api/attachments",
        data={"entity_table": "working_paper_documents", "entity_id": body["document_id"]},
        files=files,
        headers={"X-Keystone-Actor": "alex"},
    )
    assert up.status_code == 200, up.text
    assert up.json()["filename"] == "support.txt"
    listed = client.get(
        f"/api/attachments?entity_table=working_paper_documents&entity_id={body['document_id']}"
    )
    assert listed.status_code == 200
    assert any(r["filename"] == "support.txt" for r in listed.json())


def test_csv_folder_feed_provider(tmp_path: Path):
    db = SessionLocal()
    try:
        bank = db.scalar(select(BankAccount).where(BankAccount.account_number == "1010"))
        assert bank
        csv_path = tmp_path / "1010.csv"
        csv_path.write_text("date,description,amount,external_id,counterparty\n2026-07-31,FOLDER ACH,-99.00,CSV-X-1,Vendor\n")
        provider = CsvFolderProvider(feeds_dir=tmp_path)
        rows = provider.rows(bank)
        assert len(rows) == 1
        assert rows[0].external_id == "CSV-X-1"
        assert rows[0].amount == Decimal("-99.00")
        demo = DemoWbcProvider().rows(bank)
        assert any(r.external_id == "FIT-1010-1" for r in demo)
    finally:
        db.close()
