"""Bank inbox: mark Transfer / Intercompany, editable rules, visible FX rates."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.engines.fx import persistable_fx, translate_amount
from app.engines.importing import BankImportRow, import_bank_rows
from app.engines.rules import payee_token
from app.main import app
from app.models import DimEntity, Transaction
from app.services.seed import seed_if_empty

client = TestClient(app)


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def _by_code(rows, code):
    return next(r for r in rows if r["code"] == code)


def test_payee_token_skips_sweep_noise():
    txn = Transaction(
        txn_date=date(2026, 7, 1),
        description="SCOTIABANK SWEEP TO USD OPERATING",
        amount=Decimal("-1"),
        currency="CAD",
        entity_id=1,
        scenario_id=1,
        status="uncategorized",
    )
    assert payee_token(txn) == "SCOTIABANK"
    txn.counterparty = "STRIPE"
    txn.description = "SWEEP TO OPERATING"
    assert payee_token(txn) == "STRIPE"


def test_mark_transfer_posts_to_gl_1000_and_rule_is_entity_wide():
    entities = client.get("/api/entities").json()
    can = _by_code(entities, "CAN")
    banks = [b for b in client.get("/api/bank-accounts").json() if b["entity_id"] == can["id"]]
    assert len(banks) >= 2
    created = client.post(
        "/api/transactions",
        json={
            "txn_date": "2026-07-15",
            "description": "SCOTIABANK SWEEP TO USD OPERATING",
            "amount": "-500.00",
            "currency": "CAD",
            "entity_id": can["id"],
            "bank_account_id": banks[0]["id"],
            "scenario_id": 1,
        },
    )
    assert created.status_code == 200
    txn_id = created.json()["id"]

    res = client.post(
        f"/api/transactions/{txn_id}/mark-transfer",
        json={"create_rule": True, "other_bank_account_id": banks[1]["id"]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "categorized"
    accounts = {a["id"]: a for a in client.get("/api/accounts").json()}
    assert accounts[body["account_id"]]["code"] == "1000"

    rules = client.get("/api/rules").json()
    transfer = next(
        r
        for r in rules
        if r["name"].startswith("Transfer:")
        and r["assign_account_id"] == body["account_id"]
        and (r.get("match_description_contains") or "").upper() == "SCOTIABANK"
    )
    assert transfer["match_bank_account_id"] is None
    assert transfer["match_entity_id"] == can["id"]
    assert transfer["rule_kind"] == "bank_transfer"


def test_mark_intercompany_posts_to_2100_and_rule_kind():
    entities = client.get("/api/entities").json()
    can = _by_code(entities, "CAN")
    usa = _by_code(entities, "USA")
    can_banks = [b for b in client.get("/api/bank-accounts").json() if b["entity_id"] == can["id"]]

    can_txn = client.post(
        "/api/transactions",
        json={
            "txn_date": "2026-07-16",
            "description": "WBCUSA IC LEG ALPHA",
            "amount": "-4242.42",
            "currency": "CAD",
            "entity_id": can["id"],
            "bank_account_id": can_banks[0]["id"],
            "scenario_id": 1,
        },
    )
    assert can_txn.status_code == 200
    can_id = can_txn.json()["id"]

    same = client.post(
        f"/api/transactions/{can_id}/mark-intercompany",
        json={"counter_entity_id": can["id"], "create_rule": False},
    )
    assert same.status_code == 400

    marked_can = client.post(
        f"/api/transactions/{can_id}/mark-intercompany",
        json={"counter_entity_id": usa["id"], "create_rule": True},
    )
    assert marked_can.status_code == 200, marked_can.text
    body = marked_can.json()
    assert body["status"] == "categorized"
    assert body["counter_entity_id"] == usa["id"]
    accounts = {a["id"]: a for a in client.get("/api/accounts").json()}
    assert accounts[body["account_id"]]["code"] == "2100"

    rules = client.get("/api/rules").json()
    ic = next(r for r in rules if r["name"].startswith("Intercompany:") and r["assign_counter_entity_id"] == usa["id"])
    assert ic["match_bank_account_id"] is None
    assert ic["rule_kind"] == "intercompany"
    assert (ic.get("match_description_contains") or "").upper() == "WBCUSA"


def test_ic_matcher_pairs_opposite_legs():
    from app.engines.inbox import mark_intercompany
    from app.models import BankAccount, DimAccount

    db = SessionLocal()
    try:
        can = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
        usa = db.scalar(select(DimEntity).where(DimEntity.code == "USA"))
        can_bank = db.scalar(select(BankAccount).where(BankAccount.entity_id == can.id))
        usa_bank = db.scalar(select(BankAccount).where(BankAccount.entity_id == usa.id))
        ic_acct = db.scalar(select(DimAccount).where(DimAccount.code == "2100"))
        assert can_bank and usa_bank and ic_acct
        left = Transaction(
            txn_date=date(2026, 7, 16),
            description="MATCHER LEFT WBCUSA",
            amount=Decimal("-88881.17"),
            currency="CAD",
            entity_id=can.id,
            bank_account_id=can_bank.id,
            scenario_id=1,
            status="uncategorized",
        )
        right = Transaction(
            txn_date=date(2026, 7, 16),
            description="MATCHER RIGHT WBCUSA",
            amount=Decimal("88881.17"),
            currency="CAD",
            entity_id=usa.id,
            bank_account_id=usa_bank.id,
            scenario_id=1,
            status="uncategorized",
        )
        db.add_all([left, right])
        db.flush()
        mark_intercompany(db, left, counter_entity_id=usa.id, create_rule=False, actor="test")
        mark_intercompany(db, right, counter_entity_id=can.id, create_rule=False, actor="test")
        assert left.account_id == ic_acct.id
        assert right.account_id == ic_acct.id
        assert left.intercompany_match_id == right.id
        assert right.intercompany_match_id == left.id
    finally:
        db.rollback()
        db.close()


def test_rules_patch_preview_and_delete():
    accounts = client.get("/api/accounts").json()
    cash = next(a for a in accounts if a["code"] == "1000")
    created = client.post(
        "/api/rules",
        json={
            "name": "Inbox editor test",
            "priority": 40,
            "rule_kind": "bank_transfer",
            "match_description_contains": "INBOXEDITTOKEN",
            "assign_account_id": cash["id"],
        },
    )
    assert created.status_code == 200
    assert created.json()["rule_kind"] == "bank_transfer"
    rid = created.json()["id"]
    patched = client.patch(f"/api/rules/{rid}", json={"priority": 7, "is_active": False})
    assert patched.status_code == 200, patched.text
    assert patched.json()["priority"] == 7
    assert patched.json()["is_active"] is False
    assert patched.json()["name"] == "Inbox editor test"

    entities = client.get("/api/entities").json()
    can = _by_code(entities, "CAN")
    banks = [b for b in client.get("/api/bank-accounts").json() if b["entity_id"] == can["id"]]
    client.post(
        "/api/transactions",
        json={
            "txn_date": "2026-07-17",
            "description": "INBOXEDITTOKEN history line",
            "amount": "-3.00",
            "currency": "CAD",
            "entity_id": can["id"],
            "bank_account_id": banks[0]["id"],
            "scenario_id": 1,
        },
    )
    preview = client.post("/api/rules/preview", json={"rule_id": rid, "uncategorized_only": True})
    assert preview.status_code == 200, preview.text
    assert preview.json()["matched_uncategorized"] >= 1

    deleted = client.delete(f"/api/rules/{rid}")
    assert deleted.status_code == 200
    assert all(r["id"] != rid for r in client.get("/api/rules").json())


def test_fx_rates_list_and_inbox_status():
    rows = client.get("/api/fx-rates").json()
    assert rows
    assert any(r["from_currency"] == "USD" and r["to_currency"] == "CAD" for r in rows)
    entities = {e["code"]: e for e in client.get("/api/entities").json()}
    status = client.get(
        f"/api/fx-rates/status?entity_id={entities['CAN']['id']}&year=2026&month=7"
    )
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["functional_currency"] == "CAD"
    assert any(p["rate_type"] == "closing" and p["used_for"].startswith("BS") for p in body["pairs"])
    assert any(p["rate_type"] == "average" and p["used_for"] == "P&L" for p in body["pairs"])


def test_import_does_not_store_silent_one_to_one():
    db = SessionLocal()
    try:
        can = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
        banks = client.get("/api/bank-accounts").json()
        can_bank = next(b for b in banks if b["entity_id"] == can.id)
        missing = translate_amount(
            db,
            amount=Decimal("10"),
            from_currency="GBP",
            to_currency="CAD",
            as_of=date(2026, 7, 18),
            rate_type="closing",
        )
        assert missing.missing is True
        amount, rate = persistable_fx(missing)
        assert amount is None and rate is None

        result = import_bank_rows(
            db,
            bank_account_id=can_bank["id"],
            rows=[
                BankImportRow(
                    txn_date=date(2026, 7, 18),
                    description="GBP WIRE MISSINGFXPAIR",
                    amount=Decimal("-10.00"),
                    currency="GBP",
                )
            ],
            actor="test",
        )
        db.commit()
        assert result.imported == 1
        txn = db.scalar(select(Transaction).where(Transaction.description == "GBP WIRE MISSINGFXPAIR"))
        assert txn is not None
        assert txn.fx_rate is None
        assert txn.amount_reporting is None
    finally:
        db.close()

    listed = client.get("/api/transactions?search=MISSINGFXPAIR&uncategorized_only=true").json()
    assert listed
    assert listed[0]["fx_missing"] is True
    assert listed[0]["fx_rate"] is None
    status = client.get(f"/api/fx-rates/status?entity_id={listed[0]['entity_id']}&year=2026&month=7")
    assert status.status_code == 200
    body = status.json()
    assert any(p.startswith("GBP→CAD") for p in body["missing_pairs"])
    assert body["can_print"] is False
    assert body["inbox_missing_count"] >= 1
    db = SessionLocal()
    try:
        leftover = db.scalar(select(Transaction).where(Transaction.description == "GBP WIRE MISSINGFXPAIR"))
        if leftover:
            db.delete(leftover)
            db.commit()
    finally:
        db.close()
