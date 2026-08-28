from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class EngagementProgress(BaseModel):
    banks_total: int = 0
    banks_locked: int = 0
    blocking_total: int = 0
    uncategorized: int = 0
    binder_total: int = 0
    binder_reviewed: int = 0
    binder_untied: int = 0
    cash_ready: bool = False
    feeds_connected: int = 0
    feeds_pending: int = 0
    unmatched_ic: int = 0
    journals: int = 0
    month_locked: bool = False
    journal_led: bool = False
    statements_balanced: bool = False
    can_print: bool = False


class EngagementQueueItem(BaseModel):
    key: str
    step: int
    phase: str
    priority: int
    title: str
    detail: str
    href: str
    count: Optional[int] = None
    status: str = "open"


class MonthLockOut(BaseModel):
    entity_id: int
    period_year: int
    period_month: int
    is_locked: bool
    locked_at: Optional[str] = None
    locked_by: Optional[str] = None
    notes: Optional[str] = None
    journal_led: bool = False


class EngagementHomeOut(BaseModel):
    period_year: int
    period_month: int
    period_label: str
    entity_id: Optional[int] = None
    entity_code: Optional[str] = None
    entity_name: Optional[str] = None
    journal_led: bool = False
    month_lock: Optional[MonthLockOut] = None
    progress: EngagementProgress
    queue: list[EngagementQueueItem] = Field(default_factory=list)
    work_href: str
    binder_href: str
    statements_href: str
