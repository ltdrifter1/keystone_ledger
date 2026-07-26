from datetime import date

from app.database import SessionLocal, init_db
from app.engines.binder import build_binder, get_binder_document, upsert_binder_document
from app.services.seed import seed_if_empty


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def test_binder_index_has_all_sections():
    db = SessionLocal()
    try:
        today = date.today()
        binder = build_binder(db, today.year, today.month)
        keys = {d["key"] for d in binder["documents"]}
        assert "cash" in keys
        assert "pnl_analysis" in keys
        assert binder["summary"]["total"] == 11
        cash = next(d for d in binder["documents"] if d["key"] == "cash")
        assert cash["wp_ref"]
        assert cash["line_code"]
        assert "href" in cash
        assert cash["report_href"].startswith("/reports?")
    finally:
        db.close()


def test_binder_signoff_persists():
    db = SessionLocal()
    try:
        today = date.today()
        year, month = today.year, today.month
        doc = upsert_binder_document(
            db,
            year=year,
            month=month,
            key="cash",
            checked=[0, 1],
            preparer="AB",
            notes="Tie-out complete",
            status="prepared",
        )
        db.commit()
        assert doc["status"] == "prepared"
        assert doc["preparer"] == "AB"
        assert 0 in doc["checked"] and 1 in doc["checked"]

        reviewed = upsert_binder_document(
            db,
            year=year,
            month=month,
            key="cash",
            reviewer="CD",
            status="reviewed",
        )
        db.commit()
        assert reviewed["status"] == "reviewed"
        assert reviewed["reviewer"] == "CD"

        again = get_binder_document(db, year, month, "cash")
        assert again["notes"] == "Tie-out complete"
        assert again["status"] == "reviewed"
    finally:
        db.close()


def test_api_binder_endpoints():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    today = date.today()
    res = client.get(f"/api/working-papers/binder?year={today.year}&month={today.month}")
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["total"] == 11
    assert body["documents"][0]["wp_ref"]

    key = body["documents"][0]["key"]
    detail = client.get(
        f"/api/working-papers/binder/{key}?year={today.year}&month={today.month}"
    )
    assert detail.status_code == 200
    assert "procedures" in detail.json()

    upd = client.put(
        f"/api/working-papers/binder/ar?year={today.year}&month={today.month}",
        json={"checked": [0], "preparer": "XY", "status": "prepared"},
    )
    assert upd.status_code == 200
    assert upd.json()["preparer"] == "XY"

    dash = client.get("/api/dashboard?reporting_currency=CAD")
    assert dash.status_code == 200
    assert dash.json()["binder_summary"]["total"] == 11
