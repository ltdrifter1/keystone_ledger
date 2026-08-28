"""Bank inbox: mark Transfer / Intercompany, editable rules, visible FX rates."""

from fastapi.testclient import TestClient

from app.database import SessionLocal, init_db
from app.main import app
from app.services.seed import seed_if_empty

client = TestClient(app)


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def _by_code(rows, code):
    return next(r for r in rows if r["code"] == code)


def test_mark_transfer_posts_to_gl_1000_and_rule_is_entity_wide():
    entities = client.get("/api/entities").json()
    can = _by_code(entities, "CAN")
    banks = [b for b in client.get("/api/bank-accounts").json() if b["entity_id"] == can["id"]]
    assert len(banks) >= 2
    created = client.post(
        "/api/transactions",
        json={
            "txn_date": "2026-07-15",
            "description": "SWEEP TO USD OPERATING",
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
        and (r.get("match_description_contains") or "").upper() == "OPERATING"
    )
    assert transfer["match_bank_account_id"] is None
    assert transfer["match_entity_id"] == can["id"]


def test_mark_intercompany_posts_to_2100_and_sets_counter_entity():
    entities = client.get("/api/entities").json()
    can = _by_code(entities, "CAN")
    usa = _by_code(entities, "USA")
    banks = [b for b in client.get("/api/bank-accounts").json() if b["entity_id"] == can["id"]]
    created = client.post(
        "/api/transactions",
        json={
            "txn_date": "2026-07-16",
            "description": "FUNDING WBC USA",
            "amount": "-1200.00",
            "currency": "CAD",
            "entity_id": can["id"],
            "bank_account_id": banks[0]["id"],
            "scenario_id": 1,
        },
    )
    assert created.status_code == 200
    txn_id = created.json()["id"]

    same = client.post(
        f"/api/transactions/{txn_id}/mark-intercompany",
        json={"counter_entity_id": can["id"], "create_rule": False},
    )
    assert same.status_code == 400

    res = client.post(
        f"/api/transactions/{txn_id}/mark-intercompany",
        json={"counter_entity_id": usa["id"], "create_rule": True},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "categorized"
    assert body["counter_entity_id"] == usa["id"]
    accounts = {a["id"]: a for a in client.get("/api/accounts").json()}
    assert accounts[body["account_id"]]["code"] == "2100"

    rules = client.get("/api/rules").json()
    ic = next(r for r in rules if r["name"].startswith("Intercompany:") and r["assign_counter_entity_id"] == usa["id"])
    assert ic["match_bank_account_id"] is None
    assert ic["assign_account_id"] == body["account_id"]


def test_rules_patch_and_delete_persist():
    accounts = client.get("/api/accounts").json()
    cash = next(a for a in accounts if a["code"] == "1000")
    created = client.post(
        "/api/rules",
        json={
            "name": "Inbox editor test",
            "priority": 40,
            "match_description_contains": "INBOXEDITTOKEN",
            "assign_account_id": cash["id"],
        },
    )
    assert created.status_code == 200
    rid = created.json()["id"]
    patched = client.patch(f"/api/rules/{rid}", json={"priority": 7, "is_active": False})
    assert patched.status_code == 200, patched.text
    assert patched.json()["priority"] == 7
    assert patched.json()["is_active"] is False
    assert patched.json()["name"] == "Inbox editor test"
    listed = next(r for r in client.get("/api/rules").json() if r["id"] == rid)
    assert listed["priority"] == 7
    assert listed["is_active"] is False
    deleted = client.delete(f"/api/rules/{rid}")
    assert deleted.status_code == 200
    assert all(r["id"] != rid for r in client.get("/api/rules").json())


def test_fx_rates_list_usd_cad():
    rows = client.get("/api/fx-rates").json()
    assert rows
    assert any(r["from_currency"] == "USD" and r["to_currency"] == "CAD" for r in rows)
    assert any(r["rate_type"] in ("spot", "average", "closing") for r in rows)
