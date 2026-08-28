"""Official simple reporting pack: TB, equity roll, notes, scope, no fake CF."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal, init_db
from app.engines.reporting import build_analytics_pack, cashbook_book_cash
from app.engines.statement_pack import (
    SCOPE_ERROR,
    build_official_report,
    build_statement_diagnostics,
    build_trial_balance,
)
from app.engines.working_papers import find_template, list_templates
from app.main import app
from app.models import DimEntity, Transaction
from app.schemas.reports import ReportFilter
from app.services.seed import seed_if_empty

client = TestClient(app)


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    db.close()


def _entities(db):
    can = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
    usa = db.scalar(select(DimEntity).where(DimEntity.code == "USA"))
    assert can and usa
    return can, usa


def _cashbook_is_clean(db, entity_id: int, as_of: date) -> bool:
    extra = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(
            Transaction.entity_id == entity_id,
            Transaction.source_type.notin_(["synoptic_import"]),
            Transaction.status.notin_(["void", "excluded"]),
            Transaction.txn_date <= as_of,
            Transaction.scenario_id == 1,
        )
    )
    return int(extra or 0) == 0


def _can_filters(can_id: int, report_type: str = "balance_sheet") -> ReportFilter:
    as_of = date(2026, 7, 31)
    return ReportFilter(
        report_type=report_type,
        year=2026,
        month=7,
        scenario_id=1,
        reporting_currency="CAD",
        entity_ids=[can_id],
        as_of_date=as_of,
        date_to=as_of,
        consolidate=False,
        compare_prior_year=True,
        compare_prior_period=False,
        compare_budget=False,
    )


def test_trial_balance_maps_cash_gl_and_interbank():
    db = SessionLocal()
    try:
        can, _usa = _entities(db)
        filters = _can_filters(can.id)
        tb = build_trial_balance(db, filters)
        by_code = {row.account_code: row for row in tb.rows}
        assert "CASH" not in by_code
        assert tb.is_balanced is True
        cash_rows = [r for r in tb.rows if r.line_code == "BS_CASH"]
        assert cash_rows
        book, _, _ = cashbook_book_cash(db, filters)
        cash_net = sum((r.debit - r.credit for r in cash_rows), Decimal("0"))
        assert abs(cash_net - book) < Decimal("0.05")
        if "1090" in by_code:
            assert by_code["1090"].line_code == "BS_CASH_XFER"
        assert tb.notes
    finally:
        db.close()


def test_equity_roll_closes_to_bs_total_equity():
    db = SessionLocal()
    try:
        can, _usa = _entities(db)
        eq = build_official_report(db, _can_filters(can.id, "equity"))
        by_code = {line.line_code: line for line in eq.lines}
        assert eq.title == "Statement of Changes in Equity"
        assert by_code["EQ_OPENING"].line_label == "Opening equity"
        assert by_code["EQ_EARNINGS"].line_label == "Current earnings"
        assert "EQ_CLOSING" in by_code
        bs = build_official_report(db, _can_filters(can.id, "balance_sheet"))
        tot = next(line for line in bs.lines if line.line_code == "BS_TOT_EQUITY")
        assert abs(by_code["EQ_CLOSING"].amount - tot.amount) < Decimal("0.02")
        assert eq.notes
        assert eq.pack_disclaimer
        assert "prior_year" in eq.columns
    finally:
        db.close()


def test_cash_flow_endpoint_is_gone():
    res = client.get("/api/reports/cash-flow")
    assert res.status_code == 410
    assert "not part of this pack" in res.json()["detail"].lower()


def test_official_run_refuses_mixed_entities():
    entities = {e["code"]: e for e in client.get("/api/entities").json()}
    mixed = client.post(
        "/api/reports/run",
        json={
            "report_type": "income_statement",
            "period": "ytd",
            "year": 2026,
            "month": 7,
            "entity_ids": [entities["CAN"]["id"], entities["USA"]["id"]],
            "reporting_currency": "CAD",
        },
    )
    assert mixed.status_code == 400
    assert "one entity" in mixed.json()["detail"].lower()

    none = client.post(
        "/api/reports/run",
        json={
            "report_type": "balance_sheet",
            "year": 2026,
            "month": 7,
            "entity_ids": None,
            "reporting_currency": "CAD",
        },
    )
    assert none.status_code == 400
    assert SCOPE_ERROR.split("—")[0].strip()[:20].lower() in none.json()["detail"].lower() or "one entity" in none.json()["detail"].lower()


def test_diagnostics_and_can_print_on_clean_cashbook():
    db = SessionLocal()
    try:
        can, _usa = _entities(db)
        as_of = date(2026, 7, 31)
        diag = build_statement_diagnostics(db, _can_filters(can.id))
        assert diag.plugs is not None
        assert diag.statements_href
        assert diag.trial_balance_href
        if _cashbook_is_clean(db, can.id, as_of):
            assert diag.is_balanced is True
            assert diag.can_print is True
            assert diag.plugs == []
    finally:
        db.close()


def test_official_report_has_notes_and_prior_year_default_in_pack():
    db = SessionLocal()
    try:
        can, _usa = _entities(db)
        pnl = build_official_report(db, _can_filters(can.id, "income_statement"))
        assert pnl.notes
        assert any("Fiscal year" in n.heading for n in pnl.notes)
        assert pnl.pack_disclaimer
        pack = build_analytics_pack(db, _can_filters(can.id, "income_statement"))
        types = {s.report_type for s in pack.statements}
        assert types == {"income_statement", "balance_sheet", "equity"}
        assert all(s.report_type != "cash_flow" for s in pack.statements)
        assert pack.notes
        assert pack.pack_disclaimer
        is_stmt = next(s for s in pack.statements if s.report_type == "income_statement")
        assert "prior_year" in is_stmt.columns
        assert "budget" not in is_stmt.columns
        assert "prior_period" not in is_stmt.columns
    finally:
        db.close()


def test_trial_balance_api_and_diagnostics_api():
    entities = {e["code"]: e for e in client.get("/api/entities").json()}
    can_id = entities["CAN"]["id"]
    payload = {
        "report_type": "trial_balance",
        "year": 2026,
        "month": 7,
        "entity_ids": [can_id],
        "reporting_currency": "CAD",
        "as_of_date": "2026-07-31",
    }
    tb = client.post("/api/reports/trial-balance", json=payload)
    assert tb.status_code == 200, tb.text
    body = tb.json()
    codes = {row["account_code"] for row in body["rows"]}
    assert "CASH" not in codes
    assert body["is_balanced"] is True

    diag = client.post("/api/reports/diagnostics", json={**payload, "report_type": "balance_sheet"})
    assert diag.status_code == 200, diag.text
    assert "can_print" in diag.json()
    assert "plugs" in diag.json()


def test_binder_still_has_eleven_templates():
    assert len(list_templates()) == 11
    assert find_template(line_code="EQ_OPENING").key == "equity"
    assert find_template(line_code="EQ_CLOSING").wp_ref == "E.1"
    cash = find_template(line_code="BS_CASH")
    assert "is_cash" in cash.tie_out.lower() or "cash gl" in cash.tie_out.lower()


def test_usa_equity_roll_from_journals():
    db = SessionLocal()
    try:
        _can, usa = _entities(db)
        eq = build_official_report(
            db,
            ReportFilter(
                report_type="equity",
                year=2026,
                month=7,
                scenario_id=1,
                reporting_currency="USD",
                entity_ids=[usa.id],
                as_of_date=date(2026, 7, 31),
                date_to=date(2026, 7, 31),
            ),
        )
        by_code = {line.line_code: line for line in eq.lines}
        assert "EQ_CLOSING" in by_code
        assert "journal" in (eq.accounting_basis or "").lower() or "double-entry" in (eq.accounting_basis or "").lower() or "Accrual" in (eq.accounting_basis or "")
    finally:
        db.close()
