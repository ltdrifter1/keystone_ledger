from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.audit import write_audit
from app.models import CategorizationRule, Transaction


def rule_matches(rule: CategorizationRule, txn: Transaction) -> bool:
    if rule.match_entity_id is not None and rule.match_entity_id != txn.entity_id:
        return False
    if rule.match_bank_account_id is not None and rule.match_bank_account_id != txn.bank_account_id:
        return False
    if rule.match_currency is not None and rule.match_currency != txn.currency:
        return False
    if rule.match_counterparty and (txn.counterparty or "").upper() != rule.match_counterparty.upper():
        return False
    if rule.match_amount_min is not None and abs(txn.amount) < rule.match_amount_min:
        return False
    if rule.match_amount_max is not None and abs(txn.amount) > rule.match_amount_max:
        return False
    desc = txn.description or ""
    if rule.match_description_contains:
        if rule.match_description_contains.upper() not in desc.upper():
            return False
    if rule.match_description_regex:
        try:
            if not re.search(rule.match_description_regex, desc, re.IGNORECASE):
                return False
        except re.error:
            return False
    return True


def apply_rules_to_transaction(
    db: Session,
    txn: Transaction,
    rules: Optional[list[CategorizationRule]] = None,
    actor: str = "system",
) -> bool:
    """Apply first matching rule. Returns True if categorized."""
    if txn.account_id is not None or txn.is_split:
        return False

    if rules is None:
        rules = list(
            db.scalars(
                select(CategorizationRule)
                .where(CategorizationRule.is_active == True)
                .order_by(CategorizationRule.priority.asc(), CategorizationRule.id.asc())
            )
        )

    for rule in rules:
        if rule_matches(rule, txn):
            txn.account_id = rule.assign_account_id
            txn.department_id = rule.assign_department_id or txn.department_id
            txn.counter_entity_id = rule.assign_counter_entity_id or txn.counter_entity_id
            txn.categorized_by_rule_id = rule.id
            txn.status = "categorized"
            rule.hit_count = (rule.hit_count or 0) + 1
            rule.last_hit_at = datetime.utcnow()
            write_audit(
                db,
                entity_table="transactions",
                entity_id=txn.id if txn.id else 0,
                action="categorize",
                field_name="account_id",
                new_value=rule.assign_account_id,
                actor=actor,
                meta={"rule_id": rule.id, "rule_name": rule.name},
            )
            return True
    return False


def apply_rules_batch(db: Session, transactions: list[Transaction], actor: str = "system") -> int:
    rules = list(
        db.scalars(
            select(CategorizationRule)
            .where(CategorizationRule.is_active == True)
            .order_by(CategorizationRule.priority.asc(), CategorizationRule.id.asc())
        )
    )
    count = 0
    for txn in transactions:
        if apply_rules_to_transaction(db, txn, rules=rules, actor=actor):
            count += 1
    return count


def create_rule_from_transaction(
    db: Session,
    txn: Transaction,
    *,
    name: Optional[str] = None,
    remember_description: bool = True,
    actor: str = "system",
) -> CategorizationRule:
    if not txn.account_id:
        raise ValueError("Transaction must be categorized before creating a rule")

    token = None
    if remember_description and txn.description:
        # Use a distinctive token from description (longest word >= 4 chars)
        words = [w for w in re.split(r"\W+", txn.description) if len(w) >= 4]
        token = max(words, key=len) if words else txn.description[:40]

    rule = CategorizationRule(
        name=name or f"Auto: {token or txn.counterparty or txn.id}",
        priority=50,
        match_description_contains=token,
        match_counterparty=txn.counterparty,
        match_currency=txn.currency,
        match_entity_id=txn.entity_id,
        match_bank_account_id=txn.bank_account_id,
        assign_account_id=txn.account_id,
        assign_department_id=txn.department_id,
        assign_counter_entity_id=txn.counter_entity_id,
        created_by=actor,
    )
    db.add(rule)
    db.flush()
    write_audit(
        db,
        entity_table="categorization_rules",
        entity_id=rule.id,
        action="create",
        actor=actor,
        meta={"from_transaction_id": txn.id},
    )
    return rule


def suggest_amount_band(amount: Decimal) -> tuple[Decimal, Decimal]:
    """Optional helper for amount-banded rules."""
    abs_amt = abs(amount)
    return (abs_amt * Decimal("0.98"), abs_amt * Decimal("1.02"))
