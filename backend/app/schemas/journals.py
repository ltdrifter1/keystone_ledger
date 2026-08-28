from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class JournalLineIn(BaseModel):
    account_id: int
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    memo: Optional[str] = None


class JournalCreate(BaseModel):
    txn_date: date
    entity_id: int
    description: str
    lines: list[JournalLineIn] = Field(min_length=2)
    memo: Optional[str] = None
    working_paper_key: Optional[str] = None
    source_transaction_id: Optional[int] = None
    currency: str = "CAD"
    scenario_id: int = 1


class JournalLineOut(BaseModel):
    account_id: int
    account_code: Optional[str] = None
    account_name: Optional[str] = None
    debit: float
    credit: float
    amount: float
    memo: Optional[str] = None


class JournalOut(BaseModel):
    id: int
    voucher: Optional[str] = None
    txn_date: str
    description: str
    memo: Optional[str] = None
    entity_id: int
    entity_code: Optional[str] = None
    currency: str
    source_type: str
    working_paper_key: Optional[str] = None
    lines: list[JournalLineOut] = Field(default_factory=list)
    created_by: Optional[str] = None
    created_at: Optional[str] = None
