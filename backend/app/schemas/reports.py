from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class ReportFilter(BaseModel):
    report_type: str = "income_statement"
    # income_statement | balance_sheet | cash_flow
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


class ReportLine(BaseModel):
    line_code: str
    line_label: str
    section: str
    amount: Decimal
    compare_amount: Optional[Decimal] = None
    variance: Optional[Decimal] = None
    variance_pct: Optional[Decimal] = None
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


class DashboardOut(BaseModel):
    kpis: list[DashboardKPI]
    cash_by_account: list[CashBalanceRow]
    outstanding_reconciliations: int
    uncategorized_transactions: int
    unmatched_intercompany: int
    fx_exposure: list[dict] = Field(default_factory=list)
    intercompany_balances: list[dict] = Field(default_factory=list)
