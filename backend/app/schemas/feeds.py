from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.transactions import ImportResult


class FeedPendingItem(BaseModel):
    txn_date: date
    description: str
    amount: Decimal
    currency: str
    external_id: Optional[str] = None
    reference: Optional[str] = None
    counterparty: Optional[str] = None


class BankFeedOut(ORMModel):
    id: int
    bank_account_id: int
    bank_account_name: str
    entity_id: int
    entity_code: Optional[str] = None
    account_number: str
    currency: str
    institution: Optional[str] = None
    provider: str
    status: str
    last_synced_at: Optional[datetime] = None
    last_balance: Optional[Decimal] = None
    last_balance_as_of: Optional[date] = None
    error_message: Optional[str] = None
    connected_at: Optional[datetime] = None
    pending_count: int = 0
    is_stale: bool = True
    href: str = ""
    pending: list[FeedPendingItem] = Field(default_factory=list)


class FeedSyncOut(BaseModel):
    bank_account_id: int
    status: str
    imported: int
    duplicates_flagged: int
    auto_categorized: int
    skipped: int
    pending_remaining: int
    last_balance: Decimal
    last_balance_as_of: date
    last_synced_at: datetime
    statement_ending_balance: Optional[Decimal] = None
    errors: list[str] = Field(default_factory=list)
    import_result: Optional[ImportResult] = None
    feed: BankFeedOut
