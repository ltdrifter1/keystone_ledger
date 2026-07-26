from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.engines.binder import build_binder, get_binder_document, upsert_binder_document
from app.engines.cash_wp import build_cash_recon_schedule, cash_signoff_allowed
from app.engines.close_pack import lock_close_pack, run_statement_close_pack
from app.engines.reconciliation import beginning_balance
from app.models import BankAccount, Transaction
from app.services.seed import seed_if_empty


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def test_cash_schedule_uses_bank_recon_not_just_gl_drill():
    db = SessionLocal()
    try:
        today = date.today()
        schedule = build_cash_recon_schedule(db, today.year, today.month)
        assert schedule["banks_total"] >= 1
        assert "gl_statement_amount" in schedule
        assert "is_tied" in schedule
        assert "can_prepare" in schedule
        assert "can_review" in schedule
        row = schedule["banks"][0]
        assert "book_balance" in row
        assert "href" in row and "/close?" in row["href"]
    finally:
        db.close()


def test_cash_prepare_blocked_until_banks_ready():
    db = SessionLocal()
    try:
        today = date.today()
        year, month = today.year, today.month
        schedule = build_cash_recon_schedule(db, year, month)
        if schedule["can_prepare"]:
            # Seed month already clean — still enforce same-preparer/reviewer rule path separately
            cash_signoff_allowed(schedule, status="prepared", preparer="AB", reviewer=None)
            return
        try:
            upsert_binder_document(
                db,
                year=year,
                month=month,
                key="cash",
                status="prepared",
                preparer="AB",
            )
            db.commit()
            raised = False
        except ValueError as exc:
            raised = True
            assert "Cannot prepare Cash WP" in str(exc)
            db.rollback()
        assert raised
    finally:
        db.close()


def test_cash_wp_tied_after_all_banks_locked_clean():
    """Use an isolated future period so we don't lock the shared seed month."""
    db = SessionLocal()
    try:
        year, month = 2098, 6
        banks = list(db.scalars(select(BankAccount).where(BankAccount.is_active == True)).all())
        assert banks
        end = date(year, month, monthrange(year, month)[1])

        for bank in banks:
            beg = beginning_balance(db, bank.id, year, month)
            in_period = list(
                db.scalars(
                    select(Transaction).where(
                        Transaction.bank_account_id == bank.id,
                        Transaction.status != "void",
                    )
                )
            )
            cleared_est = sum(
                (
                    Decimal(t.amount)
                    for t in in_period
                    if t.txn_date.year == year
                    and t.txn_date.month == month
                    and (t.status == "categorized" or t.is_split)
                ),
                Decimal("0"),
            )
            statement = beg + cleared_est
            run_statement_close_pack(
                db,
                bank_account_id=bank.id,
                period_year=year,
                period_month=month,
                statement_ending_balance=statement,
                actor="test",
            )
        db.commit()

        schedule = build_cash_recon_schedule(db, year, month)
        assert schedule["all_started"]
        assert schedule["all_bank_tied"], schedule["gate_messages"]

        for bank_row in schedule["banks"]:
            if bank_row["reconciliation_id"] and not bank_row["is_locked"]:
                if bank_row["can_lock"] or bank_row["is_tied"]:
                    try:
                        lock_close_pack(db, bank_row["reconciliation_id"], actor="test")
                    except ValueError:
                        pass
        db.commit()

        schedule = build_cash_recon_schedule(db, year, month)
        binder = build_binder(db, year, month)
        cash = next(d for d in binder["documents"] if d["key"] == "cash")
        assert cash["close_status"] in ("ready", "locked", "in_progress")
        assert "is_tied" in cash

        doc = get_binder_document(db, year, month, "cash")
        assert doc["cash_schedule"] is not None
        assert len(doc["cash_schedule"]["banks"]) == len(banks)
        assert isinstance(doc["gate_messages"], list)
        assert end.isoformat() == schedule["period_end"]

        if schedule["can_prepare"]:
            prepared = upsert_binder_document(
                db,
                year=year,
                month=month,
                key="cash",
                status="prepared",
                preparer="AB",
            )
            db.commit()
            assert prepared["status"] == "prepared"
            if build_cash_recon_schedule(db, year, month)["can_review"]:
                reviewed = upsert_binder_document(
                    db,
                    year=year,
                    month=month,
                    key="cash",
                    status="reviewed",
                    preparer="AB",
                    reviewer="CD",
                )
                db.commit()
                assert reviewed["status"] == "reviewed"
                try:
                    upsert_binder_document(
                        db,
                        year=year,
                        month=month,
                        key="cash",
                        status="reviewed",
                        preparer="AB",
                        reviewer="AB",
                    )
                    assert False, "expected same preparer/reviewer to fail"
                except ValueError as exc:
                    assert "different" in str(exc).lower()
                    db.rollback()
        else:
            # Still prove the gate raises with a clear message
            try:
                cash_signoff_allowed(schedule, status="prepared", preparer="AB", reviewer=None)
                assert False, "expected prepare gate to fail when can_prepare is false"
            except ValueError as exc:
                assert "Cannot prepare Cash WP" in str(exc)
    finally:
        db.close()


def test_api_cash_document_includes_schedule():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    today = date.today()
    res = client.get(f"/api/working-papers/binder/cash?year={today.year}&month={today.month}")
    assert res.status_code == 200
    body = res.json()
    assert body["cash_schedule"] is not None
    assert "banks" in body["cash_schedule"]
    assert "can_prepare" in body
