"""Engagement home — ordered monthly rec queue for one entity + period."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines.bank_feeds import list_feeds
from app.engines.binder import build_binder
from app.engines.cash_wp import build_cash_recon_schedule
from app.engines.close_pack import month_close_overview
from app.engines.entity_close import get_entity_period_lock, is_journal_led_entity, serialize_lock
from app.engines.intercompany import unmatched_intercompany_count
from app.engines.journals import list_journals
from app.engines.reporting import build_report
from app.engines.statement_pack import build_statement_diagnostics
from app.models import BankAccount, DimEntity, Transaction
from app.schemas.reports import ReportFilter


def _mom_flux(db: Session, *, year: int, month: int, entity_id: int | None, currency: str) -> list:
    end = date(year, month, monthrange(year, month)[1])
    report = build_report(
        db,
        ReportFilter(
            report_type="income_statement",
            period="monthly",
            year=year,
            month=month,
            date_to=end,
            as_of_date=end,
            compare_prior_period=True,
            scenario_id=1,
            reporting_currency=currency,
            consolidate=entity_id is None,
            entity_ids=[entity_id] if entity_id else None,
            materiality_amount=Decimal("1000"),
            materiality_pct=Decimal("10"),
        ),
    )
    return list(report.flux[:4])


def build_engagement_home(
    db: Session,
    *,
    year: int,
    month: int,
    entity_id: int | None = None,
) -> dict:
    entity = db.get(DimEntity, entity_id) if entity_id else None
    currency = (entity.functional_currency if entity else None) or "CAD"
    journal_led = bool(entity_id) and is_journal_led_entity(db, entity_id)
    lock_row = get_entity_period_lock(db, entity_id, year, month) if entity_id else None
    month_lock = (
        serialize_lock(lock_row, entity_id=entity_id, year=year, month=month)
        if entity_id
        else None
    )
    if month_lock:
        month_lock["journal_led"] = journal_led
    unmatched_ic = unmatched_intercompany_count(db, entity_id=entity_id, year=year, month=month)
    journals = list_journals(db, year=year, month=month, entity_id=entity_id) if entity_id else []

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
    cash_na = bool(cash.get("not_applicable"))

    queue: list[dict] = []
    step = 1

    feeds = list_feeds(db, entity_id=entity_id, include_pending=False)
    feeds_connected = sum(1 for f in feeds if f["status"] == "connected")
    feeds_pending = sum(int(f["pending_count"] or 0) for f in feeds if f["status"] == "connected")
    disconnected = [f for f in feeds if f["status"] != "connected"]
    pending_feeds = [f for f in feeds if f["status"] == "connected" and int(f["pending_count"] or 0) > 0]

    if journal_led:
        if journals:
            queue.append(
                {
                    "key": "review-journals",
                    "step": step,
                    "phase": "work",
                    "priority": 10,
                    "title": f"Review {len(journals)} month-end journal(s)",
                    "detail": "Journal-led monthly rec — confirm FY vouchers before binder sign-off.",
                    "href": f"/work?year={year}&month={month}",
                    "count": len(journals),
                    "status": "open",
                }
            )
            step += 1
        else:
            queue.append(
                {
                    "key": "post-journals",
                    "step": step,
                    "phase": "work",
                    "priority": 10,
                    "title": "Post month-end journals",
                    "detail": "No journals in this month yet. Post the monthly rec pack from Work.",
                    "href": f"/work?year={year}&month={month}",
                    "count": None,
                    "status": "open",
                }
            )
            step += 1
    else:
        if disconnected:
            queue.append(
                {
                    "key": "connect-feeds",
                    "step": step,
                    "phase": "work",
                    "priority": 4,
                    "title": f"Connect {len(disconnected)} bank feed(s)",
                    "detail": "Live feeds replace CSV uploads and typed statement balances.",
                    "href": "/bank-accounts",
                    "count": len(disconnected),
                    "status": "open",
                }
            )
            step += 1

        if pending_feeds:
            first = pending_feeds[0]
            queue.append(
                {
                    "key": "sync-feeds",
                    "step": step,
                    "phase": "work",
                    "priority": 5,
                    "title": f"Pull {feeds_pending} live bank item(s)",
                    "detail": "New activity on the feed — sync before recon so the statement balance is complete.",
                    "href": f"/work?year={year}&month={month}&bank={first['bank_account_id']}",
                    "count": feeds_pending,
                    "status": "open",
                }
            )
            step += 1

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

    if unmatched_ic:
        queue.append(
            {
                "key": "unmatched-ic",
                "step": step,
                "phase": "binder",
                "priority": 55,
                "title": f"Match {unmatched_ic} intercompany item(s)",
                "detail": "Monthly CAN↔USA rec — unmatched IC blocks the Intercompany working paper.",
                "href": f"/binder?year={year}&month={month}&key=interco"
                + (f"&entity_id={entity_id}" if entity_id else ""),
                "count": int(unmatched_ic),
                "status": "open",
            }
        )
        step += 1

    flux_items = _mom_flux(db, year=year, month=month, entity_id=entity_id, currency=currency)
    pnl = next((d for d in binder["documents"] if d["key"] == "pnl_analysis"), None)
    if not pnl or pnl["status"] != "reviewed":
        for item in flux_items[:3]:
            queue.append(
                {
                    "key": f"flux-{item.line_code}",
                    "step": step,
                    "phase": "binder",
                    "priority": 58,
                    "title": f"Explain MoM flux · {item.line_label}",
                    "detail": item.note or f"{item.line_label} moved vs last month.",
                    "href": (
                        f"/statements?year={year}&month={month}&tab=statement&type=income_statement"
                        f"&line={item.line_code}"
                        + (f"&entity_id={entity_id}" if entity_id else "")
                    ),
                    "count": None,
                    "status": "open",
                }
            )
            step += 1

    entity_cash_tied = bool(cash.get("is_tied")) if cash_banks else cash_na
    if not cash_na and cash_banks and not entity_cash_tied:
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
    elif not cash_na and cash_banks and cash.get("can_prepare") and not cash.get("can_review"):
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

    statements_balanced = False
    can_print = False
    if entity_id:
        end = date(year, month, monthrange(year, month)[1])
        try:
            diag = build_statement_diagnostics(
                db,
                ReportFilter(
                    report_type="balance_sheet",
                    year=year,
                    month=month,
                    as_of_date=end,
                    date_to=end,
                    scenario_id=1,
                    reporting_currency=currency,
                    entity_ids=[entity_id],
                    consolidate=False,
                ),
            )
            statements_balanced = bool(diag.is_balanced)
            can_print = bool(diag.can_print)
            if not diag.can_print:
                plug_titles = "; ".join(p.title for p in diag.plugs[:3]) or "Exceptions remain"
                queue.append(
                    {
                        "key": "statements-balance",
                        "step": step,
                        "phase": "home",
                        "priority": 85,
                        "title": "Statement will not balance",
                        "detail": plug_titles,
                        "href": (diag.statements_href or f"/statements?year={year}&month={month}&tab=bs")
                        + f"&entity_id={entity_id}",
                        "count": len(diag.plugs) or None,
                        "status": "open",
                    }
                )
                step += 1
        except ValueError:
            pass

    if entity_id and not (month_lock and month_lock.get("is_locked")):
        queue.append(
            {
                "key": "lock-month",
                "step": step,
                "phase": "home",
                "priority": 90,
                "title": "Lock month",
                "detail": "Freeze the GL for this monthly rec. Late items post as PCA (post-close adj).",
                "href": f"/?year={year}&month={month}",
                "count": None,
                "status": "ready" if not unmatched_ic else "open",
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
                "title": "Monthly rec clear for this period",
                "detail": "No open blockers. Review statements or lock remaining packs.",
                "href": f"/statements?year={year}&month={month}&tab=statement",
                "count": None,
                "status": "ok",
            }
        )
    elif month_lock and month_lock.get("is_locked") and all(q.get("status") != "open" for q in queue):
        queue.append(
            {
                "key": "done",
                "step": step,
                "phase": "home",
                "priority": 100,
                "title": "Month locked",
                "detail": "GL is frozen. Post a post-close adj (PCA) for anything that lands after lock.",
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
        "journal_led": journal_led,
        "month_lock": month_lock,
        "progress": {
            "banks_total": len(packs),
            "banks_locked": locked,
            "blocking_total": sum(int(p.get("blocking_count") or 0) for p in packs),
            "uncategorized": int(uncategorized),
            "binder_total": binder["summary"]["total"],
            "binder_reviewed": reviewed,
            "binder_untied": binder["summary"]["untied"],
            "cash_ready": bool(cash.get("can_prepare")),
            "feeds_connected": feeds_connected,
            "feeds_pending": feeds_pending,
            "unmatched_ic": int(unmatched_ic),
            "journals": len(journals),
            "month_locked": bool(month_lock and month_lock.get("is_locked")),
            "journal_led": journal_led,
            "statements_balanced": statements_balanced,
            "can_print": can_print,
        },
        "queue": queue,
        "work_href": f"/work?year={year}&month={month}",
        "binder_href": f"/binder?year={year}&month={month}",
        "statements_href": f"/statements?year={year}&month={month}&tab=bs",
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
