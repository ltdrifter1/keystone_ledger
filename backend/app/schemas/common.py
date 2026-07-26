from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EntityOut(ORMModel):
    id: int
    code: str
    name: str
    country: str
    functional_currency: str
    parent_entity_id: Optional[int] = None
    is_active: bool


class EntityCreate(BaseModel):
    code: str
    name: str
    country: str
    functional_currency: str = "CAD"
    parent_entity_id: Optional[int] = None


class AccountOut(ORMModel):
    id: int
    code: str
    name: str
    account_type: str
    statement: str
    normal_balance: str
    parent_account_id: Optional[int] = None
    cash_flow_section: Optional[str] = None
    is_cash: bool
    is_intercompany: bool
    sort_order: int
    is_active: bool


class AccountCreate(BaseModel):
    code: str
    name: str
    account_type: str
    statement: str
    normal_balance: str = "debit"
    parent_account_id: Optional[int] = None
    cash_flow_section: Optional[str] = None
    is_cash: bool = False
    is_intercompany: bool = False
    sort_order: int = 0


class DepartmentOut(ORMModel):
    id: int
    code: str
    name: str
    entity_id: Optional[int] = None
    is_active: bool


class ScenarioOut(ORMModel):
    id: int
    code: str
    name: str
    scenario_type: str
    is_active: bool


class BankAccountOut(ORMModel):
    id: int
    entity_id: int
    name: str
    account_number: str
    currency: str
    institution: Optional[str] = None
    gl_account_id: Optional[int] = None
    opening_balance: Decimal
    budget_balance: Optional[Decimal] = None
    is_active: bool


class BankAccountCreate(BaseModel):
    entity_id: int
    name: str
    account_number: str
    currency: str
    institution: Optional[str] = None
    gl_account_id: Optional[int] = None
    opening_balance: Decimal = Decimal("0")
    budget_balance: Optional[Decimal] = None


class FxRateOut(ORMModel):
    id: int
    from_currency: str
    to_currency: str
    rate_date: date
    rate: Decimal
    rate_type: str


class FxRateCreate(BaseModel):
    from_currency: str
    to_currency: str
    rate_date: date
    rate: Decimal
    rate_type: str = "spot"


class RuleOut(ORMModel):
    id: int
    name: str
    priority: int
    is_active: bool
    match_description_contains: Optional[str] = None
    match_description_regex: Optional[str] = None
    match_counterparty: Optional[str] = None
    match_amount_min: Optional[Decimal] = None
    match_amount_max: Optional[Decimal] = None
    match_currency: Optional[str] = None
    match_entity_id: Optional[int] = None
    match_bank_account_id: Optional[int] = None
    assign_account_id: int
    assign_department_id: Optional[int] = None
    assign_counter_entity_id: Optional[int] = None
    hit_count: int


class RuleCreate(BaseModel):
    name: str
    priority: int = 100
    is_active: bool = True
    match_description_contains: Optional[str] = None
    match_description_regex: Optional[str] = None
    match_counterparty: Optional[str] = None
    match_amount_min: Optional[Decimal] = None
    match_amount_max: Optional[Decimal] = None
    match_currency: Optional[str] = None
    match_entity_id: Optional[int] = None
    match_bank_account_id: Optional[int] = None
    assign_account_id: int
    assign_department_id: Optional[int] = None
    assign_counter_entity_id: Optional[int] = None


class AuditLogOut(ORMModel):
    id: int
    entity_table: str
    entity_id: int
    action: str
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    actor: str
    created_at: datetime


class MessageOut(BaseModel):
    message: str
    detail: Optional[dict] = None
