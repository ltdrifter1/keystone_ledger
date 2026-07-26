from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.engines.fx import fx_exposure_by_currency, translate_amount
from app.engines.intercompany import unmatched_intercompany_count
from app.engines.reporting import aggregate_by_account
from app.models import BankAccount, DimAccount, DimEntity, Reconciliation, Transaction
from app.schemas.reports import (
    CashBalanceRow,
    DashboardKPI,
    DashboardOut,
    ReportFilter,
)


def build_dashboard(db: Session, reporting_currency: str | None = None) -> DashboardOut:
    settings = get_settings()
    reporting_currency = reporting_currency or settings.default_reporting_currency
    today = date.today()
    year = today.year

    # Cash by account
    banks = db.scalars(select(BankAccount).where(BankAccount.is_active.is_(True))).all()
    entities = {e.id: e for e in db.scalars(select(DimEntity)).all()}
    cash_rows: list[CashBalanceRow] = []
    cash_by_ccy: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    consolidated_cash = Decimal("0")

    for bank in banks:
        total = db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.bank_account_id == bank.id,
                Transaction.status != "void",
            )
        )
        bal = Decimal(bank.opening_balance) + Decimal(total or 0)
        reporting, _ = translate_amount(
            db,
            amount=bal,
            from_currency=bank.currency,
            to_currency=reporting_currency,
            as_of=today,
        )
        cash_by_ccy[bank.currency] += bal
        consolidated_cash += reporting
        ent = entities.get(bank.entity_id)
        cash_rows.append(
            CashBalanceRow(
                bank_account_id=bank.id,
                name=bank.name,
                entity_code=ent.code if ent else "?",
                currency=bank.currency,
                balance=bal,
                balance_reporting=reporting,
            )
        )

    # P&L YTD
    is_filter = ReportFilter(
        report_type="income_statement",
        period="ytd",
        year=year,
        scenario_id=1,
        reporting_currency=reporting_currency,
        consolidate=True,
    )
    acct_totals = aggregate_by_account(db, is_filter, balance_sheet=False)
    accounts = {a.id: a for a in db.scalars(select(DimAccount)).all()}
    revenue = Decimal("0")
    expenses = Decimal("0")
    for acct_id, amount in acct_totals.items():
        acct = accounts.get(acct_id)
        if not acct:
            continue
        if acct.account_type == "revenue":
            revenue += amount
        elif acct.account_type == "expense":
            expenses += -amount  # convert bank-signed to expense magnitude

    net_income = revenue - expenses

    # Working capital (simplified): current assets - current liabilities from BS
    bs_filter = ReportFilter(
        report_type="balance_sheet",
        as_of_date=today,
        scenario_id=1,
        reporting_currency=reporting_currency,
    )
    bs_totals = aggregate_by_account(db, bs_filter, balance_sheet=True)
    current_assets = Decimal("0")
    current_liab = Decimal("0")
    for acct_id, amount in bs_totals.items():
        acct = accounts.get(acct_id)
        if not acct:
            continue
        # Heuristic: cash + AR-like assets vs AP-like liabilities
        if acct.account_type == "asset" and (
            acct.is_cash or "RECEIVABLE" in acct.name.upper() or acct.code.startswith("1")
        ):
            current_assets += amount
        if acct.account_type == "liability" and (
            "PAYABLE" in acct.name.upper() or acct.code.startswith("2")
        ):
            current_liab += -amount

    working_capital = current_assets - current_liab

    outstanding_recons = db.scalar(
        select(func.count()).select_from(Reconciliation).where(
            Reconciliation.status.in_(["open", "in_progress"])
        )
    ) or 0

    uncategorized = db.scalar(
        select(func.count()).select_from(Transaction).where(
            Transaction.status == "uncategorized",
            Transaction.is_split.is_(False),
        )
    ) or 0

    unmatched_ic = unmatched_intercompany_count(db)

    # Intercompany balances by counter entity
    ic_accounts = {
        a.id
        for a in accounts.values()
        if a.is_intercompany or a.account_type in ("transfer", "intercompany")
    }
    ic_txns = db.scalars(
        select(Transaction).where(
            Transaction.status != "void",
            (Transaction.counter_entity_id.is_not(None)) | (Transaction.account_id.in_(ic_accounts)),
        )
    ).all()
    ic_balances: dict[tuple[int, int], Decimal] = defaultdict(lambda: Decimal("0"))
    for txn in ic_txns:
        if not txn.counter_entity_id:
            continue
        reporting, _ = translate_amount(
            db,
            amount=Decimal(txn.amount),
            from_currency=txn.currency,
            to_currency=reporting_currency,
            as_of=txn.txn_date,
        )
        ic_balances[(txn.entity_id, txn.counter_entity_id)] += reporting

    ic_rows = [
        {
            "from_entity_id": a,
            "to_entity_id": b,
            "from_entity": entities[a].code if a in entities else str(a),
            "to_entity": entities[b].code if b in entities else str(b),
            "balance": float(bal),
            "currency": reporting_currency,
        }
        for (a, b), bal in ic_balances.items()
        if bal != 0
    ]

    kpis = [
        DashboardKPI(key="consolidated_cash", label="Consolidated Cash", value=consolidated_cash, currency=reporting_currency),
        DashboardKPI(key="revenue", label="Revenue YTD", value=revenue, currency=reporting_currency),
        DashboardKPI(key="expenses", label="Expenses YTD", value=expenses, currency=reporting_currency),
        DashboardKPI(key="net_income", label="Net Income YTD", value=net_income, currency=reporting_currency),
        DashboardKPI(key="working_capital", label="Working Capital", value=working_capital, currency=reporting_currency),
        DashboardKPI(
            key="outstanding_reconciliations",
            label="Open Reconciliations",
            value=Decimal(outstanding_recons),
            format="number",
            status="warning" if outstanding_recons else "ok",
        ),
        DashboardKPI(
            key="uncategorized",
            label="Uncategorized Txns",
            value=Decimal(uncategorized),
            format="number",
            status="warning" if uncategorized else "ok",
        ),
        DashboardKPI(
            key="unmatched_ic",
            label="Unmatched Intercompany",
            value=Decimal(unmatched_ic),
            format="number",
            status="warning" if unmatched_ic else "ok",
        ),
    ]

    return DashboardOut(
        kpis=kpis,
        cash_by_account=cash_rows,
        outstanding_reconciliations=int(outstanding_recons),
        uncategorized_transactions=int(uncategorized),
        unmatched_intercompany=int(unmatched_ic),
        fx_exposure=fx_exposure_by_currency(db, dict(cash_by_ccy), reporting_currency, today),
        intercompany_balances=ic_rows,
    )
