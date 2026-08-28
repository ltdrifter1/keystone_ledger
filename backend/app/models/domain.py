"""Core domain models — transactions are the center of the system."""

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


class BankAccount(Base):
    """Bank account is an attribute of transactions, not the system center."""

    __tablename__ = "bank_accounts"
    __table_args__ = (UniqueConstraint("entity_id", "account_number", name="uq_bank_entity_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("dim_entity.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    account_number: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3))
    institution: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    gl_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_account.id"), nullable=True)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    # Controller cash target / budget ending balance for health checks
    budget_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    entity: Mapped["DimEntity"] = relationship(back_populates="bank_accounts")  # noqa: F821
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="bank_account")
    reconciliations: Mapped[list["Reconciliation"]] = relationship(back_populates="bank_account")
    feed_connection: Mapped[Optional["BankFeedConnection"]] = relationship(
        back_populates="bank_account", uselist=False
    )


class Transaction(Base):
    """
    FACT-like transaction table — center of Keystone Ledger.

    Bank account, entity, department, and GL account are attributes.
    Supports bank imports, manual entries, and future ERP feeds without redesign.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Natural / import identity for duplicate detection
    external_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    txn_date: Mapped[date] = mapped_column(Date, index=True)
    post_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    description: Mapped[str] = mapped_column(String(512))
    memo: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    counterparty: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # signed: +inflow / -outflow
    currency: Mapped[str] = mapped_column(String(3), default="CAD")
    amount_reporting: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)

    # Dimensional attributes
    entity_id: Mapped[int] = mapped_column(ForeignKey("dim_entity.id"), index=True)
    bank_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bank_accounts.id"), nullable=True, index=True)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_account.id"), nullable=True, index=True)
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_department.id"), nullable=True, index=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("dim_scenario.id"), index=True)
    date_key: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_date.id"), nullable=True, index=True)

    # Intercompany
    counter_entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_entity.id"), nullable=True)
    intercompany_match_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transactions.id"), nullable=True)

    # Workflow
    source_type: Mapped[str] = mapped_column(String(32), default="bank_import", index=True)
    # bank_import | bank_feed | manual | erp_import | split_parent | journal
    status: Mapped[str] = mapped_column(String(32), default="uncategorized", index=True)
    # uncategorized | categorized | matched | excluded | void
    is_split: Mapped[bool] = mapped_column(Boolean, default=False)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    is_reconciled: Mapped[bool] = mapped_column(Boolean, default=False)
    reconciliation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reconciliations.id"), nullable=True)
    categorized_by_rule_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categorization_rules.id"), nullable=True
    )

    import_batch_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    updated_by: Mapped[str] = mapped_column(String(64), default="system")

    entity: Mapped["DimEntity"] = relationship(  # noqa: F821
        back_populates="transactions", foreign_keys=[entity_id]
    )
    bank_account: Mapped[Optional["BankAccount"]] = relationship(back_populates="transactions")
    account: Mapped[Optional["DimAccount"]] = relationship(foreign_keys=[account_id])  # noqa: F821
    department: Mapped[Optional["DimDepartment"]] = relationship()  # noqa: F821
    scenario: Mapped["DimScenario"] = relationship()  # noqa: F821
    splits: Mapped[list["TransactionSplit"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )
    reconciliation: Mapped[Optional["Reconciliation"]] = relationship(
        back_populates="transactions", foreign_keys=[reconciliation_id]
    )


class TransactionSplit(Base):
    """One-to-many categorization lines when a transaction is split."""

    __tablename__ = "transaction_splits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("dim_account.id"), index=True)
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_department.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    memo: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    transaction: Mapped["Transaction"] = relationship(back_populates="splits")
    account: Mapped["DimAccount"] = relationship()  # noqa: F821


class CategorizationRule(Base):
    """Remember previous categorizations — auto-apply on import."""

    __tablename__ = "categorization_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Match criteria (all non-null criteria must match)
    match_description_contains: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    match_description_regex: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    match_counterparty: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    match_amount_min: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    match_amount_max: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    match_currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    match_entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_entity.id"), nullable=True)
    match_bank_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bank_accounts.id"), nullable=True)

    # gl | bank_transfer | intercompany
    rule_kind: Mapped[str] = mapped_column(String(32), default="gl", index=True)

    # Action
    assign_account_id: Mapped[int] = mapped_column(ForeignKey("dim_account.id"))
    assign_department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_department.id"), nullable=True)
    assign_counter_entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_entity.id"), nullable=True)

    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    last_hit_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[str] = mapped_column(String(64), default="system")


class BankFeedConnection(Base):
    """Live bank-feed link for a bank account (Open Banking-style)."""

    __tablename__ = "bank_feed_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_account_id: Mapped[int] = mapped_column(
        ForeignKey("bank_accounts.id"), unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), default="keystone_open_banking")
    # disconnected | connected | error
    status: Mapped[str] = mapped_column(String(32), default="disconnected", index=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    last_balance_as_of: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    connected_by: Mapped[str] = mapped_column(String(64), default="controller")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bank_account: Mapped["BankAccount"] = relationship(back_populates="feed_connection")


class Reconciliation(Base):
    """Monthly bank reconciliation period per bank account."""

    __tablename__ = "reconciliations"
    __table_args__ = (UniqueConstraint("bank_account_id", "period_year", "period_month", name="uq_recon_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_account_id: Mapped[int] = mapped_column(ForeignKey("bank_accounts.id"), index=True)
    period_year: Mapped[int] = mapped_column(Integer, index=True)
    period_month: Mapped[int] = mapped_column(Integer, index=True)
    statement_ending_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    calculated_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    # open | in_progress | completed | locked
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    locked_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    bank_account: Mapped["BankAccount"] = relationship(back_populates="reconciliations")
    items: Mapped[list["ReconciliationItem"]] = relationship(
        back_populates="reconciliation", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="reconciliation", foreign_keys="Transaction.reconciliation_id"
    )


class ReconciliationItem(Base):
    __tablename__ = "reconciliation_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reconciliation_id: Mapped[int] = mapped_column(ForeignKey("reconciliations.id", ondelete="CASCADE"), index=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    is_cleared: Mapped[bool] = mapped_column(Boolean, default=False)
    cleared_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    reconciliation: Mapped["Reconciliation"] = relationship(back_populates="items")
    transaction: Mapped["Transaction"] = relationship(foreign_keys=[transaction_id])


class AuditLog(Base):
    """Complete audit trail of all edits."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_table: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(32))  # create | update | delete | categorize | reconcile | lock
    field_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_table: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    filename: Mapped[str] = mapped_column(String(256))
    content_type: Mapped[str] = mapped_column(String(128))
    storage_path: Mapped[str] = mapped_column(String(512))
    uploaded_by: Mapped[str] = mapped_column(String(64), default="system")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AppUser(Base):
    """Named closer — preparer / reviewer / admin. Actor on audit and sign-off."""

    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    initials: Mapped[str] = mapped_column(String(8), index=True)
    role: Mapped[str] = mapped_column(String(32), default="preparer")
    # preparer | reviewer | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WorkingPaperDocument(Base):
    """Period-scoped working paper state (CaseWare-style binder document)."""

    __tablename__ = "working_paper_documents"
    __table_args__ = (
        UniqueConstraint(
            "period_year",
            "period_month",
            "template_key",
            "entity_id",
            name="uq_wp_doc_period_key_entity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_year: Mapped[int] = mapped_column(Integer, index=True)
    period_month: Mapped[int] = mapped_column(Integer, index=True)
    template_key: Mapped[str] = mapped_column(String(64), index=True)
    # open | prepared | reviewed
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    checked_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list[int]
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preparer: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    preparer_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reviewer: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reviewer_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by: Mapped[str] = mapped_column(String(64), default="controller")
    entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("dim_entity.id"), nullable=True, index=True)


class EntityPeriodLock(Base):
    """Month-end GL lock for one company. Bank recs stay per-account; this freezes the books."""

    __tablename__ = "entity_period_locks"
    __table_args__ = (
        UniqueConstraint("entity_id", "period_year", "period_month", name="uq_entity_period_lock"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("dim_entity.id"), index=True)
    period_year: Mapped[int] = mapped_column(Integer, index=True)
    period_month: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(32), default="locked", index=True)  # locked
    locked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    locked_by: Mapped[str] = mapped_column(String(64), default="controller")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
