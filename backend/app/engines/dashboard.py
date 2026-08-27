from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.engines.binder import build_binder
from app.engines.close_pack import month_close_overview
from app.engines.fx import fx_exposure_by_currency, translate_amount
from app.engines.intercompany import unmatched_intercompany_count
from app.engines.reporting import aggregate_by_account
from app.models import BankAccount, DimAccount, DimEntity, Reconciliation, Transaction
from app.schemas.reports import (
    CashBalanceRow,
    DashboardBinderSummary,
    DashboardCloseSummary,
    DashboardKPI,
    DashboardNextAction,
    DashboardOut,
    ReconHealthRow,
    ReportFilter,
)

# Cash vs budget: within max(5% of budget, 500 native units) counts as on target
_BUDGET_PCT = Decimal("0.05")
_BUDGET_FLOOR = Decimal("500")


def _period_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _target_status(balance: Decimal, budget: Decimal | None) -> tuple[str, bool | None, Decimal | None, Decimal | None]:
    if budget is None:
        return "no_budget", None, None, None
    variance = balance - budget
    variance_pct = None
    if budget != 0:
        variance_pct = (variance / abs(budget)) * Decimal("100")
    tolerance = max(abs(budget) * _BUDGET_PCT, _BUDGET_FLOOR)
    if abs(variance) <= tolerance:
        return "on_target", True, variance, variance_pct
    if variance > 0:
        return "above", False, variance, variance_pct
    return "below", False, variance, variance_pct


def _recon_freshness(last_date: date | None, today: date) -> str:
    if last_date is None:
        return "never"
    # Current calendar month end still "current"; prior month OK; older = stale
    if last_date.year == today.year and last_date.month == today.month:
        return "current"
    # Prior month
    if today.month == 1:
        prior_y, prior_m = today.year - 1, 12
    else:
        prior_y, prior_m = today.year, today.month - 1
    prior_end = _period_end(prior_y, prior_m)
    if last_date >= prior_end:
        return "prior"
    return "stale"


def build_recon_health(
    db: Session,
    *,
    banks: list[BankAccount],
    entities: dict[int, DimEntity],
    balances: dict[int, Decimal],
    today: date,
) -> list[ReconHealthRow]:
    rows: list[ReconHealthRow] = []
    for bank in banks:
        balance = balances.get(bank.id, Decimal("0"))
        budget = Decimal(bank.budget_balance) if bank.budget_balance is not None else None
        target_status, on_target, variance, variance_pct = _target_status(balance, budget)

        locked = list(
            db.scalars(
                select(Reconciliation)
                .where(
                    Reconciliation.bank_account_id == bank.id,
                    Reconciliation.status == "locked",
                )
                .order_by(Reconciliation.period_year.desc(), Reconciliation.period_month.desc())
            )
        )
        last = locked[0] if locked else None
        last_date = _period_end(last.period_year, last.period_month) if last else None
        last_period = f"{last.period_year}-{last.period_month:02d}" if last else None
        days_since = (today - last_date).days if last_date else None

        current = db.scalar(
            select(Reconciliation).where(
                Reconciliation.bank_account_id == bank.id,
                Reconciliation.period_year == today.year,
                Reconciliation.period_month == today.month,
            )
        )
        current_status = current.status if current else "not_started"
        ent = entities.get(bank.entity_id)

        rows.append(
            ReconHealthRow(
                bank_account_id=bank.id,
                name=bank.name,
                entity_code=ent.code if ent else "?",
                currency=bank.currency,
                balance=balance,
                budget_balance=budget,
                variance=variance,
                variance_pct=variance_pct,
                on_target=on_target,
                target_status=target_status,
                last_reconciled_date=last_date,
                last_reconciled_period=last_period,
                days_since_reconciled=days_since,
                recon_freshness=_recon_freshness(last_date, today),
                current_period_status=current_status,
                href=f"/work?year={today.year}&month={today.month}&bank={bank.id}",
            )
        )
    # Off-target / stale first
    rank = {"below": 0, "above": 1, "no_budget": 2, "on_target": 3}
    fresh = {"never": 0, "stale": 1, "prior": 2, "current": 3}
    rows.sort(key=lambda r: (rank.get(r.target_status, 9), fresh.get(r.recon_freshness, 9), r.name))
    return rows


def build_dashboard(db: Session, reporting_currency: str | None = None) -> DashboardOut:
    settings = get_settings()
    reporting_currency = reporting_currency or settings.default_reporting_currency
    today = date.today()
    year = today.year

    # Cash by account
    banks = list(db.scalars(select(BankAccount).where(BankAccount.is_active == True)).all())
    entities = {e.id: e for e in db.scalars(select(DimEntity)).all()}
    cash_rows: list[CashBalanceRow] = []
    cash_by_ccy: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    consolidated_cash = Decimal("0")
    book_balances: dict[int, Decimal] = {}

    for bank in banks:
        total = db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.bank_account_id == bank.id,
                Transaction.status != "void",
            )
        )
        bal = Decimal(bank.opening_balance) + Decimal(total or 0)
        book_balances[bank.id] = bal
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

    recon_health = build_recon_health(
        db,
        banks=banks,
        entities=entities,
        balances=book_balances,
        today=today,
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
            Transaction.is_split == False,
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

    close = month_close_overview(db, today.year, today.month)
    blocking_total = sum(int(p.get("blocking_count") or 0) for p in close["packs"])
    close_summary = DashboardCloseSummary(
        period_year=close["period_year"],
        period_month=close["period_month"],
        period_label=close["period_label"],
        banks_total=close["banks_total"],
        banks_locked=close["banks_locked"],
        banks_ready_to_lock=close["banks_ready_to_lock"],
        banks_in_progress=close.get("banks_in_progress", 0),
        can_lock_month=close["can_lock_month"],
        all_locked=close["all_locked"],
        blocking_total=blocking_total,
    )

    next_actions: list[DashboardNextAction] = []
    for action in close.get("next_actions", [])[:8]:
        params = [
            f"year={close['period_year']}",
            f"month={close['period_month']}",
            f"bank={action['bank_account_id']}",
            f"mode={action.get('mode') or 'exceptions'}",
        ]
        if action.get("filter"):
            params.append(f"filter={action['filter']}")
        next_actions.append(
            DashboardNextAction(
                key=action["key"],
                kind=action["kind"],
                priority=action["priority"],
                title=action["title"],
                detail=action["detail"],
                href=f"/work?{'&'.join(params)}",
                count=action.get("count"),
                amount=action.get("amount"),
                status="ok" if action["kind"] == "ready_to_lock" else "warning",
            )
        )
    if uncategorized and not any(a.kind == "categorize" for a in next_actions):
        next_actions.insert(
            0,
            DashboardNextAction(
                key="global-uncategorized",
                kind="categorize",
                priority=5,
                title=f"Categorize {uncategorized} uncategorized",
                detail="Open the close cockpit for this month’s bank exceptions",
                href=f"/work?year={today.year}&month={today.month}&filter=uncategorized",
                count=int(uncategorized),
                status="warning",
            ),
        )
    if unmatched_ic:
        next_actions.append(
            DashboardNextAction(
                key="unmatched-ic",
                kind="intercompany",
                priority=30,
                title=f"Match {unmatched_ic} intercompany",
                detail="Unmatched IC transfers still open",
                href=f"/work?year={today.year}&month={today.month}&filter=intercompany",
                count=int(unmatched_ic),
                status="warning",
            )
        )
    next_actions.sort(key=lambda a: (a.priority, a.title))

    binder = build_binder(db, today.year, today.month)
    binder_summary = DashboardBinderSummary(
        period_year=binder["period_year"],
        period_month=binder["period_month"],
        period_label=binder["period_label"],
        total=binder["summary"]["total"],
        prepared=binder["summary"]["prepared"],
        reviewed=binder["summary"]["reviewed"],
        open=binder["summary"]["open"],
        untied=binder["summary"]["untied"],
        href=f"/binder?year={binder['period_year']}&month={binder['period_month']}",
    )

    # Job KPIs first — what to do next — then P&L context
    kpis = [
        DashboardKPI(
            key="close_progress",
            label=f"Close {close_summary.period_label}",
            value=Decimal(close_summary.banks_locked),
            format="number",
            status="ok" if close_summary.all_locked else "warning",
        ),
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
        DashboardKPI(
            key="blocking_exceptions",
            label="Blocking Exceptions",
            value=Decimal(blocking_total),
            format="number",
            status="warning" if blocking_total else "ok",
        ),
        DashboardKPI(
            key="binder_ready",
            label="WPs Prepared",
            value=Decimal(binder_summary.prepared),
            format="number",
            status="ok" if binder_summary.prepared == binder_summary.total else "warning",
        ),
        DashboardKPI(
            key="binder_untied",
            label="Untied WP Leads",
            value=Decimal(binder_summary.untied),
            format="number",
            status="warning" if binder_summary.untied else "ok",
        ),
        DashboardKPI(key="consolidated_cash", label="Consolidated Cash", value=consolidated_cash, currency=reporting_currency),
        DashboardKPI(key="revenue", label="Revenue YTD", value=revenue, currency=reporting_currency),
        DashboardKPI(key="expenses", label="Expenses YTD", value=expenses, currency=reporting_currency),
        DashboardKPI(key="net_income", label="Net Income YTD", value=net_income, currency=reporting_currency),
        DashboardKPI(key="working_capital", label="Working Capital", value=working_capital, currency=reporting_currency),
    ]

    return DashboardOut(
        kpis=kpis,
        cash_by_account=cash_rows,
        recon_health=recon_health,
        outstanding_reconciliations=int(outstanding_recons),
        uncategorized_transactions=int(uncategorized),
        unmatched_intercompany=int(unmatched_ic),
        fx_exposure=fx_exposure_by_currency(db, dict(cash_by_ccy), reporting_currency, today),
        intercompany_balances=ic_rows,
        close_summary=close_summary,
        next_actions=next_actions,
        binder_summary=binder_summary,
    )
