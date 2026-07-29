"""Seed WBC CAN + USA ledger from mapping files and optional CAN 1010 synoptic."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

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
    Bootstrap CAN + USA as separate entities with shared WBC chart of accounts.
    When sample synoptic is present, load CAN 1010 activity (USA remains empty until its file is imported).
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

    db.commit()
    return meta


def sample_synoptic_path() -> Path:
    return SAMPLE_ROOT / "synoptic" / "CAN_1010_WBC_JUL-2026.csv"
