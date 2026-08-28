"""Simple financial reporting: fiscal YTD, current earnings, IC split, no fake CF."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal, init_db
from app.engines.drilldown import drill_report_line
from app.engines.fx import lookup_rate, translate_amount
from app.engines.reporting import (
    CURRENT_EARNINGS_CODE,
    _period_bounds,
    build_analytics_pack,
    build_report,
    cashbook_book_cash,
    fiscal_year_start,
    period_label,
)
from app.engines.working_papers import ensure_working_paper_foundation
from app.main import app
from app.models import DimEntity, Transaction
from app.schemas.reports import DrillRequest, ReportFilter
from app.services.seed import seed_if_empty

client = TestClient(app)


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    ensure_working_paper_foundation(db)
    db.close()


def _entities(db):
    can = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
    usa = db.scalar(select(DimEntity).where(DimEntity.code == "USA"))
    assert can and usa
    return can, usa


def _cashbook_is_clean(db, entity_id: int, as_of: date) -> bool:
    """True when CAN has only synoptic activity — other tests add journals/feeds to the shared DB."""
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


def test_fiscal_ytd_bounds_july_and_august():
    july = ReportFilter(report_type="income_statement", period="ytd", year=2026, month=7)
    start, end = _period_bounds(july)
    assert start == date(2025, 8, 1)
    assert end == date(2026, 7, 31)
    assert fiscal_year_start(2026, 7) == date(2025, 8, 1)
    assert "Fiscal YTD ended 31 July 2026" in period_label(july)

    august = ReportFilter(report_type="income_statement", period="ytd", year=2026, month=8)
    start, end = _period_bounds(august)
    assert start == date(2026, 8, 1)
    assert end == date(2026, 8, 31)


def test_july_bs_current_earnings_matches_fiscal_ytd_ni():
    db = SessionLocal()
    try:
        can, _usa = _entities(db)
        as_of = date(2026, 7, 31)
        bs = build_report(
            db,
            ReportFilter(
                report_type="balance_sheet",
                year=2026,
                month=7,
                scenario_id=1,
                reporting_currency="CAD",
                entity_ids=[can.id],
                as_of_date=as_of,
                date_to=as_of,
            ),
        )
        pnl = build_report(
            db,
            ReportFilter(
                report_type="income_statement",
                period="ytd",
                year=2026,
                month=7,
                scenario_id=1,
                reporting_currency="CAD",
                entity_ids=[can.id],
                as_of_date=as_of,
                date_to=as_of,
            ),
        )
        by_code = {line.line_code: line for line in bs.lines}
        assert CURRENT_EARNINGS_CODE in by_code
        assert "BS_TOT_L_AND_E" in by_code
        ni = next(line for line in pnl.lines if line.line_code in ("NI", "NET_INCOME"))
        assert abs(by_code[CURRENT_EARNINGS_CODE].amount - ni.amount) < Decimal("0.02")
        assets = by_code["BS_TOT_ASSETS"].amount
        le = by_code["BS_TOT_L_AND_E"].amount
        assert bs.balance_difference is not None
        assert abs(bs.balance_difference - (assets - le)) < Decimal("0.001")
        assert bs.is_balanced == (abs(assets - le) < Decimal("0.02"))
        if _cashbook_is_clean(db, can.id, as_of):
            assert bs.is_balanced is True
        assert bs.cover_title and "Balance Sheet" in bs.cover_title
        assert "As at 31 July 2026" in (bs.period_label or "")
        assert pnl.title == "Profit & Loss"
        assert "Fiscal YTD ended 31 July 2026" in (pnl.period_label or "")
    finally:
        db.close()


def test_usa_trade_ar_excludes_interco():
    db = SessionLocal()
    try:
        _can, usa = _entities(db)
        as_of = date(2026, 7, 31)
        bs = build_report(
            db,
            ReportFilter(
                report_type="balance_sheet",
                year=2026,
                month=7,
                scenario_id=1,
                reporting_currency="USD",
                entity_ids=[usa.id],
                as_of_date=as_of,
                date_to=as_of,
                include_zero_lines=True,
            ),
        )
        by_code = {line.line_code: line for line in bs.lines}
        # STD-001 Interco AR 38,167.90 lived on 1100 — must not inflate trade AR.
        assert abs(by_code["BS_AR"].amount) < Decimal("1.00")
        # Interco AP on 2000 + Interco AR net onto the IC line.
        assert abs(by_code["BS_IC"].amount) > Decimal("1000")
        assert by_code["BS_CURRENT_EARNINGS"].amount != 0
        assert abs(by_code["BS_CASH_XFER"].amount) < Decimal("0.02")
        assert bs.is_balanced is True
    finally:
        db.close()


def test_analytics_pack_omits_cash_flow():
    db = SessionLocal()
    try:
        pack = build_analytics_pack(
            db,
            ReportFilter(
                report_type="income_statement",
                period="ytd",
                year=2026,
                month=7,
                scenario_id=1,
                reporting_currency="CAD",
            ),
        )
        assert {s.report_type for s in pack.statements} == {"income_statement", "balance_sheet"}
        assert all(s.report_type != "cash_flow" for s in pack.statements)
    finally:
        db.close()


def test_missing_fx_rate_is_flagged():
    db = SessionLocal()
    try:
        result = translate_amount(
            db,
            amount=Decimal("100"),
            from_currency="EUR",
            to_currency="CAD",
            as_of=date(2026, 7, 31),
            rate_type="closing",
        )
        assert result.missing is True
        assert lookup_rate(db, from_currency="EUR", to_currency="CAD", as_of=date(2026, 7, 31)) is None
        # Same-currency is never missing.
        same = translate_amount(
            db,
            amount=Decimal("100"),
            from_currency="CAD",
            to_currency="CAD",
            as_of=date(2026, 7, 31),
        )
        assert same.missing is False
        assert same.amount == Decimal("100")
    finally:
        db.close()


def test_api_cover_and_balance_fields():
    entities = {e["code"]: e for e in client.get("/api/entities").json()}
    res = client.post(
        "/api/reports/run",
        json={
            "report_type": "balance_sheet",
            "period": "monthly",
            "year": 2026,
            "month": 7,
            "scenario_id": 1,
            "reporting_currency": "CAD",
            "entity_ids": [entities["CAN"]["id"]],
            "as_of_date": "2026-07-31",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["title"] == "Balance Sheet"
    assert "cover_title" in body
    assert "is_balanced" in body
    codes = {line["line_code"] for line in body["lines"]}
    assert "BS_CURRENT_EARNINGS" in codes
    assert "BS_TOT_L_AND_E" in codes
    assert "cash_flow" not in body["report_type"]
    db = SessionLocal()
    try:
        if _cashbook_is_clean(db, entities["CAN"]["id"], date(2026, 7, 31)):
            assert body["is_balanced"] is True
    finally:
        db.close()


def test_can_cashbook_bs_uses_bank_book_and_opening_equity():
    db = SessionLocal()
    try:
        can, _usa = _entities(db)
        as_of = date(2026, 7, 31)
        bs = build_report(
            db,
            ReportFilter(
                report_type="balance_sheet",
                year=2026,
                month=7,
                scenario_id=1,
                reporting_currency="CAD",
                entity_ids=[can.id],
                as_of_date=as_of,
                date_to=as_of,
            ),
        )
        by_code = {line.line_code: line for line in bs.lines}
        book, _, _ = cashbook_book_cash(
            db,
            ReportFilter(
                report_type="balance_sheet",
                year=2026,
                month=7,
                scenario_id=1,
                reporting_currency="CAD",
                entity_ids=[can.id],
                as_of_date=as_of,
                date_to=as_of,
            ),
        )
        assert abs(by_code["BS_CASH"].amount - book) < Decimal("0.02")
        assert by_code["BS_EQUITY"].line_label == "Opening equity"
        if _cashbook_is_clean(db, can.id, as_of):
            assert abs(by_code["BS_CASH"].amount - Decimal("59562.75")) < Decimal("0.02")
            assert abs(by_code["BS_EQUITY"].amount - Decimal("58735.77")) < Decimal("0.02")
            assert bs.is_balanced is True
            assert abs(bs.balance_difference or 0) < Decimal("0.02")
        assert abs(by_code["BS_CASH_XFER"].amount) > Decimal("1000")
    finally:
        db.close()


def test_zero_lines_can_be_shown():
    db = SessionLocal()
    try:
        can, _usa = _entities(db)
        as_of = date(2026, 7, 31)
        hidden = build_report(
            db,
            ReportFilter(
                report_type="balance_sheet",
                year=2026,
                month=7,
                scenario_id=1,
                reporting_currency="CAD",
                entity_ids=[can.id],
                as_of_date=as_of,
                include_zero_lines=False,
            ),
        )
        shown = build_report(
            db,
            ReportFilter(
                report_type="balance_sheet",
                year=2026,
                month=7,
                scenario_id=1,
                reporting_currency="CAD",
                entity_ids=[can.id],
                as_of_date=as_of,
                include_zero_lines=True,
            ),
        )
        hidden_codes = {line.line_code for line in hidden.lines}
        shown_codes = {line.line_code for line in shown.lines}
        assert "BS_CASH" in hidden_codes
        assert "BS_CASH_XFER" in shown_codes
        assert len(shown.lines) >= len(hidden.lines)
        zero_leaves = [
            line.line_code
            for line in shown.lines
            if abs(line.amount) <= Decimal("0.005") and not line.is_total and line.drillable
        ]
        for code in zero_leaves:
            assert code not in hidden_codes
    finally:
        db.close()


def test_can_cash_drill_ties_to_book():
    db = SessionLocal()
    try:
        can, _usa = _entities(db)
        as_of = date(2026, 7, 31)
        filters = ReportFilter(
            report_type="balance_sheet",
            year=2026,
            month=7,
            scenario_id=1,
            reporting_currency="CAD",
            entity_ids=[can.id],
            as_of_date=as_of,
            date_to=as_of,
        )
        bs = build_report(db, filters)
        cash = next(line for line in bs.lines if line.line_code == "BS_CASH")
        out = drill_report_line(
            db,
            DrillRequest(line_code="BS_CASH", account_ids=cash.account_ids, filters=filters),
        )
        assert out.is_tied is True
        assert abs(out.detail_total - cash.amount) < Decimal("0.02")
        assert any(row.account_code == "OPEN" for row in out.lines)
    finally:
        db.close()
