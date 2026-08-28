"""WBC synoptic mapping + CAN/USA separation tests."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal, init_db
from app.engines.synoptic import parse_synoptic_headers, parse_transfer_target, read_synoptic_csv
from app.main import app
from app.models import BankAccount, DimAccount, DimEntity, Transaction
from app.services.seed import SAMPLE_ROOT, seed_if_empty


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def test_mapping_files_present():
    assert (SAMPLE_ROOT / "mappings" / "wbc_chart_of_accounts.json").exists()
    assert (SAMPLE_ROOT / "mappings" / "wbc_entities_banks.json").exists()
    assert (SAMPLE_ROOT / "synoptic" / "CAN_1010_WBC_JUL-2026.csv").exists()
    assert (SAMPLE_ROOT / "synoptic" / "USA_ADJ_FY2026.csv").exists()


def test_entities_are_can_and_use_separate():
    db = SessionLocal()
    try:
        codes = sorted(db.scalars(select(DimEntity.code)).all())
        assert codes == ["CAN", "USA"]
        can = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
        use = db.scalar(select(DimEntity).where(DimEntity.code == "USA"))
        assert can is not None and use is not None
        assert can.parent_entity_id is None and use.parent_entity_id is None
        assert can.consolidation_method == "none"
        assert use.consolidation_method == "none"
        assert can.functional_currency == "CAD"
        assert use.functional_currency == "USD"
        assert can.name == "WBC CAN"
        assert use.name == "WBC USA"

        can_banks = list(db.scalars(select(BankAccount).where(BankAccount.entity_id == can.id)).all())
        use_banks = list(db.scalars(select(BankAccount).where(BankAccount.entity_id == use.id)).all())
        assert any(b.account_number == "1010" for b in can_banks)
        assert use_banks  # USA operating bank + FY adj journals

        # USA books come from the FY adjusting pack, not the CAN cashbook
        use_txn = db.scalar(
            select(func.count()).select_from(Transaction).where(Transaction.entity_id == use.id)
        )
        assert use_txn and use_txn >= 4
    finally:
        db.close()


def test_coa_matches_synoptic_codes():
    db = SessionLocal()
    try:
        codes = set(db.scalars(select(DimAccount.code)).all())
        for required in ("1000", "1010", "1100", "1200", "1300", "1400", "2000", "2100", "2200", "2300", "2400", "3000", "3100", "4000", "6600"):
            assert required in codes
        # Inventory vs prepaid swapped vs old demo CoA
        inv = db.scalar(select(DimAccount).where(DimAccount.code == "1200"))
        prepaid = db.scalar(select(DimAccount).where(DimAccount.code == "1300"))
        assert inv and "Inventory" in inv.name
        assert prepaid and "Prepaid" in prepaid.name
    finally:
        db.close()


def test_can_1010_synoptic_seeded():
    db = SessionLocal()
    try:
        can = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
        bank = db.scalar(
            select(BankAccount).where(BankAccount.entity_id == can.id, BankAccount.account_number == "1010")
        )
        assert bank is not None
        assert float(bank.opening_balance) == 58735.77
        count = db.scalar(
            select(func.count()).select_from(Transaction).where(Transaction.bank_account_id == bank.id)
        )
        assert count and count >= 2300
        categorized = db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.bank_account_id == bank.id, Transaction.status == "categorized")
        )
        assert categorized and categorized >= 2000
    finally:
        db.close()


def test_synoptic_header_parser():
    path = SAMPLE_ROOT / "synoptic" / "CAN_1010_WBC_JUL-2026.csv"
    rows, columns, meta = read_synoptic_csv(path.read_bytes())
    assert len(columns) >= 40
    assert meta["date"] == 0
    assert any(c.code == "4000" and c.channel == "NOBL" for c in columns)
    headers = parse_synoptic_headers(rows)
    assert headers[0].code == "4000"


def test_transfer_target_parser():
    parsed = parse_transfer_target("CAN 1015 USD$")
    assert parsed["entity_code"] == "CAN"
    assert parsed["gl_code"] == "1015"
    assert parsed["currency"] == "USD"


def test_api_synoptic_import_dedupes():
    client = TestClient(app)
    entities = {e["code"]: e for e in client.get("/api/entities").json()}
    assert "CAN" in entities and "USA" in entities
    banks = client.get("/api/bank-accounts").json()
    can_bank = next(b for b in banks if b["account_number"] == "1010" and b["entity_id"] == entities["CAN"]["id"])
    path = Path(SAMPLE_ROOT / "synoptic" / "CAN_1010_WBC_JUL-2026.csv")
    # Re-import should mostly skip as duplicates
    with path.open("rb") as f:
        res = client.post(
            "/api/imports/synoptic",
            data={"bank_account_id": str(can_bank["id"])},
            files={"file": ("CAN_1010.csv", f, "text/csv")},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 0
    assert body["duplicates_flagged"] > 0 or body["skipped"] > 0
