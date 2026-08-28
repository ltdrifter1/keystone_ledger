"""Phase A: one ledger, suspense 9999, balancing TB, fiscal quarters."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.engines.fiscal import fiscal_quarter_bounds, fiscal_year_of, fiscal_year_start_for
from app.engines.ledger import INTERBANK_CODE, SUSPENSE_CODE, aggregate_ledger, ensure_ledger_accounts
from app.engines.reporting import _period_bounds, build_report, cashbook_book_cash, fiscal_year_start, period_label
from app.engines.statement_pack import build_official_report, build_trial_balance
from app.engines.working_papers import ensure_working_paper_foundation
from app.models import DimAccount, DimEntity, Transaction
from app.schemas.reports import ReportFilter
from app.services.seed import seed_if_empty


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    ensure_working_paper_foundation(db)
    db.commit()
    db.close()


def _can(db):
    can = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
    assert can
    return can


def _july_filters(entity_id: int, report_type: str = "balance_sheet") -> ReportFilter:
    as_of = date(2026, 7, 31)
    return ReportFilter(
        report_type=report_type,
        year=2026,
        month=7,
        scenario_id=1,
        reporting_currency="CAD",
        entity_ids=[entity_id],
        as_of_date=as_of,
        date_to=as_of,
        consolidate=False,
    )


def test_fiscal_quarters_are_not_calendar():
    start, end = fiscal_quarter_bounds(2026, 7, 7)
    assert start == date(2026, 5, 1)
    assert end == date(2026, 7, 31)
    q1_start, q1_end = fiscal_quarter_bounds(2026, 8, 7)
    assert q1_start == date(2026, 8, 1)
    assert q1_end == date(2026, 10, 31)
    assert fiscal_year_of(date(2026, 7, 31)) == 2026
    assert fiscal_year_of(date(2026, 8, 1)) == 2027
    assert fiscal_year_start_for(2026, 7) == date(2025, 8, 1)

    july = ReportFilter(report_type="income_statement", period="quarterly", year=2026, month=7)
    q_start, q_end = _period_bounds(july)
    assert q_start == date(2026, 5, 1)
    assert q_end == date(2026, 7, 31)
    assert "Quarter ended 31 July 2026" in period_label(july)


def test_suspense_and_interbank_accounts_exist():
    db = SessionLocal()
    try:
        by_code = ensure_ledger_accounts(db)
        assert SUSPENSE_CODE in by_code
        assert INTERBANK_CODE in by_code
        assert by_code[SUSPENSE_CODE].account_type == "asset"
        assert by_code[INTERBANK_CODE].is_cash is False
    finally:
        db.close()


def test_trial_balance_debits_equal_credits():
    db = SessionLocal()
    try:
        can = _can(db)
        tb = build_trial_balance(db, _july_filters(can.id))
        by_code = {row.account_code: row for row in tb.rows}
        assert tb.is_balanced is True
        assert abs(tb.total_debit - tb.total_credit) < Decimal("0.02")
        assert "CASH" not in by_code
        assert "UNCAT" not in by_code
        assert "CE" not in by_code
        assert "1010" in by_code or any(r.line_code == "BS_CASH" for r in tb.rows)
        assert by_code.get("1090") is None or by_code["1090"].line_code == "BS_CASH_XFER"
        assert SUSPENSE_CODE in {a.code for a in db.scalars(select(DimAccount)).all()}
    finally:
        db.close()


def test_uncategorized_hits_suspense_and_stays_visible():
    db = SessionLocal()
    try:
        can = _can(db)
        acct9999 = db.scalar(select(DimAccount).where(DimAccount.code == SUSPENSE_CODE))
        assert acct9999
        txn = Transaction(
            txn_date=date(2026, 7, 15),
            description="PHASE A SUSPENSE TEST",
            amount=Decimal("-40.00"),
            currency="CAD",
            entity_id=can.id,
            bank_account_id=None,
            account_id=None,
            scenario_id=1,
            status="uncategorized",
            source_type="bank_import",
        )
        # Attach a CAN bank so the cash leg posts.
        from app.models import BankAccount

        bank = db.scalar(select(BankAccount).where(BankAccount.entity_id == can.id))
        assert bank
        txn.bank_account_id = bank.id
        db.add(txn)
        db.commit()

        tb = build_trial_balance(db, _july_filters(can.id))
        by_code = {row.account_code: row for row in tb.rows}
        assert SUSPENSE_CODE in by_code
        assert by_code[SUSPENSE_CODE].debit > 0 or by_code[SUSPENSE_CODE].credit > 0
        assert tb.uncategorized_count >= 1
        bs = build_report(db, _july_filters(can.id, "balance_sheet"))
        codes = {line.line_code for line in bs.lines}
        assert "BS_SUSPENSE" in codes
        db.delete(txn)
        db.commit()
    finally:
        db.close()


def test_statement_cash_matches_bank_book_via_cash_gl():
    db = SessionLocal()
    try:
        can = _can(db)
        filters = _july_filters(can.id)
        bs = build_report(db, filters)
        cash = next(line for line in bs.lines if line.line_code == "BS_CASH")
        book, _, _ = cashbook_book_cash(db, filters)
        assert abs(cash.amount - book) < Decimal("0.05")
        assert bs.is_balanced is True
        ni_filters = _july_filters(can.id, "income_statement")
        ni_filters.period = "ytd"
        pnl = build_report(db, ni_filters)
        ce = next(line for line in bs.lines if line.line_code == "BS_CURRENT_EARNINGS")
        ni = next(line for line in pnl.lines if line.line_code in ("NI", "NET_INCOME"))
        assert abs(ce.amount - ni.amount) < Decimal("0.05")
    finally:
        db.close()


def test_interbank_other_side_leaves_cash_gl():
    db = SessionLocal()
    try:
        can = _can(db)
        by_code = {a.code: a for a in db.scalars(select(DimAccount)).all()}
        from app.models import BankAccount

        bank = db.scalar(
            select(BankAccount).where(
                BankAccount.entity_id == can.id,
                BankAccount.is_active.is_(True),
                BankAccount.gl_account_id.is_not(None),
            )
        )
        assert bank and by_code.get("1015")
        txn = Transaction(
            txn_date=date(2026, 7, 20),
            description="PHASE A INTERBANK TEST",
            amount=Decimal("-200.00"),
            currency="CAD",
            entity_id=can.id,
            bank_account_id=bank.id,
            account_id=by_code["1015"].id,
            scenario_id=1,
            status="categorized",
            source_type="manual",
        )
        db.add(txn)
        db.commit()
        tb = build_trial_balance(db, _july_filters(can.id))
        by_row = {row.account_code: row for row in tb.rows}
        assert tb.is_balanced is True
        assert INTERBANK_CODE in by_row
        assert by_row[INTERBANK_CODE].debit >= Decimal("200")
        db.delete(txn)
        db.commit()
    finally:
        db.close()


def test_official_pack_notes_are_ledger_not_cashbook():
    db = SessionLocal()
    try:
        can = _can(db)
        pnl = build_official_report(db, _july_filters(can.id, "income_statement"))
        assert "double-entry" in (pnl.accounting_basis or "").lower()
        assert any("Fiscal year" in n.heading for n in pnl.notes)
        assert "cashbook" not in (pnl.accounting_basis or "").lower()
    finally:
        db.close()


def test_functional_currency_forced_to_entity():
    db = SessionLocal()
    try:
        usa = db.scalar(select(DimEntity).where(DimEntity.code == "USA"))
        assert usa
        rpt = build_official_report(
            db,
            ReportFilter(
                report_type="balance_sheet",
                year=2026,
                month=7,
                entity_ids=[usa.id],
                reporting_currency="CAD",
                as_of_date=date(2026, 7, 31),
                date_to=date(2026, 7, 31),
            ),
        )
        assert rpt.currency == "USD"
    finally:
        db.close()
