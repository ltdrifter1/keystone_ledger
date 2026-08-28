"""Star-schema dimension tables for filter-driven reporting."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DimEntity(Base):
    __tablename__ = "dim_entity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(64))
    functional_currency: Mapped[str] = mapped_column(String(3), default="CAD")
    parent_entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_entity.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    consolidation_method: Mapped[str] = mapped_column(String(32), default="full")  # full | equity | none
    fiscal_year_end_month: Mapped[int] = mapped_column(Integer, default=7)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    parent: Mapped[Optional["DimEntity"]] = relationship(remote_side=[id])
    bank_accounts: Mapped[list["BankAccount"]] = relationship(back_populates="entity")  # noqa: F821
    transactions: Mapped[list["Transaction"]] = relationship(  # noqa: F821
        back_populates="entity",
        foreign_keys="Transaction.entity_id",
    )


class DimAccount(Base):
    """Chart of accounts / reporting buckets."""

    __tablename__ = "dim_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    account_type: Mapped[str] = mapped_column(String(32), index=True)
    # asset | liability | equity | revenue | expense | transfer | intercompany
    statement: Mapped[str] = mapped_column(String(32), index=True)
    # income_statement | balance_sheet | cash_flow | none
    normal_balance: Mapped[str] = mapped_column(String(8), default="debit")  # debit | credit
    parent_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_account.id"), nullable=True)
    cash_flow_section: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_cash: Mapped[bool] = mapped_column(Boolean, default=False)
    is_intercompany: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    parent: Mapped[Optional["DimAccount"]] = relationship(remote_side=[id])


class DimDepartment(Base):
    __tablename__ = "dim_department"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_entity.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class DimDate(Base):
    __tablename__ = "dim_date"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # YYYYMMDD
    full_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    quarter: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer, index=True)
    month_name: Mapped[str] = mapped_column(String(16))
    day: Mapped[int] = mapped_column(Integer)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    fiscal_period: Mapped[int] = mapped_column(Integer)
    is_month_end: Mapped[bool] = mapped_column(Boolean, default=False)
    is_quarter_end: Mapped[bool] = mapped_column(Boolean, default=False)
    is_year_end: Mapped[bool] = mapped_column(Boolean, default=False)


class DimScenario(Base):
    __tablename__ = "dim_scenario"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    scenario_type: Mapped[str] = mapped_column(String(32), default="actual")
    # actual | budget | forecast | prior_year
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class DimFx(Base):
    __tablename__ = "dim_fx"
    __table_args__ = (
        UniqueConstraint("from_currency", "to_currency", "rate_date", "rate_type", name="uq_fx_pair_date_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_currency: Mapped[str] = mapped_column(String(3), index=True)
    to_currency: Mapped[str] = mapped_column(String(3), index=True)
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    rate_type: Mapped[str] = mapped_column(String(16), default="spot")  # spot | average | closing


class DimReportLayout(Base):
    """Defines row structure for IS / BS / CF report rendering."""

    __tablename__ = "dim_report_layout"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_type: Mapped[str] = mapped_column(String(32), index=True)
    # income_statement | balance_sheet | cash_flow
    section: Mapped[str] = mapped_column(String(64))
    line_code: Mapped[str] = mapped_column(String(32))
    line_label: Mapped[str] = mapped_column(String(128))
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_account.id"), nullable=True)
    account_type_filter: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    calc_formula: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    indent_level: Mapped[int] = mapped_column(Integer, default=0)
    is_bold: Mapped[bool] = mapped_column(Boolean, default=False)
    is_total: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    sign_flip: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
