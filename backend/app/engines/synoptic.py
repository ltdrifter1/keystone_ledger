"""Parse and import WBC-style bank synoptic cashbooks.

Synoptic layout (rows 0-3 headers, row 4+ data):
  0: statement section (Revenue, COGS, …)
  1: account category name
  2: GL account code
  3: channel / sub-ledger label (NOBL, Interco, Cash Sweep In, …)
  data: Posted Date | Description | Ref | Amount | Balance | …GL cols… | Total | Transfer ID | Transfer To/From | FX Register | usd$
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.audit import write_audit
from app.engines.fingerprint import transaction_fingerprint
from app.engines.fx import translate_amount
from app.engines.importing import ensure_date_dimension
from app.engines.period_locks import PeriodLockedError, assert_bank_period_open
from app.models import (
    BankAccount,
    DimAccount,
    DimDepartment,
    DimEntity,
    DimScenario,
    Transaction,
    TransactionSplit,
)
from app.schemas.transactions import ImportResult

SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "sample_data"
MAPPINGS_ROOT = SAMPLE_ROOT / "mappings"

SUMMARY_DESCRIPTIONS = {
    "TOTAL",
    "OPENING BALANCE",
    "OPENING",
    "CHECK",
}


@dataclass(frozen=True)
class SynopticColumn:
    index: int
    code: str
    section: str
    category: str
    channel: str


@dataclass
class SynopticAllocation:
    code: str
    channel: str
    amount: Decimal  # sheet sign (offsets bank amount)


def _parse_number(value: Any) -> Decimal | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("$", "").replace('"', "")
    if not s or s == "-":
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value[:32], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def load_channel_department_map() -> dict[str, str]:
    path = MAPPINGS_ROOT / "wbc_entities_banks.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return dict(data.get("channels_to_department") or {})


def parse_synoptic_headers(rows: list[list[str]]) -> list[SynopticColumn]:
    if len(rows) < 4:
        raise ValueError("Synoptic file missing 4 header rows")
    sections, cats, codes, labels = rows[0], rows[1], rows[2], rows[3]
    cols: list[SynopticColumn] = []
    width = max(len(sections), len(cats), len(codes), len(labels))
    for j in range(width):
        code = (codes[j] if j < len(codes) else "").strip()
        if not code.isdigit():
            continue
        cols.append(
            SynopticColumn(
                index=j,
                code=code,
                section=(sections[j] if j < len(sections) else "").strip(),
                category=(cats[j] if j < len(cats) else "").strip(),
                channel=(labels[j] if j < len(labels) else "").strip(),
            )
        )
    if not cols:
        raise ValueError("No GL mapping columns found in synoptic header")
    return cols


def _header_index(labels: list[str], *names: str) -> int | None:
    lowered = {str(c).strip().lower(): i for i, c in enumerate(labels)}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def parse_transfer_target(raw: str) -> dict[str, str | None]:
    """Parse values like 'CAN 1015 USD$' or 'CAN 2130 CAD'."""
    text = (raw or "").strip()
    if not text:
        return {"entity_code": None, "gl_code": None, "currency": None, "raw": None}
    m = re.match(
        r"^(?P<entity>[A-Za-z]{2,4})\s+(?P<gl>\d{3,6})\s*(?P<ccy>[A-Za-z]{3})?\$?$",
        text,
    )
    if not m:
        return {"entity_code": None, "gl_code": None, "currency": None, "raw": text}
    return {
        "entity_code": m.group("entity").upper(),
        "gl_code": m.group("gl"),
        "currency": (m.group("ccy") or "").upper() or None,
        "raw": text,
    }


def extract_allocations(row: list[str], columns: list[SynopticColumn]) -> list[SynopticAllocation]:
    out: list[SynopticAllocation] = []
    for col in columns:
        if col.index >= len(row):
            continue
        amount = _parse_number(row[col.index])
        if amount is None or amount == 0:
            continue
        out.append(SynopticAllocation(code=col.code, channel=col.channel, amount=amount))
    return out


def read_synoptic_csv(file_bytes: bytes) -> tuple[list[list[str]], list[SynopticColumn], dict[str, int | None]]:
    text = file_bytes.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 5:
        raise ValueError("Synoptic file has no data rows")
    columns = parse_synoptic_headers(rows)
    labels = rows[3]
    meta = {
        "date": _header_index(labels, "Posted Date", "Date"),
        "description": _header_index(labels, "Description"),
        "ref": _header_index(labels, "Ref", "Reference"),
        "amount": _header_index(labels, "Amount"),
        "balance": _header_index(labels, "Balance"),
        "total": _header_index(labels, "Total"),
        "transfer_id": _header_index(labels, "Transfer ID"),
        "transfer_to": _header_index(labels, "Transfer  To/From ", "Transfer To/From", "Transfer To/From "),
        "fx_register": _header_index(labels, "FX Register"),
        "usd": _header_index(labels, "usd$", "USD$", "usd"),
        "trf_seq": _header_index(labels, "TRF Seq"),
    }
    if meta["date"] is None or meta["amount"] is None or meta["description"] is None:
        raise ValueError("Synoptic missing Posted Date / Description / Amount columns")
    return rows, columns, meta


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return str(row[idx]).strip()


def _is_summary_row(desc: str, txn_date: date | None, allocations: list[SynopticAllocation]) -> bool:
    d = desc.strip().upper()
    if not d or d in SUMMARY_DESCRIPTIONS:
        return True
    if d.endswith(" ACTIVITY") and len(allocations) > 3:
        return True
    if txn_date is None:
        return True
    return False


def import_synoptic_file(
    db: Session,
    *,
    file_bytes: bytes,
    filename: str,
    bank_account_id: int,
    actor: str = "controller",
    replace_batch: bool = False,
) -> ImportResult:
    """Import a WBC synoptic into one bank account (entity-scoped)."""
    bank = db.get(BankAccount, bank_account_id)
    if not bank:
        raise ValueError("Bank account not found")
    entity = db.get(DimEntity, bank.entity_id)
    if not entity:
        raise ValueError("Bank entity missing")

    actual = db.scalar(select(DimScenario).where(DimScenario.code == "ACTUAL"))
    if not actual:
        raise ValueError("ACTUAL scenario missing — run seed")

    rows, columns, meta = read_synoptic_csv(file_bytes)
    accounts = {a.code: a for a in db.scalars(select(DimAccount).where(DimAccount.is_active == True)).all()}
    departments = {
        d.code: d
        for d in db.scalars(select(DimDepartment).where(DimDepartment.entity_id == entity.id)).all()
    }
    channel_map = load_channel_department_map()
    entities_by_code = {e.code.upper(): e for e in db.scalars(select(DimEntity)).all()}
    counter_default = next((e for c, e in entities_by_code.items() if c != entity.code.upper()), None)

    batch_id = str(uuid.uuid4())
    imported = 0
    duplicates = 0
    auto_categorized = 0
    skipped = 0
    errors: list[str] = []

    # Opening balance from OPENING BALANCE row
    for row in rows[4:]:
        desc = _cell(row, meta["description"]).upper()
        if desc.startswith("OPENING"):
            opening = _parse_number(_cell(row, meta["balance"]))
            if opening is not None:
                bank.opening_balance = opening
            skipped += 1
            break

    for row_num, row in enumerate(rows[4:], start=5):
        if not any(str(c).strip() for c in row):
            continue
        desc = _cell(row, meta["description"])
        txn_date = _parse_date(_cell(row, meta["date"]))
        amount = _parse_number(_cell(row, meta["amount"]))
        allocations = extract_allocations(row, columns)

        if _is_summary_row(desc, txn_date, allocations):
            skipped += 1
            continue
        if amount is None:
            skipped += 1
            continue

        try:
            assert_bank_period_open(db, bank.id, txn_date)
        except PeriodLockedError as exc:
            errors.append(f"row {row_num}: {exc}")
            skipped += 1
            continue

        ref = _cell(row, meta["ref"]) or None
        transfer_id = _cell(row, meta["transfer_id"]) or None
        transfer_to_raw = _cell(row, meta["transfer_to"]) or None
        transfer_to = parse_transfer_target(transfer_to_raw or "")
        fx_flag = _cell(row, meta["fx_register"]) or None
        usd_amt = _parse_number(_cell(row, meta["usd"]))
        balance = _parse_number(_cell(row, meta["balance"]))

        memo_parts = []
        if transfer_id:
            memo_parts.append(f"TRF {transfer_id}")
        if transfer_to_raw:
            memo_parts.append(f"↔ {transfer_to_raw}")
        if fx_flag:
            memo_parts.append(f"FX={fx_flag}")
        if usd_amt is not None:
            memo_parts.append(f"USD {usd_amt}")
        if len(allocations) == 1 and allocations[0].channel:
            memo_parts.append(f"[{allocations[0].channel}]")
        memo = " · ".join(memo_parts) or None

        # Synoptic rows often repeat date/amount/description (e.g. card fees).
        # Running balance is unique per cashbook line — use it (not filename) so re-imports dedupe.
        balance_key = f"{balance:.2f}" if balance is not None else f"r{row_num}"
        external_id = f"syn:{bank.id}:{txn_date.isoformat()}:{amount:.2f}:{balance_key}"
        if transfer_id:
            external_id = f"{external_id}:{transfer_id}"

        fp = transaction_fingerprint(
            txn_date=txn_date,
            amount=amount,
            description=desc,
            currency=bank.currency,
            bank_account_id=bank.id,
            external_id=external_id,
        )
        existing = db.scalar(
            select(Transaction).where(
                Transaction.bank_account_id == bank.id,
                Transaction.fingerprint == fp,
            )
        )
        if existing:
            existing.is_duplicate = True
            duplicates += 1
            skipped += 1
            continue

        reporting_amount, fx_rate = translate_amount(
            db,
            amount=amount,
            from_currency=bank.currency,
            to_currency=entity.functional_currency,
            as_of=txn_date,
            rate_type="spot",
        )

        # Counter entity for interco channels / cross-entity transfer targets
        counter_entity_id = None
        if transfer_to.get("entity_code") and transfer_to["entity_code"] != entity.code.upper():
            other = entities_by_code.get(str(transfer_to["entity_code"]))
            if other:
                counter_entity_id = other.id
        elif any(a.channel in ("Interco", "Due From", "Due To") for a in allocations) and counter_default:
            # CAN↔USE kept as separate entities; tag IC against the other entity
            counter_entity_id = counter_default.id

        primary_account = None
        primary_dept = None
        if len(allocations) == 1:
            alloc = allocations[0]
            # Prefer destination GL for cash sweeps when Transfer To/From names a GL
            dest_code = transfer_to.get("gl_code") if alloc.code == "1000" else None
            use_code = str(dest_code or alloc.code)
            primary_account = accounts.get(use_code) or accounts.get(alloc.code)
            dept_code = channel_map.get(alloc.channel)
            if dept_code:
                primary_dept = departments.get(dept_code)

        date_key = ensure_date_dimension(db, txn_date)

        txn = Transaction(
            external_id=external_id[:128],
            fingerprint=fp,
            txn_date=txn_date,
            post_date=txn_date,
            description=desc[:512],
            memo=(memo[:512] if memo else None),
            reference=(ref[:128] if ref else None),
            counterparty=(transfer_to_raw[:256] if transfer_to_raw else None),
            amount=amount,
            currency=bank.currency,
            amount_reporting=reporting_amount,
            fx_rate=fx_rate,
            entity_id=entity.id,
            bank_account_id=bank.id,
            account_id=primary_account.id if primary_account else None,
            department_id=primary_dept.id if primary_dept else None,
            scenario_id=actual.id,
            date_key=date_key,
            counter_entity_id=counter_entity_id,
            source_type="synoptic_import",
            status="categorized" if primary_account and len(allocations) <= 1 else "uncategorized",
            is_split=len(allocations) > 1,
            import_batch_id=batch_id,
            created_by=actor,
            updated_by=actor,
        )
        db.add(txn)
        db.flush()

        if len(allocations) > 1:
            # Split amounts use bank-sign convention: opposite of sheet GL sign
            for i, alloc in enumerate(allocations):
                acct = accounts.get(alloc.code)
                if not acct:
                    errors.append(f"row {row_num}: unknown account {alloc.code}")
                    continue
                dept_code = channel_map.get(alloc.channel)
                dept = departments.get(dept_code) if dept_code else None
                db.add(
                    TransactionSplit(
                        transaction_id=txn.id,
                        account_id=acct.id,
                        department_id=dept.id if dept else None,
                        amount=-alloc.amount,  # invert sheet offset → bank economic share
                        memo=alloc.channel[:256] if alloc.channel else None,
                        sort_order=i,
                    )
                )
            txn.status = "categorized"
            txn.is_split = True
            auto_categorized += 1
        elif primary_account:
            auto_categorized += 1

        imported += 1

    write_audit(
        db,
        entity_table="import_batch",
        entity_id=0,
        action="synoptic_import",
        actor=actor,
        meta={
            "batch_id": batch_id,
            "filename": filename,
            "bank_account_id": bank.id,
            "entity": entity.code,
            "imported": imported,
            "duplicates": duplicates,
            "auto_categorized": auto_categorized,
            "skipped": skipped,
            "replace_batch": replace_batch,
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


def import_synoptic_path(db: Session, path: Path, bank_account_id: int, actor: str = "seed") -> ImportResult:
    return import_synoptic_file(
        db,
        file_bytes=path.read_bytes(),
        filename=path.name,
        bank_account_id=bank_account_id,
        actor=actor,
    )
