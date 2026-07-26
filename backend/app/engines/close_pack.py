"""Statement Close Pack — exception-driven month-end close."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.engines.audit import write_audit
from app.engines.categorization import categorize_transaction
from app.engines.importing import import_bank_file
from app.engines.intercompany import auto_match_intercompany, unmatched_intercompany_count
from app.engines.reconciliation import (
    beginning_balance,
    complete_reconciliation,
    create_reconciliation,
    period_end,
    period_start,
    refresh_reconciliation_totals,
    set_cleared,
    sync_reconciliation_items,
)
from app.engines.rules import apply_rules_batch
from app.models import BankAccount, DimEntity, Reconciliation, ReconciliationItem, Transaction
from app.schemas.transactions import CategorizeRequest, ImportResult


def get_or_open_reconciliation(
    db: Session,
    *,
    bank_account_id: int,
    period_year: int,
    period_month: int,
    statement_ending_balance: Decimal,
    notes: str | None = None,
    actor: str = "controller",
) -> tuple[Reconciliation, bool]:
    """Return (recon, created). Updates statement balance if an open recon exists."""
    existing = db.scalar(
        select(Reconciliation).where(
            Reconciliation.bank_account_id == bank_account_id,
            Reconciliation.period_year == period_year,
            Reconciliation.period_month == period_month,
        )
    )
    if existing:
        if existing.status == "locked":
            raise ValueError(
                f"Period {period_year}-{period_month:02d} is already locked for this bank account."
            )
        existing.statement_ending_balance = statement_ending_balance
        if notes:
            existing.notes = notes
        existing.status = "in_progress"
        sync_reconciliation_items(db, existing)
        refresh_reconciliation_totals(db, existing)
        write_audit(
            db,
            entity_table="reconciliations",
            entity_id=existing.id,
            action="update",
            field_name="statement_ending_balance",
            new_value=str(statement_ending_balance),
            actor=actor,
            meta={"source": "close_pack"},
        )
        return existing, False

    recon = create_reconciliation(
        db,
        bank_account_id=bank_account_id,
        period_year=period_year,
        period_month=period_month,
        statement_ending_balance=statement_ending_balance,
        notes=notes or "Opened via Statement Close Pack",
        actor=actor,
    )
    return recon, True


def auto_clear_statement_items(
    db: Session,
    recon: Reconciliation,
    *,
    actor: str = "controller",
) -> int:
    """
    Auto-clear categorized/split items dated within the statement period.
    Prior-period uncleared timing items stay uncleared (exceptions if they drive difference).
    """
    if recon.status == "locked":
        raise ValueError("Reconciliation is locked")

    sync_reconciliation_items(db, recon)
    start = period_start(recon.period_year, recon.period_month)
    end = period_end(recon.period_year, recon.period_month)

    items = (
        db.scalars(
            select(ReconciliationItem)
            .options(joinedload(ReconciliationItem.transaction))
            .where(ReconciliationItem.reconciliation_id == recon.id)
        )
        .unique()
        .all()
    )

    to_clear: list[int] = []
    for item in items:
        txn = item.transaction
        if not txn or txn.status == "void" or item.is_cleared:
            continue
        if not (start <= txn.txn_date <= end):
            continue
        if txn.is_duplicate:
            continue  # leave duplicates for exception review
        if txn.is_split or (txn.account_id and txn.status == "categorized"):
            to_clear.append(txn.id)

    if to_clear:
        set_cleared(db, recon, to_clear, True, actor=actor)
    else:
        refresh_reconciliation_totals(db, recon)
    return len(to_clear)


def _exception_row(txn: Transaction, *, kind: str, message: str, is_cleared: bool, in_period: bool) -> dict:
    return {
        "kind": kind,
        "message": message,
        "transaction_id": txn.id,
        "txn_date": txn.txn_date.isoformat(),
        "description": txn.description,
        "amount": float(txn.amount),
        "currency": txn.currency,
        "status": txn.status,
        "is_split": txn.is_split,
        "is_duplicate": txn.is_duplicate,
        "is_cleared": is_cleared,
        "in_period": in_period,
        "account_id": txn.account_id,
        "account_code": txn.account.code if txn.account else None,
        "account_name": txn.account.name if txn.account else None,
        "counter_entity_id": txn.counter_entity_id,
        "intercompany_match_id": txn.intercompany_match_id,
        "blocking": kind in ("uncategorized", "duplicate", "difference"),
    }


def build_exceptions(db: Session, recon: Reconciliation) -> list[dict]:
    sync_reconciliation_items(db, recon)
    refresh_reconciliation_totals(db, recon)
    start = period_start(recon.period_year, recon.period_month)
    end = period_end(recon.period_year, recon.period_month)

    items = (
        db.scalars(
            select(ReconciliationItem)
            .options(
                joinedload(ReconciliationItem.transaction).joinedload(Transaction.account),
            )
            .where(ReconciliationItem.reconciliation_id == recon.id)
        )
        .unique()
        .all()
    )

    exceptions: list[dict] = []
    seen: set[tuple[str, int]] = set()

    for item in items:
        txn = item.transaction
        if not txn or txn.status == "void":
            continue
        in_period = start <= txn.txn_date <= end

        if txn.is_duplicate:
            key = ("duplicate", txn.id)
            if key not in seen:
                seen.add(key)
                exceptions.append(
                    _exception_row(
                        txn,
                        kind="duplicate",
                        message="Possible duplicate — confirm before clearing",
                        is_cleared=item.is_cleared,
                        in_period=in_period,
                    )
                )

        if (txn.status == "uncategorized" and not txn.is_split) and (item.is_cleared or in_period):
            key = ("uncategorized", txn.id)
            if key not in seen:
                seen.add(key)
                exceptions.append(
                    _exception_row(
                        txn,
                        kind="uncategorized",
                        message="Needs categorization before lock"
                        if item.is_cleared or in_period
                        else "Uncategorized",
                        is_cleared=item.is_cleared,
                        in_period=in_period,
                    )
                )

        if (
            in_period
            and not item.is_cleared
            and not txn.is_duplicate
            and (txn.is_split or txn.status == "categorized")
        ):
            # Should have been auto-cleared — surface if somehow left uncleared
            key = ("uncleared", txn.id)
            if key not in seen:
                seen.add(key)
                exceptions.append(
                    _exception_row(
                        txn,
                        kind="uncleared",
                        message="In-period item not cleared",
                        is_cleared=False,
                        in_period=True,
                    )
                )

        if txn.account and (txn.account.is_intercompany or txn.account.account_type == "transfer"):
            if txn.intercompany_match_id is None:
                key = ("intercompany", txn.id)
                if key not in seen:
                    seen.add(key)
                    exceptions.append(
                        _exception_row(
                            txn,
                            kind="intercompany",
                            message="Unmatched intercompany transfer",
                            is_cleared=item.is_cleared,
                            in_period=in_period,
                        )
                    )

    # Difference drivers: uncleared items (especially in-period)
    if Decimal(recon.difference or 0) != Decimal("0"):
        uncleared = [
            item
            for item in items
            if item.transaction
            and not item.is_cleared
            and item.transaction.status != "void"
        ]
        # Sort by absolute amount descending — biggest drivers first
        uncleared.sort(key=lambda i: abs(Decimal(i.transaction.amount)), reverse=True)
        for item in uncleared[:25]:
            txn = item.transaction
            in_period = start <= txn.txn_date <= end
            key = ("difference", txn.id)
            if key in seen:
                continue
            # Don't duplicate if already listed as uncategorized/duplicate
            if any(e["transaction_id"] == txn.id and e["kind"] in ("uncategorized", "duplicate") for e in exceptions):
                continue
            seen.add(key)
            exceptions.append(
                _exception_row(
                    txn,
                    kind="difference",
                    message=(
                        "Uncleared prior-period item (timing)"
                        if not in_period
                        else "Uncleared — drives statement difference"
                    ),
                    is_cleared=False,
                    in_period=in_period,
                )
            )

    # Stable sort: blocking first, then kind, then date
    kind_order = {"uncategorized": 0, "duplicate": 1, "difference": 2, "intercompany": 3, "uncleared": 4}
    exceptions.sort(key=lambda e: (0 if e["blocking"] else 1, kind_order.get(e["kind"], 9), e["txn_date"], e["transaction_id"]))
    return exceptions


def build_close_pack_status(db: Session, recon: Reconciliation) -> dict:
    bank = db.get(BankAccount, recon.bank_account_id)
    entity = db.get(DimEntity, bank.entity_id) if bank else None
    beg = beginning_balance(db, recon.bank_account_id, recon.period_year, recon.period_month)
    sync_reconciliation_items(db, recon)
    refresh_reconciliation_totals(db, recon)
    exceptions = build_exceptions(db, recon)

    blocking = [e for e in exceptions if e["blocking"]]
    # Intercompany is advisory unless it blocks difference — keep non-blocking
    can_lock = (
        recon.status != "locked"
        and Decimal(recon.difference or 0) == Decimal("0")
        and len(blocking) == 0
    )

    items = (
        db.scalars(
            select(ReconciliationItem)
            .options(joinedload(ReconciliationItem.transaction))
            .where(ReconciliationItem.reconciliation_id == recon.id)
        )
        .unique()
        .all()
    )
    cleared_count = sum(1 for i in items if i.is_cleared)
    uncleared_count = sum(1 for i in items if not i.is_cleared)
    cleared_total = Decimal("0")
    for item in items:
        txn = item.transaction
        if item.is_cleared and txn is not None and txn.status != "void":
            cleared_total += Decimal(txn.amount)

    uncategorized_count = sum(1 for e in exceptions if e["kind"] == "uncategorized")
    duplicate_count = sum(1 for e in exceptions if e["kind"] == "duplicate")

    return {
        "reconciliation_id": recon.id,
        "bank_account_id": recon.bank_account_id,
        "bank_account_name": bank.name if bank else None,
        "entity_code": entity.code if entity else None,
        "currency": bank.currency if bank else None,
        "period_year": recon.period_year,
        "period_month": recon.period_month,
        "period_label": f"{recon.period_year}-{recon.period_month:02d}",
        "status": recon.status,
        "beginning_balance": float(beg),
        "statement_ending_balance": float(recon.statement_ending_balance),
        "calculated_balance": float(recon.calculated_balance or 0),
        "cleared_total": float(cleared_total),
        "difference": float(recon.difference or 0),
        "cleared_count": cleared_count,
        "uncleared_count": uncleared_count,
        "exception_count": len(exceptions),
        "blocking_count": len(blocking),
        "uncategorized_count": uncategorized_count,
        "duplicate_count": duplicate_count,
        "can_lock": can_lock,
        "is_locked": recon.status == "locked",
        "exceptions": exceptions,
        "locked_at": recon.locked_at.isoformat() if recon.locked_at else None,
        "locked_by": recon.locked_by,
    }


def run_statement_close_pack(
    db: Session,
    *,
    bank_account_id: int,
    period_year: int,
    period_month: int,
    statement_ending_balance: Decimal,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    actor: str = "controller",
    auto_match_ic: bool = True,
) -> dict:
    """
    Full close pack:
    optional import → rules → open/update recon → auto-clear → exception queue.
    """
    bank = db.get(BankAccount, bank_account_id)
    if not bank:
        raise ValueError("Bank account not found")

    import_result: ImportResult | None = None
    if file_bytes and filename:
        import_result = import_bank_file(
            db,
            file_bytes=file_bytes,
            filename=filename,
            bank_account_id=bank_account_id,
            actor=actor,
        )

    # Re-apply rules to any remaining uncategorized on this bank
    uncat = list(
        db.scalars(
            select(Transaction).where(
                Transaction.bank_account_id == bank_account_id,
                Transaction.status == "uncategorized",
            )
        )
    )
    rules_hit = apply_rules_batch(db, uncat, actor=actor)

    if auto_match_ic:
        auto_match_intercompany(db, actor=actor)

    recon, created = get_or_open_reconciliation(
        db,
        bank_account_id=bank_account_id,
        period_year=period_year,
        period_month=period_month,
        statement_ending_balance=statement_ending_balance,
        actor=actor,
    )
    auto_cleared = auto_clear_statement_items(db, recon, actor=actor)
    status = build_close_pack_status(db, recon)

    write_audit(
        db,
        entity_table="close_packs",
        entity_id=recon.id,
        action="run",
        actor=actor,
        meta={
            "bank_account_id": bank_account_id,
            "period": status["period_label"],
            "created_recon": created,
            "auto_cleared": auto_cleared,
            "rules_hit": rules_hit,
            "imported": import_result.imported if import_result else 0,
            "exception_count": status["exception_count"],
            "can_lock": status["can_lock"],
        },
    )

    return {
        **status,
        "created_reconciliation": created,
        "auto_cleared": auto_cleared,
        "rules_applied": rules_hit,
        "import_result": import_result.model_dump() if import_result else None,
        "unmatched_intercompany_global": unmatched_intercompany_count(db),
    }


def resolve_exception_categorize(
    db: Session,
    *,
    reconciliation_id: int,
    transaction_id: int,
    account_id: int,
    create_rule: bool = True,
    clear_after: bool = True,
    actor: str = "controller",
) -> dict:
    recon = db.get(Reconciliation, reconciliation_id)
    if not recon:
        raise ValueError("Reconciliation not found")
    if recon.status == "locked":
        raise ValueError("Period is locked")

    txn = db.get(Transaction, transaction_id)
    if not txn:
        raise ValueError("Transaction not found")

    categorize_transaction(
        db,
        txn,
        CategorizeRequest(account_id=account_id, create_rule=create_rule),
        actor=actor,
    )

    start = period_start(recon.period_year, recon.period_month)
    end = period_end(recon.period_year, recon.period_month)
    if clear_after and start <= txn.txn_date <= end and not txn.is_duplicate:
        set_cleared(db, recon, [txn.id], True, actor=actor)
    else:
        refresh_reconciliation_totals(db, recon)

    return build_close_pack_status(db, recon)


def resolve_exception_clear(
    db: Session,
    *,
    reconciliation_id: int,
    transaction_id: int,
    is_cleared: bool = True,
    actor: str = "controller",
) -> dict:
    recon = db.get(Reconciliation, reconciliation_id)
    if not recon:
        raise ValueError("Reconciliation not found")
    set_cleared(db, recon, [transaction_id], is_cleared, actor=actor)
    return build_close_pack_status(db, recon)


def resolve_exception_void_duplicate(
    db: Session,
    *,
    reconciliation_id: int,
    transaction_id: int,
    actor: str = "controller",
) -> dict:
    recon = db.get(Reconciliation, reconciliation_id)
    if not recon:
        raise ValueError("Reconciliation not found")
    if recon.status == "locked":
        raise ValueError("Period is locked")
    txn = db.get(Transaction, transaction_id)
    if not txn:
        raise ValueError("Transaction not found")
    txn.status = "void"
    write_audit(
        db,
        entity_table="transactions",
        entity_id=txn.id,
        action="void",
        actor=actor,
        meta={"reason": "duplicate_excluded_from_close_pack"},
    )
    # Unclear if cleared
    item = db.scalar(
        select(ReconciliationItem).where(
            ReconciliationItem.reconciliation_id == recon.id,
            ReconciliationItem.transaction_id == transaction_id,
        )
    )
    if item and item.is_cleared:
        item.is_cleared = False
    refresh_reconciliation_totals(db, recon)
    return build_close_pack_status(db, recon)


def lock_close_pack(db: Session, reconciliation_id: int, actor: str = "controller") -> dict:
    recon = db.get(Reconciliation, reconciliation_id)
    if not recon:
        raise ValueError("Reconciliation not found")
    status = build_close_pack_status(db, recon)
    if not status["can_lock"]:
        raise ValueError(
            f"Cannot lock: difference={status['difference']}, "
            f"blocking exceptions={status['blocking_count']}"
        )
    complete_reconciliation(db, recon, actor=actor, lock=True)
    return build_close_pack_status(db, recon)


def build_next_actions(packs: list[dict]) -> list[dict]:
    """Ranked controller queue: categorize → difference → duplicates → start → lock."""
    actions: list[dict] = []
    for pack in packs:
        bank_id = pack["bank_account_id"]
        bank_name = pack.get("bank_account_name") or f"Bank {bank_id}"
        recon_id = pack.get("reconciliation_id")
        if pack.get("is_locked"):
            continue

        if pack.get("status") == "not_started":
            actions.append(
                {
                    "key": f"start-{bank_id}",
                    "kind": "not_started",
                    "priority": 40,
                    "title": f"Start close · {bank_name}",
                    "detail": "Enter statement ending balance and run the pack",
                    "bank_account_id": bank_id,
                    "bank_account_name": bank_name,
                    "reconciliation_id": None,
                    "mode": "exceptions",
                    "filter": None,
                    "count": None,
                    "amount": None,
                }
            )
            continue

        uncat = int(pack.get("uncategorized_count") or 0)
        if uncat:
            actions.append(
                {
                    "key": f"cat-{bank_id}",
                    "kind": "categorize",
                    "priority": 10,
                    "title": f"Categorize {uncat} · {bank_name}",
                    "detail": "Uncategorized items blocking the exception pass",
                    "bank_account_id": bank_id,
                    "bank_account_name": bank_name,
                    "reconciliation_id": recon_id,
                    "mode": "exceptions",
                    "filter": "uncategorized",
                    "count": uncat,
                    "amount": None,
                }
            )

        diff = pack.get("difference")
        if diff is not None and abs(float(diff)) >= 0.01:
            actions.append(
                {
                    "key": f"diff-{bank_id}",
                    "kind": "difference",
                    "priority": 20,
                    "title": f"Diff {float(diff):,.2f} · {bank_name}",
                    "detail": "Clear or unclear items until the tie-out is zero",
                    "bank_account_id": bank_id,
                    "bank_account_name": bank_name,
                    "reconciliation_id": recon_id,
                    "mode": "items",
                    "filter": "uncleared",
                    "count": int(pack.get("uncleared_count") or 0),
                    "amount": float(diff),
                }
            )

        dups = int(pack.get("duplicate_count") or 0)
        if dups:
            actions.append(
                {
                    "key": f"dup-{bank_id}",
                    "kind": "duplicate",
                    "priority": 25,
                    "title": f"Review {dups} duplicate(s) · {bank_name}",
                    "detail": "Void duplicates or keep & clear",
                    "bank_account_id": bank_id,
                    "bank_account_name": bank_name,
                    "reconciliation_id": recon_id,
                    "mode": "exceptions",
                    "filter": "duplicate",
                    "count": dups,
                    "amount": None,
                }
            )

        if pack.get("can_lock"):
            actions.append(
                {
                    "key": f"lock-{bank_id}",
                    "kind": "ready_to_lock",
                    "priority": 50,
                    "title": f"Ready to lock · {bank_name}",
                    "detail": "No blocking exceptions; difference is zero",
                    "bank_account_id": bank_id,
                    "bank_account_name": bank_name,
                    "reconciliation_id": recon_id,
                    "mode": "exceptions",
                    "filter": None,
                    "count": None,
                    "amount": 0.0,
                }
            )

    actions.sort(key=lambda a: (a["priority"], a.get("bank_account_name") or ""))
    return actions


def month_close_overview(db: Session, year: int, month: int) -> dict:
    banks = list(db.scalars(select(BankAccount).where(BankAccount.is_active == True)).all())
    entities = {e.id: e for e in db.scalars(select(DimEntity)).all()}
    packs = []
    for bank in banks:
        recon = db.scalar(
            select(Reconciliation).where(
                Reconciliation.bank_account_id == bank.id,
                Reconciliation.period_year == year,
                Reconciliation.period_month == month,
            )
        )
        if recon:
            status = build_close_pack_status(db, recon)
        else:
            beg = beginning_balance(db, bank.id, year, month)
            status = {
                "reconciliation_id": None,
                "bank_account_id": bank.id,
                "bank_account_name": bank.name,
                "entity_code": entities[bank.entity_id].code if bank.entity_id in entities else None,
                "currency": bank.currency,
                "period_year": year,
                "period_month": month,
                "period_label": f"{year}-{month:02d}",
                "status": "not_started",
                "beginning_balance": float(beg),
                "statement_ending_balance": None,
                "calculated_balance": None,
                "cleared_total": None,
                "difference": None,
                "cleared_count": 0,
                "uncleared_count": 0,
                "exception_count": 0,
                "blocking_count": 0,
                "uncategorized_count": 0,
                "duplicate_count": 0,
                "can_lock": False,
                "is_locked": False,
                "exceptions": [],
            }
        packs.append(status)

    ready = [p for p in packs if p["can_lock"]]
    locked = [p for p in packs if p["is_locked"]]
    in_progress = [
        p for p in packs if p["status"] not in ("not_started", "locked") and not p["can_lock"]
    ]
    return {
        "period_year": year,
        "period_month": month,
        "period_label": f"{year}-{month:02d}",
        "banks_total": len(packs),
        "banks_locked": len(locked),
        "banks_ready_to_lock": len(ready),
        "banks_in_progress": len(in_progress),
        "can_lock_month": bool(packs)
        and all(p["is_locked"] or p["can_lock"] for p in packs)
        and len(ready) > 0,
        "all_locked": len(locked) == len(packs) and len(packs) > 0,
        "packs": packs,
        "next_actions": build_next_actions(packs),
    }


def lock_month(db: Session, year: int, month: int, actor: str = "controller") -> dict:
    overview = month_close_overview(db, year, month)
    locked_ids = []
    errors = []
    for pack in overview["packs"]:
        if pack["is_locked"]:
            continue
        if not pack["can_lock"] or not pack["reconciliation_id"]:
            errors.append(
                {
                    "bank_account_id": pack["bank_account_id"],
                    "name": pack["bank_account_name"],
                    "reason": "not ready",
                }
            )
            continue
        try:
            lock_close_pack(db, pack["reconciliation_id"], actor=actor)
            locked_ids.append(pack["reconciliation_id"])
        except ValueError as exc:
            errors.append(
                {
                    "bank_account_id": pack["bank_account_id"],
                    "name": pack["bank_account_name"],
                    "reason": str(exc),
                }
            )
    result = month_close_overview(db, year, month)
    result["newly_locked"] = locked_ids
    result["errors"] = errors
    write_audit(
        db,
        entity_table="close_packs",
        entity_id=0,
        action="lock_month",
        actor=actor,
        meta={"period": f"{year}-{month:02d}", "locked": locked_ids, "errors": errors},
    )
    return result
