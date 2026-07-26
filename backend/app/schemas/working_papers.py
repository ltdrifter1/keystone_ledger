from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class WorkingPaperTemplateOut(BaseModel):
    key: str
    wp_ref: str
    title: str
    statement: str
    section: str
    purpose: str
    objective: str
    tie_out: str
    procedures: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    line_codes: list[str] = Field(default_factory=list)
    account_codes: list[str] = Field(default_factory=list)
    sort_order: int = 0


class WorkingPaperTemplateListOut(BaseModel):
    templates: list[WorkingPaperTemplateOut]
    count: int


class BinderCashClose(BaseModel):
    banks_total: int = 0
    banks_locked: int = 0
    banks_ready_to_lock: int = 0
    all_locked: bool = False
    blocking_total: int = 0


class BinderSummary(BaseModel):
    total: int
    prepared: int
    reviewed: int
    open: int
    untied: int
    cash_close: Optional[BinderCashClose] = None


class BinderDocumentIndex(BaseModel):
    key: str
    wp_ref: str
    title: str
    statement: str
    section: str
    purpose: str
    line_code: str
    statement_amount: float
    currency: str = "CAD"
    is_tied: Optional[bool] = None
    difference: Optional[float] = None
    status: str
    procedure_count: int
    procedures_done: int
    procedure_pct: int
    preparer: Optional[str] = None
    preparer_at: Optional[str] = None
    reviewer: Optional[str] = None
    reviewer_at: Optional[str] = None
    close_status: Optional[str] = None
    href: str
    report_href: str
    close_href: Optional[str] = None


class BinderOut(BaseModel):
    period_year: int
    period_month: int
    period_label: str
    period_end: str
    documents: list[BinderDocumentIndex]
    summary: BinderSummary


class BinderDrillLine(BaseModel):
    transaction_id: int
    txn_date: str
    description: str
    entity_code: Optional[str] = None
    account_code: str
    account_name: str
    signed_amount: float
    currency: str
    is_reconciled: bool = False


class BinderDrill(BaseModel):
    line_code: str
    line_label: str
    wp_ref: Optional[str] = None
    statement_amount: float
    detail_total: float
    difference: float
    is_tied: bool
    row_count: int
    period_label: str
    currency: str
    lines: list[BinderDrillLine] = Field(default_factory=list)


class BinderDocumentOut(BinderDocumentIndex):
    period_year: int
    period_month: int
    period_label: str
    period_end: str
    objective: str
    tie_out: str
    procedures: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    checked: list[int] = Field(default_factory=list)
    notes: Optional[str] = None
    drill: Optional[BinderDrill] = None
    filters: dict[str, Any] = Field(default_factory=dict)


class BinderDocumentUpdate(BaseModel):
    checked: Optional[list[int]] = None
    notes: Optional[str] = None
    preparer: Optional[str] = None
    reviewer: Optional[str] = None
    status: Optional[str] = None  # open | prepared | reviewed
