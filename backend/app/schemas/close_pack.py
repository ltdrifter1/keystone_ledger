from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CloseException(BaseModel):
    kind: str
    message: str
    transaction_id: int
    txn_date: str
    description: str
    amount: float
    currency: str
    status: str
    is_split: bool = False
    is_duplicate: bool = False
    is_cleared: bool = False
    in_period: bool = True
    account_id: Optional[int] = None
    account_code: Optional[str] = None
    account_name: Optional[str] = None
    counter_entity_id: Optional[int] = None
    intercompany_match_id: Optional[int] = None
    blocking: bool = True


class ClosePackStatus(BaseModel):
    reconciliation_id: Optional[int] = None
    bank_account_id: int
    bank_account_name: Optional[str] = None
    entity_code: Optional[str] = None
    currency: Optional[str] = None
    period_year: int
    period_month: int
    period_label: str
    status: str
    beginning_balance: float
    statement_ending_balance: Optional[float] = None
    calculated_balance: Optional[float] = None
    cleared_total: Optional[float] = None
    difference: Optional[float] = None
    cleared_count: int = 0
    uncleared_count: int = 0
    exception_count: int = 0
    blocking_count: int = 0
    uncategorized_count: int = 0
    duplicate_count: int = 0
    can_lock: bool = False
    is_locked: bool = False
    exceptions: list[CloseException] = Field(default_factory=list)
    locked_at: Optional[str] = None
    locked_by: Optional[str] = None
    # Present on run response
    created_reconciliation: Optional[bool] = None
    auto_cleared: Optional[int] = None
    rules_applied: Optional[int] = None
    import_result: Optional[dict[str, Any]] = None
    unmatched_intercompany_global: Optional[int] = None


class CloseNextAction(BaseModel):
    key: str
    kind: str  # categorize | difference | duplicate | ready_to_lock | not_started | intercompany
    priority: int
    title: str
    detail: str
    bank_account_id: int
    bank_account_name: Optional[str] = None
    reconciliation_id: Optional[int] = None
    mode: str = "exceptions"  # exceptions | items
    filter: Optional[str] = None
    count: Optional[int] = None
    amount: Optional[float] = None


class MonthCloseOverview(BaseModel):
    period_year: int
    period_month: int
    period_label: str
    banks_total: int
    banks_locked: int
    banks_ready_to_lock: int
    banks_in_progress: int = 0
    can_lock_month: bool
    all_locked: bool
    packs: list[ClosePackStatus]
    next_actions: list[CloseNextAction] = Field(default_factory=list)
    newly_locked: list[int] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class CategorizeExceptionRequest(BaseModel):
    account_id: int
    create_rule: bool = True
    clear_after: bool = True


class ClearExceptionRequest(BaseModel):
    is_cleared: bool = True
