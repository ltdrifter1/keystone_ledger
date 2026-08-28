from datetime import date

from fastapi.testclient import TestClient

from app.database import SessionLocal, init_db
from app.engines.engagement import build_engagement_home
from app.main import app
from app.models import DimEntity
from app.services.seed import seed_if_empty
from sqlalchemy import select


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


client = TestClient(app)


def test_engagement_home_engine_entity_scoped():
    db = SessionLocal()
    try:
        can = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
        assert can
        year, month = 2026, 6
        home = build_engagement_home(db, year=year, month=month, entity_id=can.id)
        assert home["entity_code"] == "CAN"
        assert home["period_label"] == "2026-06"
        assert home["work_href"].startswith("/work?")
        assert home["binder_href"].startswith("/binder?")
        assert home["statements_href"].startswith("/statements?")
        assert isinstance(home["queue"], list)
        assert len(home["queue"]) >= 1
        assert "can_print" in home["progress"]
        assert "statements_balanced" in home["progress"]
        for item in home["queue"]:
            assert item["href"].startswith("/")
            assert "/close?" not in item["href"]
            assert "/working-papers?" not in item["href"]
            assert item["phase"] in ("work", "binder", "home")
    finally:
        db.close()


def test_engagement_home_api():
    entities = {e["code"]: e for e in client.get("/api/entities").json()}
    can_id = entities["CAN"]["id"]
    usa_id = entities["USA"]["id"]
    res = client.get(f"/api/engagement/home?year=2026&month=6&entity_id={can_id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["entity_code"] == "CAN"
    assert body["progress"]["banks_total"] >= 1
    assert body["queue"]
    assert body["work_href"].startswith("/work?")

    can_banks = body["progress"]["banks_total"]
    usa = client.get(f"/api/engagement/home?year=2026&month=6&entity_id={usa_id}").json()
    assert usa["entity_code"] == "USA"
    assert usa["progress"]["banks_total"] < can_banks


def test_binder_cash_entity_scoped():
    entities = {e["code"]: e for e in client.get("/api/entities").json()}
    can_id = entities["CAN"]["id"]
    usa_id = entities["USA"]["id"]
    can = client.get(f"/api/working-papers/binder/cash?year=2026&month=6&entity_id={can_id}")
    assert can.status_code == 200, can.text
    can_body = can.json()
    assert can_body["cash_schedule"]["entity_id"] == can_id
    assert can_body["cash_schedule"]["banks_total"] >= 1
    assert all(
        (b.get("entity_code") == "CAN" or b.get("entity_id") == can_id)
        for b in can_body["cash_schedule"]["banks"]
    )

    usa = client.get(f"/api/working-papers/binder/cash?year=2026&month=6&entity_id={usa_id}")
    assert usa.status_code == 200, usa.text
    assert usa.json()["cash_schedule"]["banks_total"] < can_body["cash_schedule"]["banks_total"]
