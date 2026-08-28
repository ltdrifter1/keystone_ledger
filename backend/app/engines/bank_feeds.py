"""Live bank feeds — Open Banking-style connector with a WBC demo provider."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.audit import write_audit
from app.engines.feed_providers import get_provider
from app.engines.importing import BankImportRow, import_bank_rows
from app.engines.reconciliation import calculated_book_balance, period_end
from app.models import BankAccount, BankFeedConnection, DimEntity, Transaction

STALE_AFTER = timedelta(hours=24)


def _provider():
    return get_provider()


def _as_rows(bank: BankAccount) -> list[BankImportRow]:
    return _provider().rows(bank)


def _provider_key() -> str:
    return _provider().key


def pending_rows(db: Session, bank: BankAccount) -> list[BankImportRow]:
    existing_ext = set(
        db.scalars(
            select(Transaction.external_id).where(
                Transaction.bank_account_id == bank.id,
                Transaction.external_id.is_not(None),
            )
        )
    )
    return [row for row in _as_rows(bank) if not row.external_id or row.external_id not in existing_ext]


def _is_stale(conn: BankFeedConnection | None) -> bool:
    if not conn or conn.status != "connected":
        return True
    if conn.last_synced_at is None:
        return True
    return datetime.utcnow() - conn.last_synced_at > STALE_AFTER


def _href(bank_id: int, year: int | None = None, month: int | None = None) -> str:
    if year and month:
        return f"/work?year={year}&month={month}&bank={bank_id}"
    return f"/bank-accounts?bank={bank_id}"


def serialize_feed(
    db: Session,
    bank: BankAccount,
    conn: BankFeedConnection | None,
    *,
    include_pending: bool = False,
    year: int | None = None,
    month: int | None = None,
) -> dict:
    entity = db.get(DimEntity, bank.entity_id)
    pending = pending_rows(db, bank) if conn and conn.status == "connected" else []
    payload = {
        "id": conn.id if conn else 0,
        "bank_account_id": bank.id,
        "bank_account_name": bank.name,
        "entity_id": bank.entity_id,
        "entity_code": entity.code if entity else None,
        "account_number": bank.account_number,
        "currency": bank.currency,
        "institution": bank.institution,
        "provider": conn.provider if conn else _provider_key(),
        "status": conn.status if conn else "disconnected",
        "last_synced_at": conn.last_synced_at if conn else None,
        "last_balance": conn.last_balance if conn else None,
        "last_balance_as_of": conn.last_balance_as_of if conn else None,
        "error_message": conn.error_message if conn else None,
        "connected_at": conn.connected_at if conn else None,
        "pending_count": len(pending) if conn and conn.status == "connected" else 0,
        "is_stale": _is_stale(conn),
        "href": _href(bank.id, year, month),
        "pending": [],
    }
    if include_pending:
        payload["pending"] = [
            {
                "txn_date": r.txn_date,
                "description": r.description,
                "amount": r.amount,
                "currency": r.currency or bank.currency,
                "external_id": r.external_id,
                "reference": r.reference,
                "counterparty": r.counterparty,
            }
            for r in pending
        ]
    return payload


def feed_snapshot(db: Session, bank_id: int) -> dict:
    """Compact fields attached to close-pack / work chips."""
    bank = db.get(BankAccount, bank_id)
    if not bank:
        return {
            "feed_status": None,
            "feed_pending": 0,
            "feed_last_synced_at": None,
            "feed_balance": None,
            "feed_stale": True,
        }
    conn = db.scalar(select(BankFeedConnection).where(BankFeedConnection.bank_account_id == bank_id))
    pending = pending_rows(db, bank) if conn and conn.status == "connected" else []
    return {
        "feed_status": conn.status if conn else "disconnected",
        "feed_pending": len(pending),
        "feed_last_synced_at": conn.last_synced_at.isoformat() if conn and conn.last_synced_at else None,
        "feed_balance": float(conn.last_balance) if conn and conn.last_balance is not None else None,
        "feed_stale": _is_stale(conn),
    }


def get_or_create_connection(db: Session, bank: BankAccount) -> BankFeedConnection:
    conn = db.scalar(select(BankFeedConnection).where(BankFeedConnection.bank_account_id == bank.id))
    if conn:
        return conn
    conn = BankFeedConnection(
        bank_account_id=bank.id,
        provider=_provider_key(),
        status="disconnected",
    )
    db.add(conn)
    db.flush()
    return conn


def ensure_feed_connections(db: Session, *, auto_connect: bool = True) -> int:
    """Create feed rows for every active bank. Auto-connect WBC demo accounts."""
    banks = list(db.scalars(select(BankAccount).where(BankAccount.is_active == True)))  # noqa: E712
    created = 0
    for bank in banks:
        conn = db.scalar(select(BankFeedConnection).where(BankFeedConnection.bank_account_id == bank.id))
        if conn:
            continue
        now = datetime.utcnow() if auto_connect else None
        conn = BankFeedConnection(
            bank_account_id=bank.id,
            provider=_provider_key(),
            status="connected" if auto_connect else "disconnected",
            connected_at=now,
            connected_by="system",
        )
        db.add(conn)
        created += 1
    if created:
        db.flush()
        write_audit(
            db,
            entity_table="bank_feed_connections",
            entity_id=0,
            action="ensure",
            actor="system",
            meta={"created": created, "auto_connect": auto_connect},
        )
        db.commit()
    return created


def list_feeds(db: Session, *, entity_id: int | None = None, include_pending: bool = False) -> list[dict]:
    ensure_feed_connections(db, auto_connect=True)
    q = select(BankAccount).where(BankAccount.is_active == True)  # noqa: E712
    if entity_id:
        q = q.where(BankAccount.entity_id == entity_id)
    banks = list(db.scalars(q.order_by(BankAccount.name)))
    conns = {
        c.bank_account_id: c
        for c in db.scalars(select(BankFeedConnection)).all()
    }
    return [serialize_feed(db, b, conns.get(b.id), include_pending=include_pending) for b in banks]


def connect_feed(db: Session, bank_account_id: int, actor: str = "controller") -> dict:
    bank = db.get(BankAccount, bank_account_id)
    if not bank:
        raise ValueError("Bank account not found")
    conn = get_or_create_connection(db, bank)
    conn.status = "connected"
    conn.provider = _provider_key()
    conn.error_message = None
    conn.connected_at = datetime.utcnow()
    conn.connected_by = actor
    db.flush()
    write_audit(
        db,
        entity_table="bank_feed_connections",
        entity_id=conn.id,
        action="connect",
        actor=actor,
        meta={"bank_account_id": bank_account_id, "provider": _provider_key()},
    )
    return serialize_feed(db, bank, conn, include_pending=True)


def disconnect_feed(db: Session, bank_account_id: int, actor: str = "controller") -> dict:
    bank = db.get(BankAccount, bank_account_id)
    if not bank:
        raise ValueError("Bank account not found")
    conn = get_or_create_connection(db, bank)
    conn.status = "disconnected"
    conn.error_message = None
    db.flush()
    write_audit(
        db,
        entity_table="bank_feed_connections",
        entity_id=conn.id,
        action="disconnect",
        actor=actor,
        meta={"bank_account_id": bank_account_id},
    )
    return serialize_feed(db, bank, conn, include_pending=False)


def statement_balance_as_of(db: Session, bank_account_id: int, as_of: date) -> Decimal:
    return calculated_book_balance(db, bank_account_id, as_of)


def sync_feed(
    db: Session,
    bank_account_id: int,
    *,
    actor: str = "controller",
    period_year: int | None = None,
    period_month: int | None = None,
) -> dict:
    bank = db.get(BankAccount, bank_account_id)
    if not bank:
        raise ValueError("Bank account not found")
    conn = get_or_create_connection(db, bank)
    if conn.status != "connected":
        raise ValueError("Bank feed is not connected")

    pending = pending_rows(db, bank)
    result = import_bank_rows(
        db,
        bank_account_id=bank.id,
        rows=pending,
        actor=actor,
        source_type="bank_feed",
        skip_duplicates=True,
        filename=f"feed:{_provider_key()}",
    )

    as_of = date.today()
    latest = db.scalar(
        select(Transaction.txn_date)
        .where(Transaction.bank_account_id == bank.id, Transaction.status != "void")
        .order_by(Transaction.txn_date.desc())
        .limit(1)
    )
    if latest:
        as_of = latest
    balance = calculated_book_balance(db, bank.id, as_of)
    conn.last_synced_at = datetime.utcnow()
    conn.last_balance = balance
    conn.last_balance_as_of = as_of
    conn.error_message = None
    conn.status = "connected"
    db.flush()

    remaining = pending_rows(db, bank)
    statement_ending = None
    if period_year and period_month:
        statement_ending = statement_balance_as_of(
            db, bank.id, period_end(period_year, period_month)
        )

    write_audit(
        db,
        entity_table="bank_feed_connections",
        entity_id=conn.id,
        action="sync",
        actor=actor,
        meta={
            "bank_account_id": bank_account_id,
            "imported": result.imported,
            "duplicates": result.duplicates_flagged,
            "balance": str(balance),
        },
    )

    feed = serialize_feed(db, bank, conn, include_pending=True, year=period_year, month=period_month)
    return {
        "bank_account_id": bank.id,
        "status": conn.status,
        "imported": result.imported,
        "duplicates_flagged": result.duplicates_flagged,
        "auto_categorized": result.auto_categorized,
        "skipped": result.skipped,
        "pending_remaining": len(remaining),
        "last_balance": balance,
        "last_balance_as_of": as_of,
        "last_synced_at": conn.last_synced_at,
        "statement_ending_balance": statement_ending,
        "errors": result.errors,
        "import_result": result,
        "feed": feed,
    }
