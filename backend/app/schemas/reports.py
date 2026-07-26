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


class ReportOut(BaseModel):
    report_type: str
    title: str
    filters: ReportFilter
    lines: list[ReportLine]
    generated_at: str
    currency: str


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
