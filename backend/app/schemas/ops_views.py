"""Quick-view schemas for Sales, Expenses, and Budget overview tabs."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class OpsKpi(BaseModel):
    key: str
    label: str
    amount: float
    compare_amount: Optional[float] = None
    variance: Optional[float] = None
    variance_pct: Optional[float] = None
    tone: str = "neutral"  # neutral | ok | warn | danger


class OpsLine(BaseModel):
    line_code: str
    line_label: str
    section: str
    amount: float
    compare_amount: Optional[float] = None
    variance: Optional[float] = None
    variance_pct: Optional[float] = None
    indent_level: int = 0
    is_bold: bool = False
    is_total: bool = False
    drillable: bool = False
    account_id: Optional[int] = None
    account_ids: list[int] = Field(default_factory=list)
    account_type_filter: Optional[str] = None
    wp_ref: Optional[str] = None
    href: Optional[str] = None


class SalesViewOut(BaseModel):
    title: str = "Sales"
    period_label: str
    period_year: int
    period_month: int
    currency: str = "CAD"
    entity_id: Optional[int] = None
    entity_code: Optional[str] = None
    kpis: list[OpsKpi] = Field(default_factory=list)
    lines: list[OpsLine] = Field(default_factory=list)
    top_channels: list[OpsLine] = Field(default_factory=list)
    report_filters: dict = Field(default_factory=dict)


class ExpensesViewOut(BaseModel):
    title: str = "Expenses"
    period_label: str
    period_year: int
    period_month: int
    currency: str = "CAD"
    entity_id: Optional[int] = None
    entity_code: Optional[str] = None
    kpis: list[OpsKpi] = Field(default_factory=list)
    lines: list[OpsLine] = Field(default_factory=list)
    report_filters: dict = Field(default_factory=dict)


class CashBudgetRow(BaseModel):
    bank_account_id: int
    bank_account_name: str
    entity_code: Optional[str] = None
    currency: str
    book_balance: float
    budget_balance: Optional[float] = None
    variance: Optional[float] = None
    variance_pct: Optional[float] = None
    status: str = "no_budget"  # on_target | above | below | no_budget
    href: str


class BudgetViewOut(BaseModel):
    title: str = "Budget overview"
    period_label: str
    period_year: int
    period_month: int
    currency: str = "CAD"
    entity_id: Optional[int] = None
    entity_code: Optional[str] = None
    pnl_kpis: list[OpsKpi] = Field(default_factory=list)
    pnl_lines: list[OpsLine] = Field(default_factory=list)
    cash_rows: list[CashBudgetRow] = Field(default_factory=list)
    budget_facts_ready: bool = False
    report_filters: dict = Field(default_factory=dict)
