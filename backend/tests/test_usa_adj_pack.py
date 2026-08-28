"""WBC USA FY2026 adjusting pack — last year's books on the USA entity."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.engines.adj_pack import USA_ADJ_PATH, ensure_wbc_company_pack, import_adj_pack_path, parse_adj_pack, resolve_gl_code
from app.engines.schedules import build_wp_schedule
from app.main import app
from app.models import DimEntity, Transaction
from app.services.seed import SAMPLE_ROOT, seed_if_empty

client = TestClient(app)


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    ensure_wbc_company_pack(db)
    db.close()


def test_parse_usa_adj_pack():
    pack = parse_adj_pack(USA_ADJ_PATH.read_bytes())
    assert pack.entity_code == "USA"
    assert pack.txn_date and pack.txn_date.isoformat() == "2026-07-31"
    assert [e.entry_no for e in pack.entries] == ["STD-001", "STD-002", "STD-003", "CLASS1"]
    std1 = pack.entries[0]
    assert {resolve_gl_code(l, std1) for l in std1.lines} == {"1100", "4000"}
    class1 = pack.entries[3]
    assert [resolve_gl_code(l, class1) for l in class1.lines] == ["5200", "6600"]


def test_usa_adj_seeded_and_idempotent():
    db = SessionLocal()
    try:
        usa = db.scalar(select(DimEntity).where(DimEntity.code == "USA"))
        assert usa and usa.name == "WBC USA"
        journals = list(
            db.scalars(
                select(Transaction).where(
                    Transaction.entity_id == usa.id,
                    Transaction.source_type == "journal",
                )
            )
        )
        refs = {t.reference for t in journals}
        assert {"STD-001", "STD-002", "STD-003", "CLASS1"} <= refs
        assert all(t.currency == "USD" for t in journals)
        again = import_adj_pack_path(db, USA_ADJ_PATH, entity_id=usa.id, actor="test")
        assert again.imported == 0
        assert again.skipped >= 4
    finally:
        db.close()


def test_usa_ar_ap_schedules_include_adj():
    db = SessionLocal()
    try:
        usa = db.scalar(select(DimEntity).where(DimEntity.code == "USA"))
        ar = build_wp_schedule(db, "ar", 2026, 7, entity_id=usa.id)
        ap = build_wp_schedule(db, "ap", 2026, 7, entity_id=usa.id)
        assert ar["kind"] == "aging"
        assert ap["kind"] == "aging"
        ar_gl = ar.get("gl_amount", ar.get("gl"))
        ap_gl = ap.get("gl_amount", ap.get("gl"))
        assert ar_gl > 0
        assert ap_gl > 0
        # STD-001 Interco AR 38,167.90
        assert abs(ar_gl - 38167.90) < 0.05
        # STD-002 + STD-003 AP 140,996.40 + 38,916.36
        assert abs(ap_gl - (140996.40 + 38916.36)) < 0.05
    finally:
        db.close()


def test_api_adj_pack_dedupes():
    entities = {e["code"]: e for e in client.get("/api/entities").json()}
    assert entities["CAN"]["name"] == "WBC CAN"
    assert entities["USA"]["name"] == "WBC USA"
    path = SAMPLE_ROOT / "synoptic" / "USA_ADJ_FY2026.csv"
    with path.open("rb") as f:
        res = client.post(
            "/api/imports/adj-pack",
            data={"entity_id": str(entities["USA"]["id"])},
            files={"file": ("USA_ADJ.csv", f, "text/csv")},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 0
    assert body["skipped"] >= 4
