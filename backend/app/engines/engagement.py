"""Engagement home — pack exceptions for one entity + period."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.close_pack import month_close_overview
from app.engines.entity_close import get_entity_period_lock, is_journal_led_entity, serialize_lock
from app.engines.intercompany import unmatched_intercompany_count
from app.engines.journals import list_journals
from app.engines.statement_pack import build_statement_diagnostics
from app.models import BankAccount, DimEntity
from app.schemas.reports import ReportFilter


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

    journals = list_journals(db, year=year, month=month, entity_id=entity_id) if entity_id else []
    unmatched_ic = unmatched_intercompany_count(db, entity_id=entity_id, year=year, month=month)

    close = month_close_overview(db, year, month)
    packs = close["packs"]
    if entity_id:
        packs = [p for p in packs if _pack_entity(db, p) == entity_id]

    statements_href = f"/statements?year={year}&month={month}&tab=bs"
    work_href = f"/work?year={year}&month={month}"
    binder_href = f"/binder?year={year}&month={month}"

    queue: list[dict] = []
    statements_balanced = False
    can_print = False
    uncategorized = 0
    unmapped = 0

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
            uncategorized = int(diag.uncategorized_count)
            unmapped = int(diag.unmapped_count)
            for i, plug in enumerate(diag.plugs, start=1):
                href = plug.href or statements_href
                if plug.key == "uncategorized":
                    href = f"{work_href}&filter=uncategorized"
                queue.append(
                    {
                        "key": plug.key,
                        "step": i,
                        "phase": "home",
                        "priority": 10 * i,
                        "title": plug.title,
                        "detail": plug.detail,
                        "href": href,
                        "count": None,
                        "status": "open",
                    }
                )
        except ValueError:
            queue.append(
                {
                    "key": "scope",
                    "step": 1,
                    "phase": "home",
                    "priority": 10,
                    "title": "Select one entity",
                    "detail": "This pack does not consolidate CAN and USA.",
                    "href": statements_href,
                    "count": None,
                    "status": "open",
                }
            )

    if not queue:
        queue.append(
            {
                "key": "pack-ready",
                "step": 1,
                "phase": "home",
                "priority": 100,
                "title": "Pack is printable",
                "detail": "P&L, balance sheet, equity, and trial balance for this entity.",
                "href": statements_href,
                "count": None,
                "status": "ok",
            }
        )

    locked = sum(1 for p in packs if p.get("is_locked"))
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
            "uncategorized": uncategorized,
            "binder_total": 0,
            "binder_reviewed": 0,
            "binder_untied": unmapped,
            "cash_ready": True,
            "feeds_connected": 0,
            "feeds_pending": 0,
            "unmatched_ic": int(unmatched_ic),
            "journals": len(journals),
            "month_locked": bool(month_lock and month_lock.get("is_locked")),
            "journal_led": journal_led,
            "statements_balanced": statements_balanced,
            "can_print": can_print,
        },
        "queue": queue,
        "work_href": work_href,
        "binder_href": binder_href,
        "statements_href": statements_href,
    }


def _pack_entity(db: Session, pack: dict) -> int | None:
    if pack.get("entity_id"):
        return int(pack["entity_id"])
    bank_id = pack.get("bank_account_id")
    if not bank_id:
        return None
    bank = db.get(BankAccount, bank_id)
    return bank.entity_id if bank else None
