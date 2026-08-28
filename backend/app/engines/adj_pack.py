"""Import WBC adjusting-entry packs (FY close journals, not cashbooks).

Expected layout (from Synoptic FY packs, e.g. USA_ADJ):

    WBC USA
    Adjusting Entries
    July 31, 2026

    Entry No.,Description,FS Line,GL Code,,Dr,Cr
    STD-001,Interco AR,,,,"38,167.90",
    ,Interco sales,,,,,"38,167.90"
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.journals import post_journal
from app.models import BankAccount, DimAccount, DimEntity, DimScenario, Transaction
from app.schemas.transactions import ImportResult

SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "sample_data"
USA_ADJ_PATH = SAMPLE_ROOT / "synoptic" / "USA_ADJ_FY2026.csv"

ENTITY_ALIASES = {
    "usa": "USA",
    "wbc usa": "USA",
    "wbc united states": "USA",
    "united states": "USA",
    "can": "CAN",
    "wbc can": "CAN",
    "wbc canada": "CAN",
    "canada": "CAN",
}

# Description / FS-line → GL when the pack leaves GL Code blank.
DESC_GL = (
    ("interco ar", "1100"),
    ("interco a/r", "1100"),
    ("interco sales", "4000"),
    ("interco ap - service", "2000"),
    ("interco ap-service", "2000"),
    ("interco ap-inventory", "2000"),
    ("interco ap - inventory", "2000"),
    ("interco ap", "2000"),
    ("interco a/p", "2000"),
)

FS_LINE_GL = {
    "cogs": "5000",
    "opex": "6600",
    "exp": "6600",
    "operating": "6600",
    "revenue": "4000",
    "sales": "4000",
    "ar": "1100",
    "ap": "2000",
    "inventory": "1200",
}


@dataclass
class AdjLine:
    description: str
    fs_line: str
    gl_code: str
    debit: Decimal
    credit: Decimal


@dataclass
class AdjEntry:
    entry_no: str
    lines: list[AdjLine] = field(default_factory=list)


@dataclass
class AdjPack:
    entity_code: str | None
    txn_date: date | None
    entries: list[AdjEntry]


def _parse_number(value: str) -> Decimal | None:
    s = (value or "").strip().replace(",", "").replace("$", "").replace('"', "")
    if not s or s == "-":
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: str) -> date | None:
    value = (value or "").strip().strip('"')
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(value[:32], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def _entity_from_text(text: str) -> str | None:
    key = re.sub(r"\s+", " ", (text or "").strip().lower())
    if key in ENTITY_ALIASES:
        return ENTITY_ALIASES[key]
    if "usa" in key or "united states" in key:
        return "USA"
    if "can" in key or "canada" in key:
        return "CAN"
    return None


def parse_adj_pack(file_bytes: bytes) -> AdjPack:
    text = file_bytes.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("Adjusting pack is empty")

    blob = " ".join(" ".join(c.strip() for c in row) for row in rows[:8]).lower()
    if "posted date" in blob and "adjusting" not in blob:
        raise ValueError("This looks like a cashbook synoptic — use Import synoptic instead")

    entity_code: str | None = None
    txn_date: date | None = None
    header_idx: int | None = None
    cols: dict[str, int] = {}

    for i, row in enumerate(rows):
        cells = [str(c).strip() for c in row]
        if not any(cells):
            continue
        if entity_code is None:
            entity_code = _entity_from_text(cells[0]) or _entity_from_text(" ".join(cells))
        for cell in cells:
            parsed = _parse_date(cell)
            if parsed:
                txn_date = parsed
        lowered = [re.sub(r"[.\s]+", " ", c.lower()).strip() for c in cells]
        has_entry = any(c in ("entry no", "entry #", "entry number", "entry") for c in lowered)
        has_dr = any(c in ("dr", "debit") for c in lowered)
        has_cr = any(c in ("cr", "credit") for c in lowered)
        if has_entry and has_dr and has_cr:
            header_idx = i
            for j, name in enumerate(lowered):
                if name in ("entry no", "entry #", "entry number") or name == "entry":
                    cols["entry_no"] = j
                elif name in ("description", "desc", "memo"):
                    cols["description"] = j
                elif name in ("fs line", "fs", "line"):
                    cols["fs_line"] = j
                elif name in ("gl code", "gl", "account", "code"):
                    cols["gl_code"] = j
                elif name in ("dr", "debit"):
                    cols["debit"] = j
                elif name in ("cr", "credit"):
                    cols["credit"] = j
            break

    if header_idx is None or "debit" not in cols or "credit" not in cols:
        raise ValueError("Adjusting pack needs an Entry No / Description / Dr / Cr header")

    def cell(row: list[str], key: str) -> str:
        idx = cols.get(key)
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx]).strip()

    entries: list[AdjEntry] = []
    current: AdjEntry | None = None
    for row in rows[header_idx + 1 :]:
        if not any(str(c).strip() for c in row):
            continue
        entry_no = cell(row, "entry_no")
        desc = cell(row, "description")
        debit = _parse_number(cell(row, "debit")) or Decimal("0")
        credit = _parse_number(cell(row, "credit")) or Decimal("0")
        if debit == 0 and credit == 0 and not desc:
            continue
        if entry_no:
            current = AdjEntry(entry_no=entry_no)
            entries.append(current)
        if current is None:
            continue
        if debit == 0 and credit == 0:
            continue
        current.lines.append(
            AdjLine(
                description=desc or current.entry_no,
                fs_line=cell(row, "fs_line"),
                gl_code=cell(row, "gl_code"),
                debit=debit,
                credit=credit,
            )
        )

    entries = [e for e in entries if len(e.lines) >= 2]
    if not entries:
        raise ValueError("Adjusting pack has no balanced entries")
    return AdjPack(entity_code=entity_code, txn_date=txn_date, entries=entries)


def _normalize_desc(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def resolve_gl_code(line: AdjLine, entry: AdjEntry) -> str:
    raw = (line.gl_code or "").strip()
    if raw.isdigit():
        return raw
    desc = _normalize_desc(line.description)
    blob = " ".join(_normalize_desc(l.description) for l in entry.lines)
    fs = _normalize_desc(line.fs_line) or _normalize_desc(raw)

    if "move dl" in desc or "direct labour" in blob or "direct labor" in blob:
        if fs in ("cogs",):
            return "5200"
        if fs in ("opex", "exp", "operating"):
            return "6600"

    for needle, code in DESC_GL:
        if needle in desc:
            return code

    if "interco exp" in desc:
        if "inventory" in blob:
            return "5000"
        return "6600"

    if fs in FS_LINE_GL:
        return FS_LINE_GL[fs]
    raise ValueError(f"{entry.entry_no}: cannot map '{line.description}' / FS '{line.fs_line or raw}' to a GL account")


def _working_paper_key(entry: AdjEntry) -> str | None:
    blob = " ".join(l.description for l in entry.lines).lower()
    fs = " ".join(l.fs_line for l in entry.lines).lower()
    if "interco" in blob:
        return "interco"
    if "cogs" in fs or "opex" in fs or "direct labour" in blob or "move dl" in blob:
        return "pnl_analysis"
    return None


def import_adj_pack(
    db: Session,
    *,
    file_bytes: bytes,
    filename: str,
    entity_id: int | None = None,
    actor: str = "seed",
) -> ImportResult:
    pack = parse_adj_pack(file_bytes)
    entity: DimEntity | None = None
    if entity_id:
        entity = db.get(DimEntity, entity_id)
    if entity is None and pack.entity_code:
        entity = db.scalar(select(DimEntity).where(DimEntity.code == pack.entity_code))
    if entity is None:
        raise ValueError("Could not tell which company this pack belongs to — pick WBC CAN or WBC USA")

    txn_date = pack.txn_date or date(2026, 7, 31)
    accounts = {a.code: a for a in db.scalars(select(DimAccount).where(DimAccount.is_active == True)).all()}
    actual = db.scalar(select(DimScenario).where(DimScenario.code == "ACTUAL"))
    if not actual:
        raise ValueError("ACTUAL scenario missing — run seed")
    counterpart = db.scalar(
        select(DimEntity).where(DimEntity.code != entity.code, DimEntity.is_active == True)
    )

    batch_id = str(uuid.uuid4())
    imported = 0
    skipped = 0
    errors: list[str] = []

    for entry in pack.entries:
        existing = db.scalar(
            select(Transaction).where(
                Transaction.entity_id == entity.id,
                Transaction.source_type == "journal",
                Transaction.reference == entry.entry_no,
                Transaction.status != "void",
            )
        )
        if existing:
            skipped += 1
            continue
        try:
            lines = []
            for line in entry.lines:
                code = resolve_gl_code(line, entry)
                account = accounts.get(code)
                if not account:
                    raise ValueError(f"{entry.entry_no}: unknown GL {code}")
                lines.append(
                    {
                        "account_id": account.id,
                        "debit": line.debit,
                        "credit": line.credit,
                        "memo": line.description,
                    }
                )
            is_ic = any("interco" in _normalize_desc(l.description) for l in entry.lines)
            post_journal(
                db,
                txn_date=txn_date,
                entity_id=entity.id,
                description=f"{entry.entry_no} · {entry.lines[0].description}",
                lines=lines,
                actor=actor,
                memo=f"FY adj pack {filename}",
                working_paper_key=_working_paper_key(entry),
                currency=entity.functional_currency,
                scenario_id=actual.id,
                reference=entry.entry_no,
                counter_entity_id=counterpart.id if is_ic and counterpart else None,
                counterparty=counterpart.name if is_ic and counterpart else None,
                external_id=f"adj:{entity.code}:{entry.entry_no}",
            )
            imported += 1
        except ValueError as exc:
            errors.append(str(exc))
            skipped += 1

    return ImportResult(
        batch_id=batch_id,
        imported=imported,
        duplicates_flagged=skipped if imported == 0 else 0,
        auto_categorized=imported,
        skipped=skipped,
        errors=errors[:50],
    )


def import_adj_pack_path(db: Session, path: Path, *, entity_id: int | None = None, actor: str = "seed") -> ImportResult:
    return import_adj_pack(db, file_bytes=path.read_bytes(), filename=path.name, entity_id=entity_id, actor=actor)


def ensure_wbc_company_pack(db: Session) -> dict:
    """Keep entity labels and FY2026 USA books current on already-seeded databases."""
    renamed = 0
    for code, name in (("CAN", "WBC CAN"), ("USA", "WBC USA")):
        ent = db.scalar(select(DimEntity).where(DimEntity.code == code))
        if ent and ent.name != name:
            ent.name = name
            renamed += 1

    usa = db.scalar(select(DimEntity).where(DimEntity.code == "USA"))
    bank_renamed = 0
    if usa:
        for bank in db.scalars(select(BankAccount).where(BankAccount.entity_id == usa.id)).all():
            if "pending" in (bank.name or "").lower() or bank.name.startswith("USA Operating"):
                bank.name = "WBC USA 1010 Operating USD"
                bank_renamed += 1

    adj = {"loaded": False}
    if usa and USA_ADJ_PATH.exists():
        result = import_adj_pack_path(db, USA_ADJ_PATH, entity_id=usa.id, actor="seed")
        adj = {
            "loaded": True,
            "imported": result.imported,
            "skipped": result.skipped,
            "errors": result.errors[:5],
        }
    if renamed or bank_renamed or adj.get("imported"):
        db.commit()
    return {"renamed_entities": renamed, "renamed_banks": bank_renamed, "usa_adj": adj}
