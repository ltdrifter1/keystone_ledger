"""Balanced adjusting journals — GL-only, no bank period lock."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines.audit import write_audit
from app.engines.importing import ensure_date_dimension
from app.models import DimAccount, DimEntity, Transaction, TransactionSplit


def _d(value: Decimal | str | int | float | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def bank_amount_from_debit_credit(account: DimAccount, debit: Decimal, credit: Decimal) -> Decimal:
    """Map Dr/Cr into the app's bank-signed amount so reporting stays consistent."""
    net_debit = _d(debit) - _d(credit)
    if account.account_type == "expense":
        return -net_debit
    if account.account_type == "revenue":
        return -net_debit
    if account.normal_balance == "credit":
        return net_debit
    return net_debit


def _next_voucher(db: Session, year: int, month: int) -> str:
    like = f"J-{year}-{month:02d}-%"
    count = db.scalar(select(func.count()).where(Transaction.reference.like(like))) or 0
    return f"J-{year}-{month:02d}-{int(count) + 1:04d}"


def post_journal(
    db: Session,
    *,
    txn_date: date,
    entity_id: int,
    description: str,
    lines: list[dict],
    actor: str = "AC",
    memo: str | None = None,
    working_paper_key: str | None = None,
    source_transaction_id: int | None = None,
    currency: str = "CAD",
    scenario_id: int = 1,
) -> Transaction:
    entity = db.get(DimEntity, entity_id)
    if not entity:
        raise ValueError("Entity not found")
    if len(lines) < 2:
        raise ValueError("Journal needs at least two lines")

    parsed: list[tuple[DimAccount, Decimal, Decimal, Decimal, str | None]] = []
    total_dr = Decimal("0")
    total_cr = Decimal("0")
    for raw in lines:
        account_id = int(raw["account_id"])
        account = db.get(DimAccount, account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")
        debit = _d(raw.get("debit") or 0)
        credit = _d(raw.get("credit") or 0)
        if debit < 0 or credit < 0:
            raise ValueError("Debit and credit must be ≥ 0")
        if debit == 0 and credit == 0:
            raise ValueError(f"Line {account.code} has no debit or credit")
        if debit and credit:
            raise ValueError(f"Line {account.code} cannot have both debit and credit")
        bank_amt = bank_amount_from_debit_credit(account, debit, credit)
        parsed.append((account, debit, credit, bank_amt, raw.get("memo")))
        total_dr += debit
        total_cr += credit

    if total_dr != total_cr:
        raise ValueError(f"Journal is out of balance (Dr {total_dr} vs Cr {total_cr})")
    if total_dr == 0:
        raise ValueError("Journal total cannot be zero")

    year, month = txn_date.year, txn_date.month
    voucher = _next_voucher(db, year, month)
    note_parts = [p for p in (memo, f"WP {working_paper_key}" if working_paper_key else None) if p]
    parent_memo = " · ".join(note_parts) or None
    if source_transaction_id:
        parent_memo = ((parent_memo + " · ") if parent_memo else "") + f"from txn #{source_transaction_id}"

    parent = Transaction(
        txn_date=txn_date,
        description=description.strip() or f"Adjusting journal {voucher}",
        memo=parent_memo,
        reference=voucher,
        amount=Decimal("0"),
        currency=currency or entity.functional_currency,
        entity_id=entity_id,
        bank_account_id=None,
        account_id=None,
        scenario_id=scenario_id,
        source_type="journal",
        status="categorized",
        is_split=True,
        date_key=ensure_date_dimension(db, txn_date),
        import_batch_id=f"journal:{working_paper_key or 'adj'}:{year}-{month:02d}",
        created_by=actor,
        updated_by=actor,
    )
    db.add(parent)
    db.flush()

    for i, (account, debit, credit, bank_amt, line_memo) in enumerate(parsed):
        side = f"Dr {debit}" if debit else f"Cr {credit}"
        db.add(
            TransactionSplit(
                transaction_id=parent.id,
                account_id=account.id,
                amount=bank_amt,
                memo=line_memo or side,
                sort_order=i,
            )
        )

    write_audit(
        db,
        entity_table="transactions",
        entity_id=parent.id,
        action="journal",
        new_value=voucher,
        actor=actor,
        meta={
            "working_paper_key": working_paper_key,
            "source_transaction_id": source_transaction_id,
            "debit": str(total_dr),
            "credit": str(total_cr),
            "lines": len(parsed),
        },
    )
    db.flush()
    return parent


def serialize_journal(db: Session, txn: Transaction) -> dict:
    entity = db.get(DimEntity, txn.entity_id)
    lines = []
    for split in sorted(txn.splits, key=lambda s: s.sort_order):
        account = db.get(DimAccount, split.account_id)
        memo = split.memo or ""
        debit = Decimal("0")
        credit = Decimal("0")
        if memo.startswith("Dr "):
            try:
                debit = Decimal(memo[3:].split()[0])
            except Exception:
                debit = Decimal("0")
        elif memo.startswith("Cr "):
            try:
                credit = Decimal(memo[3:].split()[0])
            except Exception:
                credit = Decimal("0")
        else:
            # Reconstruct from bank-signed amount
            if account:
                if account.account_type in ("expense", "revenue"):
                    net = -Decimal(split.amount)
                elif account.normal_balance == "credit":
                    net = Decimal(split.amount)
                else:
                    net = Decimal(split.amount)
                if net >= 0:
                    debit = net
                else:
                    credit = -net
        lines.append(
            {
                "account_id": split.account_id,
                "account_code": account.code if account else None,
                "account_name": account.name if account else None,
                "debit": float(debit),
                "credit": float(credit),
                "amount": float(split.amount),
                "memo": split.memo,
            }
        )
    return {
        "id": txn.id,
        "voucher": txn.reference,
        "txn_date": txn.txn_date.isoformat(),
        "description": txn.description,
        "memo": txn.memo,
        "entity_id": txn.entity_id,
        "entity_code": entity.code if entity else None,
        "currency": txn.currency,
        "source_type": txn.source_type,
        "working_paper_key": (txn.import_batch_id or "").split(":")[1]
        if txn.import_batch_id and txn.import_batch_id.startswith("journal:")
        else None,
        "lines": lines,
        "created_by": txn.created_by,
        "created_at": txn.created_at.isoformat() if txn.created_at else None,
    }


def list_journals(
    db: Session,
    *,
    year: int | None = None,
    month: int | None = None,
    entity_id: int | None = None,
    working_paper_key: str | None = None,
) -> list[dict]:
    q = select(Transaction).where(Transaction.source_type == "journal", Transaction.status != "void")
    if entity_id:
        q = q.where(Transaction.entity_id == entity_id)
    if year:
        start = date(year, month or 1, 1)
        if month:
            from calendar import monthrange

            end = date(year, month, monthrange(year, month)[1])
        else:
            end = date(year, 12, 31)
        q = q.where(Transaction.txn_date >= start, Transaction.txn_date <= end)
    if working_paper_key:
        q = q.where(Transaction.import_batch_id.like(f"journal:{working_paper_key}:%"))
    rows = list(db.scalars(q.order_by(Transaction.txn_date.desc(), Transaction.id.desc())))
    return [serialize_journal(db, t) for t in rows]
