from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SplitIn(BaseModel):
    account_id: int
    amount: Decimal
    department_id: Optional[int] = None
    memo: Optional[str] = None
    sort_order: int = 0


class SplitOut(ORMModel):
    id: int
    transaction_id: int
    account_id: int
    department_id: Optional[int] = None
    amount: Decimal
    memo: Optional[str] = None
    sort_order: int


class TransactionOut(ORMModel):
    id: int
    external_id: Optional[str] = None
    fingerprint: Optional[str] = None
    txn_date: date
    post_date: Optional[date] = None
    description: str
    memo: Optional[str] = None
    reference: Optional[str] = None
    counterparty: Optional[str] = None
    amount: Decimal
    currency: str
    amount_reporting: Optional[Decimal] = None
    fx_rate: Optional[Decimal] = None
    entity_id: int
    bank_account_id: Optional[int] = None
    account_id: Optional[int] = None
    department_id: Optional[int] = None
    scenario_id: int
    counter_entity_id: Optional[int] = None
    intercompany_match_id: Optional[int] = None
    source_type: str
    status: str
    is_split: bool
    is_duplicate: bool
    is_reconciled: bool
    reconciliation_id: Optional[int] = None
    categorized_by_rule_id: Optional[int] = None
    import_batch_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    splits: list[SplitOut] = Field(default_factory=list)
    # Denormalized labels for grid UX
    entity_code: Optional[str] = None
    account_code: Optional[str] = None
    account_name: Optional[str] = None
    bank_account_name: Optional[str] = None
    is_period_locked: bool = False
    is_editable: bool = True


class TransactionCreate(BaseModel):
    txn_date: date
    description: str
    amount: Decimal
    currency: str = "CAD"
    entity_id: int
    scenario_id: int = 1
    bank_account_id: Optional[int] = None
    account_id: Optional[int] = None
    department_id: Optional[int] = None
    memo: Optional[str] = None
    reference: Optional[str] = None
    counterparty: Optional[str] = None
    counter_entity_id: Optional[int] = None
    source_type: str = "manual"
    post_date: Optional[date] = None
    external_id: Optional[str] = None


class TransactionUpdate(BaseModel):
    txn_date: Optional[date] = None
    description: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    entity_id: Optional[int] = None
    bank_account_id: Optional[int] = None
    account_id: Optional[int] = None
    department_id: Optional[int] = None
    scenario_id: Optional[int] = None
    memo: Optional[str] = None
    reference: Optional[str] = None
    counterparty: Optional[str] = None
    counter_entity_id: Optional[int] = None
    status: Optional[str] = None
    create_rule: bool = False
    rule_name: Optional[str] = None


class CategorizeRequest(BaseModel):
    account_id: int
    department_id: Optional[int] = None
    counter_entity_id: Optional[int] = None
    create_rule: bool = False
    rule_name: Optional[str] = None
    remember_description: bool = True


class BulkCategorizeRequest(BaseModel):
    transaction_ids: list[int]
    account_id: int
    department_id: Optional[int] = None
    create_rule: bool = False


class SplitRequest(BaseModel):
    splits: list[SplitIn]


class TransactionFilter(BaseModel):
    entity_id: Optional[int] = None
    bank_account_id: Optional[int] = None
    account_id: Optional[int] = None
    department_id: Optional[int] = None
    scenario_id: Optional[int] = None
    status: Optional[str] = None
    currency: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    search: Optional[str] = None
    uncategorized_only: bool = False
    unreconciled_only: bool = False
    duplicates_only: bool = False
    unmatched_ic_only: bool = False
    limit: int = 200
    offset: int = 0


class ImportResult(BaseModel):
    batch_id: str
    imported: int
    duplicates_flagged: int
    auto_categorized: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class IntercompanyMatchOut(BaseModel):
    left_id: int
    right_id: int
    amount: Decimal
    left_entity_id: int
    right_entity_id: int
    confidence: str


class ReconciliationOut(ORMModel):
    id: int
    bank_account_id: int
    period_year: int
    period_month: int
    statement_ending_balance: Decimal
    calculated_balance: Optional[Decimal] = None
    difference: Optional[Decimal] = None
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    locked_at: Optional[datetime] = None
    locked_by: Optional[str] = None
    notes: Optional[str] = None
    uncleared_count: int = 0
    cleared_count: int = 0


class ReconciliationCreate(BaseModel):
    bank_account_id: int
    period_year: int
    period_month: int
    statement_ending_balance: Decimal
    notes: Optional[str] = None


class ReconciliationClearRequest(BaseModel):
    transaction_ids: list[int]
    is_cleared: bool = True
