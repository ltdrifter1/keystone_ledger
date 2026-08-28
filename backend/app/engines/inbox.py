"""Bank inbox actions: mark a line as an intra-entity transfer or intercompany."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.audit import write_audit
from app.engines.categorization import categorize_transaction
from app.engines.rules import KIND_INTERCOMPANY, KIND_TRANSFER, create_rule_from_transaction, payee_token
from app.engines.intercompany import auto_match_intercompany
from app.models import BankAccount, DimAccount, DimEntity, Transaction
from app.schemas.transactions import CategorizeRequest

CASH_TRANSFER_CODE = "1000"
INTERCOMPANY_CODE = "2100"


def account_by_code(db: Session, code: str) -> DimAccount:
    acct = db.scalar(select(DimAccount).where(DimAccount.code == code))
    if not acct:
        raise ValueError(f"GL {code} is not on the chart")
    return acct


def intercompany_account(db: Session) -> DimAccount:
    acct = db.scalar(select(DimAccount).where(DimAccount.code == INTERCOMPANY_CODE))
    if acct:
        return acct
    acct = db.scalar(
        select(DimAccount)
        .where(DimAccount.is_intercompany == True)  # noqa: E712
        .order_by(DimAccount.code)
    )
    if not acct:
        raise ValueError("No intercompany account on the chart")
    return acct


def mark_bank_transfer(
    db: Session,
    txn: Transaction,
    *,
    other_bank_account_id: int | None = None,
    create_rule: bool = True,
    actor: str = "controller",
) -> Transaction:
    """Post the line to GL 1000 (due to/from other banks of this entity)."""
    if other_bank_account_id is not None:
        other = db.get(BankAccount, other_bank_account_id)
        if not other:
            raise ValueError("Other bank account not found")
        if other.entity_id != txn.entity_id:
            raise ValueError("Transfer must stay on the same entity")
        if txn.bank_account_id and other.id == txn.bank_account_id:
            raise ValueError("Pick a different bank for the transfer")

    acct = account_by_code(db, CASH_TRANSFER_CODE)
    categorize_transaction(
        db,
        txn,
        CategorizeRequest(account_id=acct.id, create_rule=False),
        actor=actor,
    )
    if create_rule:
        token = payee_token(txn) or txn.counterparty or str(txn.id)
        create_rule_from_transaction(
            db,
            txn,
            name=f"Transfer: {token}",
            lock_bank_account=False,
            kind=KIND_TRANSFER,
            actor=actor,
        )
    write_audit(
        db,
        entity_table="transactions",
        entity_id=txn.id,
        action="mark_transfer",
        actor=actor,
        meta={
            "account_code": CASH_TRANSFER_CODE,
            "other_bank_account_id": other_bank_account_id,
        },
    )
    return txn


def mark_intercompany(
    db: Session,
    txn: Transaction,
    *,
    counter_entity_id: int,
    create_rule: bool = True,
    actor: str = "controller",
) -> Transaction:
    """Post the line to GL 2100 and tag the other entity."""
    if counter_entity_id == txn.entity_id:
        raise ValueError("Intercompany counterparty must be a different entity")
    counter = db.get(DimEntity, counter_entity_id)
    if not counter:
        raise ValueError("Counter entity not found")

    acct = intercompany_account(db)
    categorize_transaction(
        db,
        txn,
        CategorizeRequest(
            account_id=acct.id,
            counter_entity_id=counter_entity_id,
            create_rule=False,
        ),
        actor=actor,
    )
    if create_rule:
        token = payee_token(txn) or counter.code
        create_rule_from_transaction(
            db,
            txn,
            name=f"Intercompany: {token}",
            lock_bank_account=False,
            kind=KIND_INTERCOMPANY,
            actor=actor,
        )
    db.flush()
    auto_match_intercompany(db, actor=actor, txn_id=txn.id)
    write_audit(
        db,
        entity_table="transactions",
        entity_id=txn.id,
        action="mark_intercompany",
        actor=actor,
        meta={"account_code": acct.code, "counter_entity_id": counter_entity_id},
    )
    return txn
