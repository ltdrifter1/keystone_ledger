from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

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


@dataclass
class BankImportRow:
    txn_date: date
    description: str
    amount: Decimal
    currency: str | None = None
    external_id: str | None = None
    reference: str | None = None
    counterparty: str | None = None
    label: str | None = None


def import_bank_rows(
    db: Session,
    *,
    bank_account_id: int,
    rows: Iterable[BankImportRow],
    actor: str = "controller",
    source_type: str = "bank_import",
    skip_duplicates: bool = False,
    batch_id: str | None = None,
    filename: str | None = None,
) -> ImportResult:
    """Ingest already-parsed bank rows (file import or live feed)."""
    bank = db.get(BankAccount, bank_account_id)
    if not bank:
        raise ValueError("Bank account not found")

    actual_scenario = db.scalar(select(DimScenario).where(DimScenario.code == "ACTUAL"))
    if not actual_scenario:
        raise ValueError("ACTUAL scenario missing — run seed")

    batch_id = batch_id or uuid.uuid4().hex[:12]
    imported = 0
    duplicates = 0
    skipped = 0
    errors: list[str] = []
    new_txns: list[Transaction] = []

    existing_fps = set(
        db.scalars(select(Transaction.fingerprint).where(Transaction.fingerprint.is_not(None)))
    )
    existing_ext = set(
        db.scalars(
            select(Transaction.external_id).where(
                Transaction.bank_account_id == bank_account_id,
                Transaction.external_id.is_not(None),
            )
        )
    )

    for idx, row in enumerate(rows, start=1):
        label = row.label or f"Row {idx}"
        try:
            try:
                assert_bank_period_open(db, bank_account_id, row.txn_date)
            except PeriodLockedError as exc:
                raise ValueError(str(exc)) from exc
            description = (row.description or "").strip()
            if not description:
                raise ValueError("Empty description")
            amount = Decimal(row.amount)
            currency = (row.currency or bank.currency).strip().upper()
            external_id = row.external_id.strip() if row.external_id else None
            if external_id and external_id in existing_ext:
                duplicates += 1
                if skip_duplicates:
                    continue

            fp = transaction_fingerprint(
                txn_date=row.txn_date,
                amount=amount,
                description=description,
                currency=currency,
                bank_account_id=bank_account_id,
                external_id=external_id,
            )
            is_dup = fp in existing_fps
            if is_dup:
                duplicates += 1
                if skip_duplicates:
                    continue

            entity = db.get(DimEntity, bank.entity_id)
            target_ccy = entity.functional_currency if entity else currency
            amount_reporting, fx_rate = translate_amount(
                db,
                amount=amount,
                from_currency=currency,
                to_currency=target_ccy,
                as_of=row.txn_date,
            )
            date_key = ensure_date_dimension(db, row.txn_date)

            txn = Transaction(
                external_id=external_id,
                fingerprint=fp,
                txn_date=row.txn_date,
                description=description,
                reference=row.reference,
                counterparty=row.counterparty,
                amount=amount,
                currency=currency,
                amount_reporting=amount_reporting,
                fx_rate=fx_rate,
                entity_id=bank.entity_id,
                bank_account_id=bank.id,
                scenario_id=actual_scenario.id,
                date_key=date_key,
                source_type=source_type,
                status="uncategorized",
                is_duplicate=is_dup,
                import_batch_id=batch_id,
                created_by=actor,
                updated_by=actor,
            )
            db.add(txn)
            new_txns.append(txn)
            existing_fps.add(fp)
            if external_id:
                existing_ext.add(external_id)
            imported += 1
        except (ValueError, InvalidOperation, KeyError) as exc:
            skipped += 1
            errors.append(f"{label}: {exc}")

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
            "source_type": source_type,
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

    name_lower = filename.lower()
    if name_lower.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes))
    elif name_lower.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(file_bytes))
    else:
        raise ValueError("Unsupported file type. Use CSV or Excel.")

    df = _normalize_columns(df)
    parsed: list[BankImportRow] = []
    parse_errors: list[str] = []
    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        try:
            if "date" not in row_dict or "description" not in row_dict:
                raise ValueError("Missing required date/description columns")
            description = str(row_dict.get("description") or "").strip()
            if not description:
                raise ValueError("Empty description")
            external_id = row_dict.get("external_id")
            external_id = str(external_id) if pd.notna(external_id) and external_id is not None else None
            reference = row_dict.get("reference")
            reference = str(reference) if pd.notna(reference) and reference is not None else None
            counterparty = row_dict.get("counterparty")
            counterparty = str(counterparty) if pd.notna(counterparty) and counterparty is not None else None
            currency = row_dict.get("currency")
            currency = str(currency).strip().upper() if pd.notna(currency) and currency is not None else None
            parsed.append(
                BankImportRow(
                    txn_date=_parse_date(row_dict["date"]),
                    description=description,
                    amount=_parse_amount(row_dict),
                    currency=currency,
                    external_id=external_id,
                    reference=reference,
                    counterparty=counterparty,
                    label=f"Row {idx}",
                )
            )
        except (ValueError, InvalidOperation, KeyError) as exc:
            parse_errors.append(f"Row {idx}: {exc}")

    result = import_bank_rows(
        db,
        bank_account_id=bank_account_id,
        rows=parsed,
        actor=actor,
        source_type="bank_import",
        filename=filename,
    )
    if parse_errors:
        result.skipped += len(parse_errors)
        result.errors = (parse_errors + result.errors)[:50]
    return result
