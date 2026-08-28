"""Double-entry ledger: bank activity is cash + the other side; journals stay as posted.

Bank-signed storage (+inflow / -outflow) is converted to debit/credit at this layer.
Uncategorized bank lines hit suspense 9999. Interbank sweeps coded to 1000 on a
child cash account (1010/…) are remapped to 1090 so 1000 can remain USA cash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.engines.fx import translate_amount
from app.engines.journals import bank_amount_from_debit_credit
from app.models import BankAccount, DimAccount, Transaction

SUSPENSE_CODE = "9999"
INTERBANK_CODE = "1090"
JOURNAL_SOURCES = {"journal", "post_close_adj"}
OPENING_MEMO = "Opening balance"


@dataclass
class GlLine:
    txn: object
    txn_date: date
    entity_id: int
    account_id: int
    department_id: Optional[int]
    debit: Decimal
    credit: Decimal
    currency: str
    memo: str
    description: str
    is_opening: bool = False

    @property
    def net_debit(self) -> Decimal:
        return self.debit - self.credit

    def bank_signed(self, account: DimAccount) -> Decimal:
        return net_debit_to_bank_signed(account, self.net_debit)


def _d(value: Decimal | str | int | float | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def net_debit_to_bank_signed(account: DimAccount, net_debit: Decimal) -> Decimal:
    if account.account_type in ("revenue", "expense"):
        return -net_debit
    return net_debit


def bank_signed_to_debit_credit(account: DimAccount, amount: Decimal) -> tuple[Decimal, Decimal]:
    """Inverse of journals.bank_amount_from_debit_credit."""
    amount = _d(amount)
    if account.account_type in ("revenue", "expense"):
        net_debit = -amount
    else:
        net_debit = amount
    if net_debit >= 0:
        return net_debit, Decimal("0")
    return Decimal("0"), -net_debit


def is_journal_txn(txn: Transaction) -> bool:
    if txn.source_type in JOURNAL_SOURCES:
        return True
    return txn.bank_account_id is None and bool(txn.is_split)


def ensure_ledger_accounts(db: Session) -> dict[str, DimAccount]:
    """Idempotent 9999 suspense + 1090 interbank clearing."""
    existing = {a.code: a for a in db.scalars(select(DimAccount)).all()}
    created = False
    if SUSPENSE_CODE not in existing:
        acct = DimAccount(
            code=SUSPENSE_CODE,
            name="Uncategorized (suspense)",
            account_type="asset",
            statement="balance_sheet",
            normal_balance="debit",
            is_cash=False,
            is_intercompany=False,
            sort_order=95,
        )
        db.add(acct)
        created = True
    if INTERBANK_CODE not in existing:
        parent = existing.get("1000")
        acct = DimAccount(
            code=INTERBANK_CODE,
            name="Due to / from other bank accounts",
            account_type="asset",
            statement="balance_sheet",
            normal_balance="debit",
            parent_account_id=parent.id if parent else None,
            is_cash=False,
            is_intercompany=False,
            sort_order=15,
        )
        db.add(acct)
        created = True
    if created:
        db.flush()
    return {a.code: a for a in db.scalars(select(DimAccount)).all()}


def _opening_proxy(bank: BankAccount, cash_id: int, as_of: date) -> SimpleNamespace:
    opening = _d(bank.opening_balance)
    return SimpleNamespace(
        id=-bank.id,
        currency=bank.currency,
        txn_date=as_of,
        entity_id=bank.entity_id,
        entity=None,
        bank_account=bank,
        is_split=False,
        splits=[],
        memo=OPENING_MEMO,
        account_id=cash_id,
        department_id=None,
        amount=opening,
        status="posted",
        is_reconciled=True,
        description=f"Opening balance — {bank.name}",
        source_type="opening",
        counterparty="",
        counter_entity_id=None,
        intercompany_match_id=None,
        is_duplicate=False,
        is_editable=True,
    )


def _default_cash_id(by_code: dict[str, DimAccount], suspense: DimAccount) -> int:
    cash = by_code.get("1000")
    return cash.id if cash else suspense.id


def _cash_account_id(
    txn: Transaction,
    accounts: dict[int, DimAccount],
    by_code: dict[str, DimAccount],
    suspense: DimAccount,
) -> int:
    bank = txn.bank_account
    if bank and bank.gl_account_id and bank.gl_account_id in accounts:
        return bank.gl_account_id
    return _default_cash_id(by_code, suspense)


def _remap_other_account(
    account: DimAccount,
    cash_acct: DimAccount,
    by_code: dict[str, DimAccount],
) -> DimAccount:
    """Other-side cash (sweeps, self-coded, 1000 on a child bank) belongs on 1090."""
    interbank = by_code.get(INTERBANK_CODE)
    if not interbank:
        return account
    if account.id == cash_acct.id or account.is_cash:
        return interbank
    return account


def _other_shares(txn: Transaction, suspense: DimAccount) -> list[tuple[int, Decimal, Optional[int], str]]:
    """(account_id, bank-signed share, department_id, memo) summing to the cash movement."""
    if txn.is_split and txn.splits:
        out = []
        for split in txn.splits:
            out.append((split.account_id, _d(split.amount), split.department_id, split.memo or ""))
        return out
    if txn.account_id:
        return [(txn.account_id, _d(txn.amount), txn.department_id, txn.memo or "")]
    return [(suspense.id, _d(txn.amount), txn.department_id, txn.memo or "uncategorized")]


def iter_gl_lines(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    scenario_id: int,
    entity_ids: Optional[list[int]],
    department_ids: Optional[list[int]] = None,
    include_openings: bool = False,
) -> Iterable[GlLine]:
    by_code = ensure_ledger_accounts(db)
    suspense = by_code[SUSPENSE_CODE]
    accounts = {a.id: a for a in by_code.values()}

    q = (
        select(Transaction)
        .options(
            joinedload(Transaction.splits),
            joinedload(Transaction.bank_account),
            joinedload(Transaction.entity),
        )
        .where(
            Transaction.scenario_id == scenario_id,
            Transaction.txn_date >= date_from,
            Transaction.txn_date <= date_to,
            Transaction.status.notin_(["void", "excluded"]),
        )
    )
    if entity_ids:
        q = q.where(Transaction.entity_id.in_(entity_ids))

    txns = db.scalars(q).unique().all()
    for txn in txns:
        bank = txn.bank_account
        if bank is not None and not bank.is_active:
            continue
        if is_journal_txn(txn):
            splits = list(txn.splits) if txn.is_split and txn.splits else []
            if not splits and txn.account_id:
                splits = [
                    SimpleNamespace(
                        account_id=txn.account_id,
                        amount=txn.amount,
                        department_id=txn.department_id,
                        memo=txn.memo,
                    )
                ]
            for split in splits:
                if department_ids and split.department_id not in department_ids:
                    continue
                acct = accounts.get(split.account_id)
                if not acct:
                    continue
                debit, credit = bank_signed_to_debit_credit(acct, _d(split.amount))
                if debit == 0 and credit == 0:
                    continue
                yield GlLine(
                    txn=txn,
                    txn_date=txn.txn_date,
                    entity_id=txn.entity_id,
                    account_id=acct.id,
                    department_id=split.department_id,
                    debit=debit,
                    credit=credit,
                    currency=txn.currency,
                    memo=split.memo or "",
                    description=txn.description,
                )
            continue

        shares = _other_shares(txn, suspense)
        if department_ids:
            shares = [s for s in shares if s[2] in department_ids]
            if not shares:
                continue

        cash_id = _cash_account_id(txn, accounts, by_code, suspense)
        cash_share = sum((s[1] for s in shares), Decimal("0")) if department_ids else _d(txn.amount)
        cash_acct = accounts.get(cash_id) or suspense
        cash_debit, cash_credit = bank_signed_to_debit_credit(cash_acct, cash_share)
        if cash_debit or cash_credit:
            yield GlLine(
                txn=txn,
                txn_date=txn.txn_date,
                entity_id=txn.entity_id,
                account_id=cash_acct.id,
                department_id=None,
                debit=cash_debit,
                credit=cash_credit,
                currency=txn.currency,
                memo="",
                description=txn.description,
            )

        for account_id, share, dept_id, memo in shares:
            acct = accounts.get(account_id) or suspense
            acct = _remap_other_account(acct, cash_acct, by_code)
            abs_share = abs(_d(share))
            if abs_share == 0:
                continue
            if share < 0:
                debit, credit = abs_share, Decimal("0")
            else:
                debit, credit = Decimal("0"), abs_share
            yield GlLine(
                txn=txn,
                txn_date=txn.txn_date,
                entity_id=txn.entity_id,
                account_id=acct.id,
                department_id=dept_id,
                debit=debit,
                credit=credit,
                currency=txn.currency,
                memo=memo,
                description=txn.description,
            )

    if not include_openings:
        return

    bq = select(BankAccount).where(BankAccount.is_active.is_(True))
    if entity_ids:
        bq = bq.where(BankAccount.entity_id.in_(entity_ids))
    for bank in db.scalars(bq).all():
        opening = _d(bank.opening_balance)
        if opening == 0:
            continue
        cash_id = bank.gl_account_id or _default_cash_id(by_code, suspense)
        cash_acct = accounts.get(cash_id) or suspense
        debit, credit = bank_signed_to_debit_credit(cash_acct, opening)
        equity = by_code.get("3000")
        proxy = _opening_proxy(bank, cash_acct.id, date_to)
        yield GlLine(
            txn=proxy,
            txn_date=date_to,
            entity_id=bank.entity_id,
            account_id=cash_acct.id,
            department_id=None,
            debit=debit,
            credit=credit,
            currency=bank.currency,
            memo=OPENING_MEMO,
            description=proxy.description,
            is_opening=True,
        )
        if equity:
            # Opposite equity so the opening is a balanced pair.
            eq_debit, eq_credit = credit, debit
            yield GlLine(
                txn=proxy,
                txn_date=date_to,
                entity_id=bank.entity_id,
                account_id=equity.id,
                department_id=None,
                debit=eq_debit,
                credit=eq_credit,
                currency=bank.currency,
                memo=OPENING_MEMO,
                description=proxy.description,
                is_opening=True,
            )


@dataclass
class LedgerTotals:
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    bank_signed: Decimal = Decimal("0")
    ic_bank_signed: Decimal = Decimal("0")

    @property
    def net_debit(self) -> Decimal:
        return self.debit - self.credit


@dataclass
class LedgerBundle:
    by_account: dict[int, LedgerTotals]
    fx_missing: bool = False
    fx_missing_pairs: list[str] = field(default_factory=list)


def aggregate_ledger(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    scenario_id: int,
    entity_ids: Optional[list[int]],
    department_ids: Optional[list[int]],
    reporting_currency: str,
    rate_type: str,
    include_openings: bool,
    ic_predicate=None,
) -> LedgerBundle:
    accounts = {a.id: a for a in db.scalars(select(DimAccount)).all()}
    by_account: dict[int, LedgerTotals] = {}
    missing_pairs: list[str] = []
    seen: set[str] = set()

    for line in iter_gl_lines(
        db,
        date_from=date_from,
        date_to=date_to,
        scenario_id=scenario_id,
        entity_ids=entity_ids,
        department_ids=department_ids,
        include_openings=include_openings,
    ):
        acct = accounts.get(line.account_id)
        if not acct:
            continue
        native_net = line.net_debit
        translated = translate_amount(
            db,
            amount=native_net,
            from_currency=line.currency,
            to_currency=reporting_currency,
            as_of=line.txn_date,
            rate_type=rate_type,
        )
        if translated.missing:
            pair = f"{line.currency}→{reporting_currency}"
            if pair not in seen:
                seen.add(pair)
                missing_pairs.append(pair)
        # Preserve Dr/Cr side after translation.
        if native_net >= 0:
            debit, credit = translated.amount, Decimal("0")
        else:
            debit, credit = Decimal("0"), -translated.amount
        slot = by_account.setdefault(line.account_id, LedgerTotals())
        slot.debit += debit
        slot.credit += credit
        # translated.amount is net_debit in reporting currency.
        slot.bank_signed += net_debit_to_bank_signed(acct, translated.amount)
        if ic_predicate and ic_predicate(acct, line):
            slot.ic_bank_signed += net_debit_to_bank_signed(acct, translated.amount)

    return LedgerBundle(
        by_account=by_account,
        fx_missing=bool(missing_pairs),
        fx_missing_pairs=missing_pairs,
    )


def roundtrip_ok(account: DimAccount, debit: Decimal, credit: Decimal) -> bool:
    """Sanity: journal conversion is reversible."""
    bank = bank_amount_from_debit_credit(account, debit, credit)
    d2, c2 = bank_signed_to_debit_credit(account, bank)
    return d2 == debit and c2 == credit
