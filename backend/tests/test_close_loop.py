"""Monthly close loop: categorize → reconcile → lock → hard gate."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.engines.period_locks import PeriodLockedError, assert_txn_editable
from app.engines.reconciliation import (
    beginning_balance,
    complete_reconciliation,
    create_reconciliation,
    set_cleared,
)
from app.main import app
from app.models import BankAccount, DimAccount, DimEntity, DimScenario, Transaction
from app.services.seed import seed_if_empty

client = TestClient(app)


def setup_module():
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def _fresh_bank(db, label: str) -> BankAccount:
    entity = db.scalar(select(DimEntity).limit(1))
    cash = db.scalar(select(DimAccount).where(DimAccount.code == "1000"))
    suffix = uuid4().hex[:8]
    bank = BankAccount(
        entity_id=entity.id,
        name=f"Test Bank {label} {suffix}",
        account_number=f"T-{suffix}",
        currency="CAD",
        institution="Test",
        gl_account_id=cash.id if cash else None,
        opening_balance=Decimal("1000.00"),
    )
    db.add(bank)
    db.flush()
    return bank


def test_beginning_balance_uses_opening_when_no_prior_lock():
    db = SessionLocal()
    try:
        bank = _fresh_bank(db, "beg")
        db.commit()
        beg = beginning_balance(db, bank.id, 2030, 1)
        assert beg == Decimal("1000.00")
    finally:
        db.close()


def test_reconcile_tie_and_lock_then_block_edits():
    db = SessionLocal()
    try:
        bank = _fresh_bank(db, "lock")
        account = db.scalar(select(DimAccount).where(DimAccount.code == "6600"))
        scenario = db.scalar(select(DimScenario).where(DimScenario.code == "ACTUAL"))
        year, month = 2031, 2

        txn = Transaction(
            txn_date=date(year, month, 10),
            description="CLOSE LOOP FEE",
            amount=Decimal("-25.00"),
            currency="CAD",
            entity_id=bank.entity_id,
            bank_account_id=bank.id,
            account_id=account.id,
            scenario_id=scenario.id,
            status="categorized",
            source_type="manual",
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)
        db.refresh(bank)

        beg = beginning_balance(db, bank.id, year, month)
        assert beg == Decimal("1000.00")
        statement = beg + txn.amount  # 975.00

        recon = create_reconciliation(
            db,
            bank_account_id=bank.id,
            period_year=year,
            period_month=month,
            statement_ending_balance=statement,
        )
        db.flush()
        set_cleared(db, recon, [txn.id], True)
        assert Decimal(recon.difference or 0) == Decimal("0")
        complete_reconciliation(db, recon, lock=True)
        db.commit()
        db.refresh(txn)
        db.refresh(recon)

        assert recon.status == "locked"
        assert txn.is_reconciled is True

        try:
            assert_txn_editable(db, txn, changing_fields={"amount"})
            raised = False
        except PeriodLockedError:
            raised = True
        assert raised

        res = client.patch(f"/api/transactions/{txn.id}", json={"amount": "-11.00"})
        assert res.status_code == 409
    finally:
        db.close()


def test_cannot_lock_with_difference():
    db = SessionLocal()
    try:
        bank = _fresh_bank(db, "diff")
        db.commit()
        recon = create_reconciliation(
            db,
            bank_account_id=bank.id,
            period_year=2032,
            period_month=1,
            statement_ending_balance=Decimal("999999.99"),
        )
        db.commit()
        try:
            complete_reconciliation(db, recon, lock=True)
            assert False, "should have failed"
        except ValueError as exc:
            assert "difference" in str(exc).lower()
    finally:
        db.close()


def test_cannot_lock_uncategorized_cleared():
    db = SessionLocal()
    try:
        bank = _fresh_bank(db, "uncat")
        scenario = db.scalar(select(DimScenario).where(DimScenario.code == "ACTUAL"))
        year, month = 2033, 4
        txn = Transaction(
            txn_date=date(year, month, 5),
            description="UNCATEGORIZED CLOSE ITEM",
            amount=Decimal("-5.00"),
            currency="CAD",
            entity_id=bank.entity_id,
            bank_account_id=bank.id,
            scenario_id=scenario.id,
            status="uncategorized",
            source_type="manual",
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)

        statement = beginning_balance(db, bank.id, year, month) + txn.amount
        recon = create_reconciliation(
            db,
            bank_account_id=bank.id,
            period_year=year,
            period_month=month,
            statement_ending_balance=statement,
        )
        set_cleared(db, recon, [txn.id], True)
        db.commit()
        try:
            complete_reconciliation(db, recon, lock=True)
            assert False, "should block uncategorized"
        except ValueError as exc:
            assert "uncategorized" in str(exc).lower()
    finally:
        db.close()


def test_workspace_endpoint():
    db = SessionLocal()
    try:
        bank = _fresh_bank(db, "ws")
        db.commit()
        recon = create_reconciliation(
            db,
            bank_account_id=bank.id,
            period_year=2034,
            period_month=1,
            statement_ending_balance=Decimal("1000.00"),
        )
        db.commit()
        rid = recon.id
    finally:
        db.close()

    res = client.get(f"/api/reconciliations/{rid}/workspace")
    assert res.status_code == 200
    body = res.json()
    assert body["beginning_balance"] == 1000.0
    assert body["difference"] == 0.0
    assert body["can_lock"] is True


def test_inline_categorize_and_split_api():
    # Ensure an editable uncategorized txn exists
    banks = client.get("/api/bank-accounts").json()
    bank_id = banks[0]["id"]
    entities = client.get("/api/entities").json()
    create = client.post(
        "/api/transactions",
        json={
            "txn_date": "2035-05-01",
            "description": "INLINE CAT TARGET",
            "amount": "-40.00",
            "currency": "CAD",
            "entity_id": entities[0]["id"],
            "bank_account_id": bank_id,
            "scenario_id": 1,
            "source_type": "manual",
        },
    )
    assert create.status_code == 200, create.text
    txn_id = create.json()["id"]

    accounts = client.get("/api/accounts").json()
    a1 = next(a for a in accounts if a["code"] == "6500")
    a2 = next(a for a in accounts if a["code"] == "6600")

    cat = client.post(
        f"/api/transactions/{txn_id}/categorize",
        json={"account_id": a1["id"], "create_rule": False},
    )
    assert cat.status_code == 200
    assert cat.json()["account_id"] == a1["id"]

    split = client.post(
        f"/api/transactions/{txn_id}/split",
        json={
            "splits": [
                {"account_id": a1["id"], "amount": "-25.00"},
                {"account_id": a2["id"], "amount": "-15.00"},
            ]
        },
    )
    assert split.status_code == 200, split.text
    assert split.json()["is_split"] is True
    assert len(split.json()["splits"]) == 2
