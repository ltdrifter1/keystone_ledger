"""Seed demo chart, entities (Canada/USA), bank accounts, rules, and sample transactions."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.fingerprint import transaction_fingerprint
from app.engines.importing import ensure_date_dimension
from app.models import (
    BankAccount,
    CategorizationRule,
    DimAccount,
    DimDepartment,
    DimEntity,
    DimFx,
    DimReportLayout,
    DimScenario,
    Transaction,
)


def seed_if_empty(db: Session) -> bool:
    if db.scalar(select(DimEntity).limit(1)):
        return False
    seed_all(db)
    return True


def seed_all(db: Session) -> None:
    ca = DimEntity(code="CA", name="Keystone Canada Inc.", country="Canada", functional_currency="CAD")
    us = DimEntity(code="US", name="Keystone USA LLC", country="United States", functional_currency="USD")
    db.add_all([ca, us])
    db.flush()

    scenarios = [
        DimScenario(code="ACTUAL", name="Actual", scenario_type="actual"),
        DimScenario(code="BUDGET", name="Budget", scenario_type="budget"),
        DimScenario(code="FORECAST", name="Forecast", scenario_type="forecast"),
        DimScenario(code="PRIOR", name="Prior Year", scenario_type="prior_year"),
    ]
    db.add_all(scenarios)
    db.flush()
    actual = scenarios[0]
    budget = scenarios[1]

    accounts = [
        DimAccount(code="1000", name="Cash & Banks", account_type="asset", statement="balance_sheet", is_cash=True, sort_order=10),
        DimAccount(code="1100", name="Accounts Receivable", account_type="asset", statement="balance_sheet", sort_order=20),
        DimAccount(code="1500", name="Fixed Assets", account_type="asset", statement="balance_sheet", sort_order=30),
        DimAccount(code="2000", name="Accounts Payable", account_type="liability", statement="balance_sheet", normal_balance="credit", sort_order=40),
        DimAccount(code="2100", name="Accrued Liabilities", account_type="liability", statement="balance_sheet", normal_balance="credit", sort_order=50),
        DimAccount(code="2500", name="Intercompany Payable", account_type="liability", statement="balance_sheet", normal_balance="credit", is_intercompany=True, sort_order=60),
        DimAccount(code="3000", name="Equity / Owner Capital", account_type="equity", statement="balance_sheet", normal_balance="credit", sort_order=70),
        DimAccount(code="4000", name="Operating Revenue", account_type="revenue", statement="income_statement", normal_balance="credit", sort_order=80, cash_flow_section="operating"),
        DimAccount(code="4100", name="Other Income", account_type="revenue", statement="income_statement", normal_balance="credit", sort_order=90, cash_flow_section="operating"),
        DimAccount(code="5000", name="Salaries & Wages", account_type="expense", statement="income_statement", sort_order=100, cash_flow_section="operating"),
        DimAccount(code="5100", name="Rent & Occupancy", account_type="expense", statement="income_statement", sort_order=110, cash_flow_section="operating"),
        DimAccount(code="5200", name="Software & SaaS", account_type="expense", statement="income_statement", sort_order=120, cash_flow_section="operating"),
        DimAccount(code="5300", name="Professional Fees", account_type="expense", statement="income_statement", sort_order=130, cash_flow_section="operating"),
        DimAccount(code="5400", name="Travel & Entertainment", account_type="expense", statement="income_statement", sort_order=140, cash_flow_section="operating"),
        DimAccount(code="5500", name="Bank Fees", account_type="expense", statement="income_statement", sort_order=150, cash_flow_section="operating"),
        DimAccount(code="6000", name="Intercompany Transfer", account_type="transfer", statement="none", is_intercompany=True, sort_order=160),
        DimAccount(code="6100", name="Owner Draw / Distribution", account_type="equity", statement="balance_sheet", sort_order=170),
        DimAccount(code="6200", name="Asset Purchase", account_type="asset", statement="balance_sheet", cash_flow_section="investing", sort_order=180),
    ]
    db.add_all(accounts)
    db.flush()
    by_code = {a.code: a for a in accounts}

    depts = [
        DimDepartment(code="CORP", name="Corporate", entity_id=ca.id),
        DimDepartment(code="OPS", name="Operations", entity_id=ca.id),
        DimDepartment(code="USOPS", name="US Operations", entity_id=us.id),
    ]
    db.add_all(depts)
    db.flush()

    banks = [
        BankAccount(
            entity_id=ca.id,
            name="RBC Operating CAD",
            account_number="****4521",
            currency="CAD",
            institution="RBC",
            gl_account_id=by_code["1000"].id,
            opening_balance=Decimal("125000.00"),
        ),
        BankAccount(
            entity_id=ca.id,
            name="RBC USD Account",
            account_number="****8890",
            currency="USD",
            institution="RBC",
            gl_account_id=by_code["1000"].id,
            opening_balance=Decimal("42000.00"),
        ),
        BankAccount(
            entity_id=us.id,
            name="Chase Operating USD",
            account_number="****3312",
            currency="USD",
            institution="Chase",
            gl_account_id=by_code["1000"].id,
            opening_balance=Decimal("88000.00"),
        ),
    ]
    db.add_all(banks)
    db.flush()

    # FX rates
    today = date.today()
    for i in range(0, 180, 15):
        d = today - timedelta(days=i)
        db.add(DimFx(from_currency="USD", to_currency="CAD", rate_date=d, rate=Decimal("1.3600"), rate_type="spot"))
        db.add(DimFx(from_currency="USD", to_currency="CAD", rate_date=d, rate=Decimal("1.3550"), rate_type="average"))
        db.add(DimFx(from_currency="USD", to_currency="CAD", rate_date=d, rate=Decimal("1.3620"), rate_type="closing"))

    # Report layouts — Income Statement
    is_layout = [
        ("REV", "Revenue", "revenue", None, "revenue", None, 0, True, False, 10, False),
        ("REV_OPS", "Operating Revenue", "revenue", by_code["4000"].id, None, None, 1, False, False, 20, False),
        ("REV_OTH", "Other Income", "revenue", by_code["4100"].id, None, None, 1, False, False, 30, False),
        ("TOT_REV", "Total Revenue", "revenue", None, None, "REV_OPS + REV_OTH", 0, True, True, 40, False),
        ("EXP", "Expenses", "expense", None, "expense", None, 0, True, False, 50, False),
        ("EXP_SAL", "Salaries & Wages", "expense", by_code["5000"].id, None, None, 1, False, False, 60, False),
        ("EXP_RENT", "Rent & Occupancy", "expense", by_code["5100"].id, None, None, 1, False, False, 70, False),
        ("EXP_SAAS", "Software & SaaS", "expense", by_code["5200"].id, None, None, 1, False, False, 80, False),
        ("EXP_PROF", "Professional Fees", "expense", by_code["5300"].id, None, None, 1, False, False, 90, False),
        ("EXP_TRAV", "Travel & Entertainment", "expense", by_code["5400"].id, None, None, 1, False, False, 100, False),
        ("EXP_BANK", "Bank Fees", "expense", by_code["5500"].id, None, None, 1, False, False, 110, False),
        ("TOT_EXP", "Total Expenses", "expense", None, None, "EXP_SAL + EXP_RENT + EXP_SAAS + EXP_PROF + EXP_TRAV + EXP_BANK", 0, True, True, 120, False),
        ("NI", "Net Income", "totals", None, None, "TOT_REV - TOT_EXP", 0, True, True, 130, False),
    ]
    for code, label, section, acct_id, type_f, formula, indent, bold, total, order, flip in is_layout:
        db.add(
            DimReportLayout(
                report_type="income_statement",
                section=section,
                line_code=code,
                line_label=label,
                account_id=acct_id,
                account_type_filter=type_f,
                calc_formula=formula,
                indent_level=indent,
                is_bold=bold,
                is_total=total,
                sort_order=order,
                sign_flip=flip,
            )
        )

    # Rules
    rules = [
        CategorizationRule(
            name="Payroll ADP",
            priority=10,
            match_description_contains="ADP PAYROLL",
            assign_account_id=by_code["5000"].id,
            assign_department_id=depts[0].id,
        ),
        CategorizationRule(
            name="AWS / Cloud",
            priority=20,
            match_description_contains="AWS",
            assign_account_id=by_code["5200"].id,
        ),
        CategorizationRule(
            name="Office Rent",
            priority=20,
            match_description_contains="COMMERCIAL REIT",
            assign_account_id=by_code["5100"].id,
        ),
        CategorizationRule(
            name="Stripe Revenue",
            priority=10,
            match_description_contains="STRIPE",
            assign_account_id=by_code["4000"].id,
        ),
        CategorizationRule(
            name="Intercompany Transfer",
            priority=15,
            match_description_contains="IC TRANSFER",
            assign_account_id=by_code["6000"].id,
        ),
        CategorizationRule(
            name="Bank Service Charge",
            priority=30,
            match_description_contains="SERVICE CHARGE",
            assign_account_id=by_code["5500"].id,
        ),
    ]
    db.add_all(rules)
    db.flush()

    # Sample transactions spanning current year
    samples = [
        # CA RBC CAD
        (banks[0], today - timedelta(days=5), "STRIPE TRANSFER", Decimal("18500.00"), by_code["4000"].id, None),
        (banks[0], today - timedelta(days=6), "ADP PAYROLL JAN16", Decimal("-42000.00"), by_code["5000"].id, depts[0].id),
        (banks[0], today - timedelta(days=8), "COMMERCIAL REIT RENT", Decimal("-8500.00"), by_code["5100"].id, None),
        (banks[0], today - timedelta(days=10), "AWS MONTHLY", Decimal("-2140.55"), by_code["5200"].id, None),
        (banks[0], today - timedelta(days=12), "DELOITTE ADVISORY", Decimal("-6500.00"), by_code["5300"].id, None),
        (banks[0], today - timedelta(days=14), "IC TRANSFER TO US", Decimal("-25000.00"), by_code["6000"].id, None),
        (banks[0], today - timedelta(days=18), "AIR CANADA YYZ-SFO", Decimal("-812.40"), None, None),  # uncategorized
        (banks[0], today - timedelta(days=20), "SERVICE CHARGE", Decimal("-15.00"), by_code["5500"].id, None),
        (banks[0], today - timedelta(days=40), "STRIPE TRANSFER", Decimal("22100.00"), by_code["4000"].id, None),
        (banks[0], today - timedelta(days=45), "ADP PAYROLL DEC", Decimal("-41500.00"), by_code["5000"].id, depts[0].id),
        # US Chase
        (banks[2], today - timedelta(days=14), "IC TRANSFER FROM CA", Decimal("18382.35"), by_code["6000"].id, None),
        (banks[2], today - timedelta(days=7), "STRIPE TRANSFER", Decimal("14200.00"), by_code["4000"].id, None),
        (banks[2], today - timedelta(days=9), "GUSTO PAYROLL", Decimal("-28000.00"), None, None),
        (banks[2], today - timedelta(days=11), "AWS MONTHLY", Decimal("-980.00"), by_code["5200"].id, None),
        (banks[2], today - timedelta(days=15), "WEWORK DOWNTOWN", Decimal("-4200.00"), by_code["5100"].id, None),
        # CA USD account
        (banks[1], today - timedelta(days=16), "VENDOR USD WIRE", Decimal("-3500.00"), by_code["5300"].id, None),
        (banks[1], today - timedelta(days=3), "CUSTOMER USD WIRE", Decimal("9000.00"), by_code["4000"].id, None),
    ]

    for bank, txn_date, desc, amount, account_id, dept_id in samples:
        fp = transaction_fingerprint(
            txn_date=txn_date,
            amount=amount,
            description=desc,
            currency=bank.currency,
            bank_account_id=bank.id,
        )
        status = "categorized" if account_id else "uncategorized"
        counter_entity = None
        if "IC TRANSFER TO US" in desc:
            counter_entity = us.id
        if "IC TRANSFER FROM CA" in desc:
            counter_entity = ca.id
        txn = Transaction(
            fingerprint=fp,
            txn_date=txn_date,
            description=desc,
            amount=amount,
            currency=bank.currency,
            entity_id=bank.entity_id,
            bank_account_id=bank.id,
            account_id=account_id,
            department_id=dept_id,
            scenario_id=actual.id,
            date_key=ensure_date_dimension(db, txn_date),
            counter_entity_id=counter_entity,
            source_type="bank_import",
            status=status,
            created_by="seed",
            updated_by="seed",
        )
        db.add(txn)

    # Budget scenario sample (revenue/expense targets as memo transactions without bank)
    budget_lines = [
        (ca.id, today.replace(day=1), "Budget Revenue", Decimal("200000.00"), by_code["4000"].id),
        (ca.id, today.replace(day=1), "Budget Salaries", Decimal("-160000.00"), by_code["5000"].id),
        (us.id, today.replace(day=1), "Budget Revenue", Decimal("120000.00"), by_code["4000"].id),
        (us.id, today.replace(day=1), "Budget Salaries", Decimal("-90000.00"), by_code["5000"].id),
    ]
    for entity_id, txn_date, desc, amount, account_id in budget_lines:
        db.add(
            Transaction(
                txn_date=txn_date,
                description=desc,
                amount=amount,
                currency="CAD" if entity_id == ca.id else "USD",
                entity_id=entity_id,
                account_id=account_id,
                scenario_id=budget.id,
                date_key=ensure_date_dimension(db, txn_date),
                source_type="manual",
                status="categorized",
                created_by="seed",
            )
        )

    db.commit()
