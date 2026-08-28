"""Seed WBC CAN + USA ledger from mapping files, CAN 1010 synoptic, and USA FY adj pack."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.adj_pack import USA_ADJ_PATH, import_adj_pack_path
from app.engines.synoptic import import_synoptic_path
from app.models import BankAccount, DimEntity
from app.services.wbc_bootstrap import SAMPLE_ROOT, bootstrap_wbc_dimensions


def seed_if_empty(db: Session) -> bool:
    if db.scalar(select(DimEntity).limit(1)):
        return False
    seed_all(db)
    return True


def seed_all(db: Session, *, load_synoptic: bool = True) -> dict:
    """
    Bootstrap WBC CAN + WBC USA as separate companies with the shared chart.
    Loads CAN 1010 cashbook activity and USA FY2026 adjusting journals when present.
    """
    meta = bootstrap_wbc_dimensions(db)
    db.flush()

    synoptic_result = None
    if load_synoptic:
        synoptic_path = SAMPLE_ROOT / "synoptic" / "CAN_1010_WBC_JUL-2026.csv"
        can = db.scalar(select(DimEntity).where(DimEntity.code == "CAN"))
        bank = None
        if can:
            bank = db.scalar(
                select(BankAccount).where(
                    BankAccount.entity_id == can.id,
                    BankAccount.account_number == "1010",
                )
            )
        if bank and synoptic_path.exists():
            synoptic_result = import_synoptic_path(db, synoptic_path, bank.id, actor="seed")
            meta["synoptic"] = {
                "file": str(synoptic_path.name),
                "bank_account_id": bank.id,
                "imported": synoptic_result.imported,
                "auto_categorized": synoptic_result.auto_categorized,
                "skipped": synoptic_result.skipped,
                "duplicates": synoptic_result.duplicates_flagged,
                "errors": synoptic_result.errors[:10],
            }
        else:
            meta["synoptic"] = {"loaded": False, "reason": "CAN 1010 bank or file missing"}

        usa = db.scalar(select(DimEntity).where(DimEntity.code == "USA"))
        if usa and USA_ADJ_PATH.exists():
            adj = import_adj_pack_path(db, USA_ADJ_PATH, entity_id=usa.id, actor="seed")
            meta["usa_adj"] = {
                "file": USA_ADJ_PATH.name,
                "imported": adj.imported,
                "skipped": adj.skipped,
                "errors": adj.errors[:10],
            }
        else:
            meta["usa_adj"] = {"loaded": False, "reason": "USA entity or adj pack missing"}

    db.commit()
    return meta


def sample_synoptic_path() -> Path:
    return SAMPLE_ROOT / "synoptic" / "CAN_1010_WBC_JUL-2026.csv"
