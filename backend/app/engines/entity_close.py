"""Month-end entity GL lock — monthly recs, not a daily close."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines.audit import write_audit
from app.engines.period_locks import PeriodLockedError
from app.models import DimEntity, EntityPeriodLock, Transaction


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def get_entity_period_lock(db: Session, entity_id: int, year: int, month: int) -> EntityPeriodLock | None:
    return db.scalar(
        select(EntityPeriodLock).where(
            EntityPeriodLock.entity_id == entity_id,
            EntityPeriodLock.period_year == year,
            EntityPeriodLock.period_month == month,
            EntityPeriodLock.status == "locked",
        )
    )


def is_entity_month_locked(db: Session, entity_id: int, txn_date: date) -> EntityPeriodLock | None:
    return get_entity_period_lock(db, entity_id, txn_date.year, txn_date.month)


def serialize_lock(lock: EntityPeriodLock | None, *, entity_id: int, year: int, month: int) -> dict:
    return {
        "entity_id": entity_id,
        "period_year": year,
        "period_month": month,
        "is_locked": lock is not None,
        "locked_at": lock.locked_at.isoformat() if lock and lock.locked_at else None,
        "locked_by": lock.locked_by if lock else None,
        "notes": lock.notes if lock else None,
    }


def is_journal_led_entity(db: Session, entity_id: int) -> bool:
    """USA-style books: month-end journals, no synoptic cashbook."""
    journals = db.scalar(
        select(func.count()).select_from(Transaction).where(
            Transaction.entity_id == entity_id,
            Transaction.source_type.in_(("journal", "post_close_adj")),
            Transaction.status != "void",
        )
    ) or 0
    synoptic = db.scalar(
        select(func.count()).select_from(Transaction).where(
            Transaction.entity_id == entity_id,
            Transaction.source_type == "synoptic_import",
            Transaction.status != "void",
        )
    ) or 0
    return bool(journals) and not synoptic


def lock_entity_month(
    db: Session,
    *,
    entity_id: int,
    year: int,
    month: int,
    actor: str = "controller",
    notes: str | None = None,
) -> dict:
    entity = db.get(DimEntity, entity_id)
    if not entity:
        raise ValueError("Entity not found")
    existing = get_entity_period_lock(db, entity_id, year, month)
    if existing:
        return serialize_lock(existing, entity_id=entity_id, year=year, month=month)
    lock = EntityPeriodLock(
        entity_id=entity_id,
        period_year=year,
        period_month=month,
        status="locked",
        locked_by=actor,
        notes=notes or "Month-end GL lock",
    )
    db.add(lock)
    db.flush()
    write_audit(
        db,
        entity_table="entity_period_locks",
        entity_id=lock.id,
        action="lock",
        actor=actor,
        meta={"entity": entity.code, "period": f"{year}-{month:02d}"},
    )
    return serialize_lock(lock, entity_id=entity_id, year=year, month=month)


def assert_entity_month_open(db: Session, entity_id: int, txn_date: date, *, allow_post_close: bool = False) -> None:
    lock = is_entity_month_locked(db, entity_id, txn_date)
    if not lock:
        return
    if allow_post_close:
        return
    raise PeriodLockedError(
        f"{lock.period_year}-{lock.period_month:02d} is locked for this company. "
        "Post a post-close adjusting journal (PCA) — do not reopen the monthly rec."
    )
