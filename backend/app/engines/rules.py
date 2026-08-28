from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.audit import write_audit
from app.models import CategorizationRule, Transaction

KIND_GL = "gl"
KIND_TRANSFER = "bank_transfer"
KIND_INTERCOMPANY = "intercompany"
KIND_PRIORITY = {
    KIND_GL: 50,
    KIND_TRANSFER: 40,
    KIND_INTERCOMPANY: 35,
}

# Banking noise — not a payee. Prefer the merchant / counterparty token instead of the longest word.
_PAYEE_STOP = {
    "FROM",
    "WITH",
    "THIS",
    "THAT",
    "PAYMENT",
    "TRANSFER",
    "SWEEP",
    "DEPOSIT",
    "WITHDRAWAL",
    "FEE",
    "CHARGE",
    "CREDIT",
    "DEBIT",
    "ACH",
    "WIRE",
    "EFT",
    "PAD",
    "BILL",
    "THE",
    "AND",
    "FOR",
    "BANK",
    "ACCT",
    "ACCOUNT",
    "ONLINE",
    "PURCHASE",
    "POS",
    "ATM",
    "MONTHLY",
    "PREAUTHORIZED",
    "INTERCOMPANY",
    "INTERCO",
    "FUNDING",
    "OPERATING",
    "TO",
    "OF",
    "VIA",
    "REF",
    "LIVE",
    "FEED",
    "CLOSE",
    "TEST",
    "INBOX",
    "SETTLEMENT",
    "PAYROLL",
    "API",
}
_CURRENCY_TOKENS = {"USD", "CAD", "EUR", "GBP", "AUD", "MXN", "JPY", "CHF", "CNY"}


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
                meta={"rule_id": rule.id, "rule_name": rule.name, "rule_kind": rule.rule_kind},
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


def _first_payee_word(blob: Optional[str]) -> Optional[str]:
    if not blob:
        return None
    words = [w for w in re.split(r"\W+", blob) if len(w) >= 3]
    for word in words:
        upper = word.upper()
        if upper in _PAYEE_STOP or upper in _CURRENCY_TOKENS:
            continue
        if word.isdigit():
            continue
        return word
    return None


def payee_token(txn: Transaction) -> Optional[str]:
    """Payee-ish token: counterparty first, then the first non-generic word in the description."""
    for blob in (txn.counterparty, txn.description):
        token = _first_payee_word(blob)
        if token:
            return token
    return None


def description_token(txn: Transaction) -> Optional[str]:
    return payee_token(txn)


def preview_rule(
    db: Session,
    rule: CategorizationRule,
    *,
    uncategorized_only: bool = True,
    sample_limit: int = 20,
) -> dict:
    q = select(Transaction).where(Transaction.status != "void").order_by(Transaction.txn_date.desc(), Transaction.id.desc())
    if uncategorized_only:
        q = q.where(Transaction.status == "uncategorized", Transaction.account_id.is_(None))
    if rule.match_entity_id is not None:
        q = q.where(Transaction.entity_id == rule.match_entity_id)
    if rule.match_bank_account_id is not None:
        q = q.where(Transaction.bank_account_id == rule.match_bank_account_id)
    rows = list(db.scalars(q.limit(2000)))
    matched = [t for t in rows if rule_matches(rule, t)]
    uncat = [t for t in matched if t.status == "uncategorized" and t.account_id is None]
    sample = matched[:sample_limit]
    return {
        "matched_uncategorized": len(uncat) if uncategorized_only else sum(1 for t in matched if t.status == "uncategorized"),
        "matched_total": len(matched),
        "sample": sample,
    }


def create_rule_from_transaction(
    db: Session,
    txn: Transaction,
    *,
    name: Optional[str] = None,
    remember_description: bool = True,
    lock_bank_account: bool = False,
    kind: str = KIND_GL,
    actor: str = "system",
) -> CategorizationRule:
    if not txn.account_id:
        raise ValueError("Transaction must be categorized before creating a rule")

    token = payee_token(txn) if remember_description else None
    kind = kind if kind in KIND_PRIORITY else KIND_GL
    prefix = {"bank_transfer": "Transfer", "intercompany": "Intercompany"}.get(kind, "Auto")

    rule = CategorizationRule(
        name=name or f"{prefix}: {token or txn.counterparty or txn.id}",
        priority=KIND_PRIORITY[kind],
        is_active=True,
        rule_kind=kind,
        match_description_contains=token,
        match_counterparty=txn.counterparty,
        match_currency=txn.currency,
        match_entity_id=txn.entity_id,
        # Entity-wide by default so a remembered sweep/IC rule hits every bank of that company.
        match_bank_account_id=txn.bank_account_id if lock_bank_account else None,
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
