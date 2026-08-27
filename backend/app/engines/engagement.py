"""Engagement home — ordered close / binder queue for one entity + period."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines.binder import build_binder
from app.engines.cash_wp import build_cash_recon_schedule
from app.engines.close_pack import month_close_overview
from app.models import BankAccount, DimEntity, Transaction


def build_engagement_home(
    db: Session,
    *,
    year: int,
    month: int,
    entity_id: int | None = None,
) -> dict:
    entity = db.get(DimEntity, entity_id) if entity_id else None
    close = month_close_overview(db, year, month)
    packs = close["packs"]
    if entity_id:
        packs = [p for p in packs if _pack_entity(db, p) == entity_id]

    bank_ids = None
    if entity_id:
        bank_ids = list(
            db.scalars(select(BankAccount.id).where(BankAccount.entity_id == entity_id, BankAccount.is_active == True))
        )

    uncat_q = select(func.count()).select_from(Transaction).where(
        Transaction.status == "uncategorized",
        Transaction.is_split == False,  # noqa: E712
    )
    if bank_ids is not None:
        if not bank_ids:
            uncategorized = 0
        else:
            uncategorized = db.scalar(uncat_q.where(Transaction.bank_account_id.in_(bank_ids))) or 0
    else:
        uncategorized = db.scalar(uncat_q) or 0

    binder = build_binder(db, year, month, entity_id=entity_id)
    cash = build_cash_recon_schedule(db, year, month, entity_id=entity_id)
    cash_banks = cash["banks"]

    queue: list[dict] = []
    step = 1

    if uncategorized:
        queue.append(
            {
                "key": "uncategorized",
                "step": step,
                "phase": "work",
                "priority": 10,
                "title": f"Categorize {uncategorized} transactions",
                "detail": "Clear uncategorized items before recon can lock cleanly.",
                "href": f"/work?year={year}&month={month}&filter=uncategorized"
                + (f"&bank={bank_ids[0]}" if bank_ids else ""),
                "count": int(uncategorized),
                "status": "open",
            }
        )
        step += 1

    blocking_packs = [p for p in packs if int(p.get("blocking_count") or 0) > 0]
    for pack in blocking_packs[:5]:
        queue.append(
            {
                "key": f"block-{pack['bank_account_id']}",
                "step": step,
                "phase": "work",
                "priority": 20,
                "title": f"Clear exceptions · {pack.get('bank_account_name')}",
                "detail": f"{pack.get('blocking_count')} blocking · diff {pack.get('difference')}",
                "href": (
                    f"/work?year={year}&month={month}&bank={pack['bank_account_id']}"
                    f"&mode=exceptions"
                ),
                "count": int(pack.get("blocking_count") or 0),
                "status": "open",
            }
        )
        step += 1

    open_diff = [
        p
        for p in packs
        if p.get("status") != "not_started"
        and p.get("difference") is not None
        and abs(float(p["difference"])) >= 0.01
        and int(p.get("blocking_count") or 0) == 0
    ]
    for pack in open_diff[:3]:
        queue.append(
            {
                "key": f"diff-{pack['bank_account_id']}",
                "step": step,
                "phase": "work",
                "priority": 30,
                "title": f"Tie recon · {pack.get('bank_account_name')}",
                "detail": f"Difference still open: {pack.get('difference')}",
                "href": f"/work?year={year}&month={month}&bank={pack['bank_account_id']}&mode=items",
                "count": None,
                "status": "open",
            }
        )
        step += 1

    ready = [p for p in packs if p.get("can_lock") and not p.get("is_locked")]
    for pack in ready[:3]:
        queue.append(
            {
                "key": f"lock-{pack['bank_account_id']}",
                "step": step,
                "phase": "work",
                "priority": 40,
                "title": f"Lock · {pack.get('bank_account_name')}",
                "detail": "Ready to lock for the period.",
                "href": f"/work?year={year}&month={month}&bank={pack['bank_account_id']}",
                "count": None,
                "status": "ready",
            }
        )
        step += 1

    not_started = [p for p in packs if p.get("status") == "not_started"]
    for pack in not_started[:3]:
        queue.append(
            {
                "key": f"start-{pack['bank_account_id']}",
                "step": step,
                "phase": "work",
                "priority": 50,
                "title": f"Start recon · {pack.get('bank_account_name')}",
                "detail": "No statement pack started for this period.",
                "href": f"/work?year={year}&month={month}&bank={pack['bank_account_id']}",
                "count": None,
                "status": "open",
            }
        )
        step += 1

    # Cash WP gate — entity-scoped schedule
    entity_cash_tied = bool(cash.get("is_tied")) if cash_banks else False
    if cash_banks and not entity_cash_tied:
        queue.append(
            {
                "key": "cash-wp",
                "step": step,
                "phase": "binder",
                "priority": 60,
                "title": "Finish Cash WP C.1",
                "detail": "Bank diffs or BS cash vs books still open — prepare is gated.",
                "href": f"/binder?year={year}&month={month}&key=cash"
                + (f"&entity_id={entity_id}" if entity_id else ""),
                "count": None,
                "status": "open",
            }
        )
        step += 1
    elif cash_banks and cash.get("can_prepare") and not cash.get("can_review"):
        cash_doc = next((d for d in binder["documents"] if d["key"] == "cash"), None)
        if cash_doc and cash_doc["status"] == "open":
            queue.append(
                {
                    "key": "cash-prepare",
                    "step": step,
                    "phase": "binder",
                    "priority": 65,
                    "title": "Prepare Cash WP C.1",
                    "detail": "Banks are ready — sign off preparer on Cash.",
                    "href": f"/binder?year={year}&month={month}&key=cash"
                    + (f"&entity_id={entity_id}" if entity_id else ""),
                    "count": None,
                    "status": "ready",
                }
            )
            step += 1

    untied = [d for d in binder["documents"] if d.get("is_tied") is False and d["key"] != "cash"]
    for doc in untied[:4]:
        queue.append(
            {
                "key": f"untied-{doc['key']}",
                "step": step,
                "phase": "binder",
                "priority": 70,
                "title": f"Tie {doc['wp_ref']} · {doc['title']}",
                "detail": f"Lead difference {doc.get('difference')}",
                "href": doc["href"],
                "count": None,
                "status": "open",
            }
        )
        step += 1

    unsigned = [
        d
        for d in binder["documents"]
        if d["status"] not in ("prepared", "reviewed") and d.get("is_tied") is not False
    ]
    for doc in unsigned[:4]:
        queue.append(
            {
                "key": f"sign-{doc['key']}",
                "step": step,
                "phase": "binder",
                "priority": 80,
                "title": f"Sign {doc['wp_ref']} · {doc['title']}",
                "detail": f"{doc['procedures_done']}/{doc['procedure_count']} procedures · status {doc['status']}",
                "href": doc["href"],
                "count": None,
                "status": "ready" if doc.get("is_tied") else "open",
            }
        )
        step += 1

    if not queue:
        queue.append(
            {
                "key": "done",
                "step": 1,
                "phase": "home",
                "priority": 100,
                "title": "Engagement clear for this period",
                "detail": "No open blockers. Review statements or lock remaining packs.",
                "href": f"/statements?year={year}&month={month}&tab=statement",
                "count": None,
                "status": "ok",
            }
        )

    locked = sum(1 for p in packs if p.get("is_locked"))
    reviewed = sum(1 for d in binder["documents"] if d["status"] == "reviewed")

    return {
        "period_year": year,
        "period_month": month,
        "period_label": f"{year}-{month:02d}",
        "entity_id": entity_id,
        "entity_code": entity.code if entity else None,
        "entity_name": entity.name if entity else None,
        "progress": {
            "banks_total": len(packs),
            "banks_locked": locked,
            "blocking_total": sum(int(p.get("blocking_count") or 0) for p in packs),
            "uncategorized": int(uncategorized),
            "binder_total": binder["summary"]["total"],
            "binder_reviewed": reviewed,
            "binder_untied": binder["summary"]["untied"],
            "cash_ready": bool(cash.get("can_prepare")),
        },
        "queue": queue,
        "work_href": f"/work?year={year}&month={month}",
        "binder_href": f"/binder?year={year}&month={month}",
        "statements_href": f"/statements?year={year}&month={month}&tab=statement",
    }


def _pack_entity(db: Session, pack: dict) -> int | None:
    if pack.get("entity_id"):
        return int(pack["entity_id"])
    bank_id = pack.get("bank_account_id")
    if not bank_id:
        return None
    return _bank_entity(db, bank_id)


def _bank_entity(db: Session, bank_id: int) -> int | None:
    bank = db.get(BankAccount, bank_id)
    return bank.entity_id if bank else None
