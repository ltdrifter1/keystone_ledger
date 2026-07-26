from __future__ import annotations

import io
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.audit import write_audit
from app.engines.fingerprint import transaction_fingerprint
from app.engines.fx import translate_amount
from app.engines.period_locks import PeriodLockedError, assert_bank_period_open
from app.engines.rules import apply_rules_batch
from app.models import BankAccount, DimDate, DimEntity, DimScenario, Transaction
from app.schemas.transactions import ImportResult


COLUMN_ALIASES = {
    "date": ["date", "txn_date", "transaction date", "posting date", "trans date"],
    "description": ["description", "memo", "narrative", "details", "name"],
    "amount": ["amount", "value", "transaction amount"],
    "debit": ["debit", "withdrawal", "withdrawals"],
    "credit": ["credit", "deposit", "deposits"],
    "reference": ["reference", "ref", "check number", "cheque number", "fitid"],
    "counterparty": ["counterparty", "payee", "merchant"],
    "currency": ["currency", "ccy"],
    "external_id": ["external_id", "id", "fitid", "transaction id"],
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping: dict[str, str] = {}
    lower = {c: str(c).strip().lower() for c in df.columns}
    for canonical, aliases in COLUMN_ALIASES.items():
        for col, low in lower.items():
            if low in aliases and canonical not in mapping.values():
                mapping[col] = canonical
    return df.rename(columns=mapping)


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"Invalid date: {value}")
    return ts.date()


def _parse_amount(row: dict[str, Any]) -> Decimal:
    if "amount" in row and pd.notna(row.get("amount")):
        return Decimal(str(row["amount"]).replace(",", "").replace("$", "").strip())
    debit = row.get("debit")
    credit = row.get("credit")
    d = Decimal("0")
    c = Decimal("0")
    if debit is not None and pd.notna(debit) and str(debit).strip() != "":
        d = abs(Decimal(str(debit).replace(",", "").replace("$", "").strip()))
    if credit is not None and pd.notna(credit) and str(credit).strip() != "":
        c = abs(Decimal(str(credit).replace(",", "").replace("$", "").strip()))
    if d and c:
        raise ValueError("Row has both debit and credit")
    if d:
        return -d
    if c:
        return c
    raise ValueError("No amount/debit/credit found")


def ensure_date_dimension(db: Session, d: date) -> int:
    key = int(d.strftime("%Y%m%d"))
    existing = db.get(DimDate, key)
    if existing:
        return key
    # Also check identity map / pending inserts for this session
    for obj in db.new:
        if isinstance(obj, DimDate) and obj.id == key:
            return key
    db.add(
        DimDate(
            id=key,
            full_date=d,
            year=d.year,
            quarter=(d.month - 1) // 3 + 1,
            month=d.month,
            month_name=d.strftime("%b"),
            day=d.day,
            fiscal_year=d.year,
            fiscal_period=d.month,
            is_month_end=False,
            is_quarter_end=d.month in (3, 6, 9, 12) and d.day >= 28,
            is_year_end=d.month == 12 and d.day == 31,
        )
    )
    db.flush()
    return key


def import_bank_file(
    db: Session,
    *,
    file_bytes: bytes,
    filename: str,
    bank_account_id: int,
    actor: str = "controller",
) -> ImportResult:
    bank = db.get(BankAccount, bank_account_id)
    if not bank:
        raise ValueError("Bank account not found")

    actual_scenario = db.scalar(select(DimScenario).where(DimScenario.code == "ACTUAL"))
    if not actual_scenario:
        raise ValueError("ACTUAL scenario missing — run seed")

    name_lower = filename.lower()
    if name_lower.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes))
    elif name_lower.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(file_bytes))
    else:
        raise ValueError("Unsupported file type. Use CSV or Excel.")

    df = _normalize_columns(df)
    batch_id = uuid.uuid4().hex[:12]
    imported = 0
    duplicates = 0
    skipped = 0
    errors: list[str] = []
    new_txns: list[Transaction] = []

    existing_fps = set(db.scalars(select(Transaction.fingerprint).where(Transaction.fingerprint.is_not(None))))

    for idx, row in df.iterrows():
        try:
            row_dict = row.to_dict()
            if "date" not in row_dict or "description" not in row_dict:
                raise ValueError("Missing required date/description columns")
            txn_date = _parse_date(row_dict["date"])
            try:
                assert_bank_period_open(db, bank_account_id, txn_date)
            except PeriodLockedError as exc:
                raise ValueError(str(exc)) from exc
            description = str(row_dict.get("description") or "").strip()
            if not description:
                raise ValueError("Empty description")
            amount = _parse_amount(row_dict)
            currency = str(row_dict.get("currency") or bank.currency).strip().upper()
            external_id = row_dict.get("external_id")
            external_id = str(external_id) if pd.notna(external_id) and external_id is not None else None
            reference = row_dict.get("reference")
            reference = str(reference) if pd.notna(reference) and reference is not None else None
            counterparty = row_dict.get("counterparty")
            counterparty = str(counterparty) if pd.notna(counterparty) and counterparty is not None else None

            fp = transaction_fingerprint(
                txn_date=txn_date,
                amount=amount,
                description=description,
                currency=currency,
                bank_account_id=bank_account_id,
                external_id=external_id,
            )
            is_dup = fp in existing_fps
            if is_dup:
                duplicates += 1

            entity = db.get(DimEntity, bank.entity_id)
            target_ccy = entity.functional_currency if entity else currency
            amount_reporting, fx_rate = translate_amount(
                db,
                amount=amount,
                from_currency=currency,
                to_currency=target_ccy,
                as_of=txn_date,
            )
            date_key = ensure_date_dimension(db, txn_date)

            txn = Transaction(
                external_id=external_id,
                fingerprint=fp,
                txn_date=txn_date,
                description=description,
                reference=reference,
                counterparty=counterparty,
                amount=amount,
                currency=currency,
                amount_reporting=amount_reporting,
                fx_rate=fx_rate,
                entity_id=bank.entity_id,
                bank_account_id=bank.id,
                scenario_id=actual_scenario.id,
                date_key=date_key,
                source_type="bank_import",
                status="uncategorized",
                is_duplicate=is_dup,
                import_batch_id=batch_id,
                created_by=actor,
                updated_by=actor,
            )
            db.add(txn)
            new_txns.append(txn)
            existing_fps.add(fp)
            imported += 1
        except (ValueError, InvalidOperation, KeyError) as exc:
            skipped += 1
            errors.append(f"Row {idx}: {exc}")

    db.flush()
    auto_categorized = apply_rules_batch(db, [t for t in new_txns if not t.is_duplicate], actor=actor)

    write_audit(
        db,
        entity_table="import_batches",
        entity_id=0,
        action="import",
        actor=actor,
        meta={
            "batch_id": batch_id,
            "bank_account_id": bank_account_id,
            "imported": imported,
            "duplicates": duplicates,
            "auto_categorized": auto_categorized,
            "filename": filename,
        },
    )

    return ImportResult(
        batch_id=batch_id,
        imported=imported,
        duplicates_flagged=duplicates,
        auto_categorized=auto_categorized,
        skipped=skipped,
        errors=errors[:50],
    )
