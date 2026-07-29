from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.engines.close_pack import run_statement_close_pack
from app.engines.reconciliation import beginning_balance
from app.main import app
from app.models import BankAccount, DimAccount, DimEntity, DimScenario, Transaction
from app.services.seed import seed_if_empty

client = TestClient(app)


def setup_module():
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def _fresh_bank(db, opening: Decimal = Decimal("1000.00")) -> BankAccount:
    entity = db.scalar(select(DimEntity).limit(1))
    cash = db.scalar(select(DimAccount).where(DimAccount.code == "1000"))
    suf = uuid4().hex[:8]
    bank = BankAccount(
        entity_id=entity.id,
        name=f"Close Pack {suf}",
        account_number=f"CP-{suf}",
        currency="CAD",
        gl_account_id=cash.id if cash else None,
        opening_balance=opening,
    )
    db.add(bank)
    db.flush()
    return bank


def test_close_pack_auto_clears_and_locks_when_clean():
    db = SessionLocal()
    try:
        bank = _fresh_bank(db)
        scenario = db.scalar(select(DimScenario).where(DimScenario.code == "ACTUAL"))
        expense = db.scalar(select(DimAccount).where(DimAccount.code == "6600"))
        year, month = 2040, 3
        txn = Transaction(
            txn_date=date(year, month, 12),
            description="SERVICE CHARGE CLOSE PACK",
            amount=Decimal("-15.00"),
            currency="CAD",
            entity_id=bank.entity_id,
            bank_account_id=bank.id,
            account_id=expense.id,
            scenario_id=scenario.id,
            status="categorized",
            source_type="manual",
        )
        db.add(txn)
        db.commit()
        db.refresh(bank)

        beg = beginning_balance(db, bank.id, year, month)
        statement = beg + txn.amount
        result = run_statement_close_pack(
            db,
            bank_account_id=bank.id,
            period_year=year,
            period_month=month,
            statement_ending_balance=statement,
        )
        db.commit()
        assert result["auto_cleared"] >= 1
        assert result["difference"] == 0.0
        assert result["blocking_count"] == 0
        assert result["can_lock"] is True

        lock = client.post(f"/api/close-pack/{result['reconciliation_id']}/lock")
        assert lock.status_code == 200, lock.text
        assert lock.json()["is_locked"] is True
    finally:
        db.close()


def test_close_pack_surfaces_uncategorized_exception():
    db = SessionLocal()
    try:
        bank = _fresh_bank(db)
        scenario = db.scalar(select(DimScenario).where(DimScenario.code == "ACTUAL"))
        year, month = 2040, 4
        txn = Transaction(
            txn_date=date(year, month, 5),
            description="MYSTERY VENDOR",
            amount=Decimal("-40.00"),
            currency="CAD",
            entity_id=bank.entity_id,
            bank_account_id=bank.id,
            scenario_id=scenario.id,
            status="uncategorized",
            source_type="manual",
        )
        db.add(txn)
        db.commit()
        db.refresh(bank)
        beg = beginning_balance(db, bank.id, year, month)
        result = run_statement_close_pack(
            db,
            bank_account_id=bank.id,
            period_year=year,
            period_month=month,
            statement_ending_balance=beg + txn.amount,
        )
        db.commit()
        kinds = {e["kind"] for e in result["exceptions"]}
        assert "uncategorized" in kinds or "difference" in kinds
        assert result["can_lock"] is False

        accounts = client.get("/api/accounts").json()
        acct = next(a for a in accounts if a["code"] == "5300")
        fixed = client.post(
            f"/api/close-pack/{result['reconciliation_id']}/exceptions/{txn.id}/categorize",
            json={"account_id": acct["id"], "create_rule": True, "clear_after": True},
        )
        assert fixed.status_code == 200, fixed.text
        body = fixed.json()
        assert body["can_lock"] is True
        assert body["blocking_count"] == 0
    finally:
        db.close()


def test_close_pack_run_via_api_multipart():
    # Use a dedicated empty bank so seeded CAN 1010 history does not require prior locks
    db = SessionLocal()
    try:
        bank = _fresh_bank(db)
        db.commit()
        db.refresh(bank)
        bank_id = bank.id
        year, month = 2041, 1
        beg = beginning_balance(db, bank_id, year, month)
    finally:
        db.close()

    res = client.post(
        "/api/close-pack/run",
        data={
            "bank_account_id": str(bank_id),
            "period_year": str(year),
            "period_month": str(month),
            "statement_ending_balance": str(beg),
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reconciliation_id"]
    assert body["period_label"] == "2041-01"


def test_month_overview():
    res = client.get("/api/close-pack/month?year=2041&month=1")
    assert res.status_code == 200
    body = res.json()
    assert body["banks_total"] >= 1
    assert "packs" in body
