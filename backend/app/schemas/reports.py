from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class ReportFilter(BaseModel):
    report_type: str = "income_statement"
    # income_statement | balance_sheet | equity | trial_balance
    entity_ids: Optional[list[int]] = None
    department_ids: Optional[list[int]] = None
    scenario_id: int = 1
    compare_scenario_id: Optional[int] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    as_of_date: Optional[date] = None
    period: str = "ytd"  # monthly | quarterly | ytd | custom
    year: Optional[int] = None
    month: Optional[int] = None
    quarter: Optional[int] = None
    consolidate: bool = False
    reporting_currency: str = "CAD"
    compare_prior_period: bool = False
    compare_prior_year: bool = False
    compare_budget: bool = False
    materiality_amount: Optional[Decimal] = None
    materiality_pct: Optional[Decimal] = None
    include_zero_lines: bool = False


class ReportingNote(BaseModel):
    heading: str
    body: str


class StatementPlug(BaseModel):
    key: str
    title: str
    detail: str
    amount: Optional[Decimal] = None
    href: Optional[str] = None
    blocking: bool = True


class ReportLine(BaseModel):
    line_code: str
    line_label: str
    section: str
    amount: Decimal
    compare_amount: Optional[Decimal] = None
    variance: Optional[Decimal] = None
    variance_pct: Optional[Decimal] = None
    prior_period_amount: Optional[Decimal] = None
    prior_period_variance: Optional[Decimal] = None
    prior_period_variance_pct: Optional[Decimal] = None
    prior_year_amount: Optional[Decimal] = None
    prior_year_variance: Optional[Decimal] = None
    prior_year_variance_pct: Optional[Decimal] = None
    budget_amount: Optional[Decimal] = None
    budget_variance: Optional[Decimal] = None
    budget_variance_pct: Optional[Decimal] = None
    flux_flag: Optional[str] = None  # material | new | drop
    flux_note: Optional[str] = None
    indent_level: int = 0
    is_bold: bool = False
    is_total: bool = False
    account_id: Optional[int] = None
    # Working-paper drill metadata
    drillable: bool = False
    account_ids: list[int] = Field(default_factory=list)
    account_type_filter: Optional[str] = None
    wp_ref: Optional[str] = None  # e.g. A.1, B.3


class ReportOut(BaseModel):
    report_type: str
    title: str
    filters: ReportFilter
    lines: list[ReportLine]
    generated_at: str
    currency: str
    period_label: Optional[str] = None
    prior_period_label: Optional[str] = None
    prior_year_label: Optional[str] = None
    budget_label: Optional[str] = None
    columns: list[str] = Field(default_factory=lambda: ["amount"])
    flux: list["FluxItem"] = Field(default_factory=list)
    cover_title: Optional[str] = None
    entity_name: Optional[str] = None
    is_balanced: Optional[bool] = None
    balance_difference: Optional[Decimal] = None
    fx_missing: bool = False
    fx_missing_pairs: list[str] = Field(default_factory=list)
    accounting_basis: Optional[str] = None
    notes: list["ReportingNote"] = Field(default_factory=list)
    pack_disclaimer: Optional[str] = None


class FluxItem(BaseModel):
    report_type: str
    line_code: str
    line_label: str
    wp_ref: Optional[str] = None
    amount: Decimal
    prior_amount: Optional[Decimal] = None
    variance: Optional[Decimal] = None
    variance_pct: Optional[Decimal] = None
    flag: str
    note: str
    drillable: bool = False


class AnalyticsKpi(BaseModel):
    key: str
    label: str
    amount: Decimal
    prior_amount: Optional[Decimal] = None
    variance: Optional[Decimal] = None
    variance_pct: Optional[Decimal] = None
    tone: Optional[str] = None


class AnalyticsPack(BaseModel):
    period_label: str
    currency: str
    materiality_amount: Decimal
    materiality_pct: Decimal
    kpis: list[AnalyticsKpi] = Field(default_factory=list)
    flux: list[FluxItem] = Field(default_factory=list)
    statements: list[ReportOut] = Field(default_factory=list)
    generated_at: str
    budget_is_illustrative: bool = False
    notes: list[ReportingNote] = Field(default_factory=list)
    pack_disclaimer: Optional[str] = None
    can_print: bool = False


class TrialBalanceRow(BaseModel):
    account_id: Optional[int] = None
    account_code: str
    account_name: str
    account_type: str
    statement: Optional[str] = None
    line_code: Optional[str] = None
    line_label: Optional[str] = None
    mapped: bool = False
    opening_debit: Decimal = Decimal("0")
    opening_credit: Decimal = Decimal("0")
    period_debit: Decimal = Decimal("0")
    period_credit: Decimal = Decimal("0")
    debit: Decimal = Decimal("0")  # closing
    credit: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    synthetic: bool = False
    exception: Optional[str] = None


class TrialBalanceOut(BaseModel):
    title: str = "Trial Balance"
    cover_title: Optional[str] = None
    entity_name: Optional[str] = None
    period_label: Optional[str] = None
    currency: str
    as_of_date: date
    accounting_basis: Optional[str] = None
    rows: list[TrialBalanceRow] = Field(default_factory=list)
    total_debit: Decimal = Decimal("0")
    total_credit: Decimal = Decimal("0")
    unmapped_count: int = 0
    uncategorized_count: int = 0
    uncategorized_amount: Decimal = Decimal("0")
    is_complete: bool = False
    is_balanced: bool = False
    balance_difference: Optional[Decimal] = None
    notes: list[ReportingNote] = Field(default_factory=list)
    generated_at: str


class StatementDiagnostics(BaseModel):
    entity_id: int
    entity_code: Optional[str] = None
    entity_name: Optional[str] = None
    period_label: str
    currency: str
    accounting_basis: Optional[str] = None
    is_balanced: bool = False
    balance_difference: Optional[Decimal] = None
    fx_missing: bool = False
    fx_missing_pairs: list[str] = Field(default_factory=list)
    uncategorized_count: int = 0
    uncategorized_amount: Decimal = Decimal("0")
    unmapped_count: int = 0
    unmapped_codes: list[str] = Field(default_factory=list)
    cashbook_journals_count: int = 0
    plugs: list[StatementPlug] = Field(default_factory=list)
    can_print: bool = False
    notes: list[ReportingNote] = Field(default_factory=list)
    pack_disclaimer: Optional[str] = None
    statements_href: str
    trial_balance_href: str



class DrillRequest(BaseModel):
    filters: ReportFilter
    line_code: str
    account_id: Optional[int] = None
    account_ids: Optional[list[int]] = None
    account_type_filter: Optional[str] = None


class DrillLine(BaseModel):
    transaction_id: int
    txn_date: date
    description: str
    entity_id: int
    entity_code: Optional[str] = None
    bank_account_name: Optional[str] = None
    account_id: int
    account_code: str
    account_name: str
    department_id: Optional[int] = None
    native_amount: Decimal
    currency: str
    reporting_amount: Decimal
    signed_amount: Decimal  # statement presentation sign
    is_split: bool = False
    split_memo: Optional[str] = None
    status: str
    is_reconciled: bool = False


class WorkingPaperSnippet(BaseModel):
    """Embedded WP template shown on drill / working-paper drawer."""

    key: str
    wp_ref: str
    title: str
    purpose: str
    objective: str
    tie_out: str
    procedures: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class DrillOut(BaseModel):
    line_code: str
    line_label: str
    wp_ref: Optional[str] = None
    report_type: str
    currency: str
    filters: ReportFilter
    period_label: str
    statement_amount: Decimal
    detail_total: Decimal
    difference: Decimal
    is_tied: bool
    row_count: int
    lines: list[DrillLine]
    generated_at: str
    template: Optional[WorkingPaperSnippet] = None



class DashboardKPI(BaseModel):
    key: str
    label: str
    value: Decimal
    currency: Optional[str] = None
    format: str = "currency"  # currency | number | percent
    trend: Optional[Decimal] = None
    status: Optional[str] = None


class CashBalanceRow(BaseModel):
    bank_account_id: int
    name: str
    entity_code: str
    currency: str
    balance: Decimal
    balance_reporting: Decimal


class ReconHealthRow(BaseModel):
    """At-a-glance reconciliation health for a bank account."""

    bank_account_id: int
    name: str
    entity_code: str
    currency: str
    balance: Decimal
    budget_balance: Optional[Decimal] = None
    variance: Optional[Decimal] = None
    variance_pct: Optional[Decimal] = None
    on_target: Optional[bool] = None
    target_status: str  # on_target | above | below | no_budget
    last_reconciled_date: Optional[date] = None
    last_reconciled_period: Optional[str] = None
    days_since_reconciled: Optional[int] = None
    recon_freshness: str  # current | prior | stale | never
    current_period_status: str  # not_started | open | in_progress | completed | locked
    href: str


class DashboardNextAction(BaseModel):
    key: str
    kind: str
    priority: int
    title: str
    detail: str
    href: str
    count: Optional[int] = None
    amount: Optional[float] = None
    status: Optional[str] = None


class DashboardCloseSummary(BaseModel):
    period_year: int
    period_month: int
    period_label: str
    banks_total: int
    banks_locked: int
    banks_ready_to_lock: int
    banks_in_progress: int
    can_lock_month: bool
    all_locked: bool
    blocking_total: int = 0


class DashboardBinderSummary(BaseModel):
    period_year: int
    period_month: int
    period_label: str
    total: int
    prepared: int
    reviewed: int
    open: int
    untied: int
    href: str


class DashboardOut(BaseModel):
    kpis: list[DashboardKPI]
    cash_by_account: list[CashBalanceRow]
    recon_health: list[ReconHealthRow] = Field(default_factory=list)
    outstanding_reconciliations: int
    uncategorized_transactions: int
    unmatched_intercompany: int
    fx_exposure: list[dict] = Field(default_factory=list)
    intercompany_balances: list[dict] = Field(default_factory=list)
    close_summary: Optional[DashboardCloseSummary] = None
    next_actions: list[DashboardNextAction] = Field(default_factory=list)
    binder_summary: Optional[DashboardBinderSummary] = None
