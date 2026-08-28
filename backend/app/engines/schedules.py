"""Live working-paper schedules: aging, rollforward, IC listing, P&L lead."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.fx import translate_amount
from app.engines.reporting import _iter_fact_lines, _signed_amount, build_report
from app.engines.working_papers import get_template
from app.models import DimAccount, DimEntity
from app.schemas.reports import ReportFilter

AGING_KEYS = ("ar", "ap")
ROLLFORWARD_KEYS = (
    "prepaid",
    "inventory",
    "unearned_revenue",
    "taxes_payable",
    "shareholder_loan",
    "equity",
)
IC_KEYS = ("interco",)
PNL_KEYS = ("pnl_analysis",)


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def _age_bucket(txn_date: date, as_of: date) -> str:
    days = (as_of - txn_date).days
    if days <= 30:
        return "current"
    if days <= 60:
        return "days_31_60"
    if days <= 90:
        return "days_61_90"
    return "days_91_plus"


def _entity_currency(db: Session, entity_id: int | None) -> str:
    if entity_id is None:
        return "CAD"
    ent = db.get(DimEntity, entity_id)
    return (ent.functional_currency if ent else None) or "CAD"


def _report_filters(template, year: int, month: int, entity_id: int | None, reporting_currency: str) -> ReportFilter:
    end = _month_end(year, month)
    entity_ids = [entity_id] if entity_id is not None else None
    consolidate = entity_id is None
    if template.statement == "balance_sheet":
        return ReportFilter(
            report_type="balance_sheet",
            as_of_date=end,
            year=year,
            month=month,
            scenario_id=1,
            reporting_currency=reporting_currency,
            consolidate=consolidate,
            entity_ids=entity_ids,
        )
    return ReportFilter(
        report_type="income_statement",
        period="ytd",
        year=year,
        month=month,
        date_to=end,
        as_of_date=end,
        scenario_id=1,
        reporting_currency=reporting_currency,
        consolidate=consolidate,
        entity_ids=entity_ids,
    )


def _gl_amount(
    db: Session, template, year: int, month: int, entity_id: int | None, reporting_currency: str
) -> tuple[str, Decimal]:
    filters = _report_filters(template, year, month, entity_id, reporting_currency)
    report = build_report(db, filters)
    by_code = {line.line_code: line for line in report.lines}
    for code in template.line_codes:
        if code in by_code:
            return code, Decimal(by_code[code].amount)
    return template.line_codes[0] if template.line_codes else template.key, Decimal("0")


def _account_ids(db: Session, template) -> list[int]:
    codes = set(template.account_codes)
    rows = list(db.scalars(select(DimAccount)))
    ids = [a.id for a in rows if a.code in codes]
    if ids:
        return ids
    # P&L: all revenue/expense
    if template.key == "pnl_analysis":
        return [a.id for a in rows if a.account_type in ("revenue", "expense") and a.is_active]
    if template.key == "interco":
        return [a.id for a in rows if a.is_intercompany or a.account_type in ("transfer", "intercompany")]
    return ids


def _fact_rows(
    db: Session,
    *,
    account_ids: set[int],
    date_from: date,
    date_to: date,
    entity_id: int | None,
    report_type: str,
    reporting_currency: str = "CAD",
) -> list[dict]:
    accounts = {a.id: a for a in db.scalars(select(DimAccount)).all()}
    entities = {e.id: e for e in db.scalars(select(DimEntity)).all()}
    rows: list[dict] = []
    entity_ids = [entity_id] if entity_id is not None else None
    for txn, account_id, _dept, amount in _iter_fact_lines(
        db,
        date_from=date_from,
        date_to=date_to,
        scenario_id=1,
        entity_ids=entity_ids,
        department_ids=None,
    ):
        if account_id not in account_ids:
            continue
        acct = accounts.get(account_id)
        if not acct:
            continue
        translated, _ = translate_amount(
            db,
            amount=amount,
            from_currency=txn.currency,
            to_currency=reporting_currency,
            as_of=txn.txn_date,
            rate_type="closing" if report_type == "balance_sheet" else "average",
        )
        signed = _signed_amount(acct, translated, report_type)
        entity = entities.get(txn.entity_id)
        rows.append(
            {
                "transaction_id": txn.id,
                "txn_date": txn.txn_date.isoformat(),
                "description": txn.description,
                "counterparty": txn.counterparty or txn.description[:48],
                "entity_code": entity.code if entity else None,
                "account_code": acct.code,
                "account_name": acct.name,
                "signed_amount": float(signed),
                "amount": signed,
                "currency": reporting_currency,
                "source_type": txn.source_type,
                "intercompany_match_id": txn.intercompany_match_id,
                "counter_entity_id": txn.counter_entity_id,
                "is_matched": txn.intercompany_match_id is not None,
            }
        )
    return rows


def _aging_schedule(rows: list[dict], as_of: date, gl: Decimal) -> dict:
    buckets = {"current": Decimal("0"), "days_31_60": Decimal("0"), "days_61_90": Decimal("0"), "days_91_plus": Decimal("0")}
    by_party: dict[str, dict] = {}
    for row in rows:
        txn_date = date.fromisoformat(row["txn_date"])
        bucket = _age_bucket(txn_date, as_of)
        amt = row["amount"]
        buckets[bucket] += amt
        key = row["counterparty"] or "—"
        party = by_party.setdefault(
            key,
            {
                "counterparty": key,
                "current": Decimal("0"),
                "days_31_60": Decimal("0"),
                "days_61_90": Decimal("0"),
                "days_91_plus": Decimal("0"),
                "total": Decimal("0"),
                "count": 0,
            },
        )
        party[bucket] += amt
        party["total"] += amt
        party["count"] += 1

    listing = sorted(by_party.values(), key=lambda p: abs(p["total"]), reverse=True)
    total = sum((b for b in buckets.values()), Decimal("0"))
    diff = total - gl
    return {
        "kind": "aging",
        "buckets": {k: float(v) for k, v in buckets.items()},
        "parties": [
            {
                "counterparty": p["counterparty"],
                "current": float(p["current"]),
                "days_31_60": float(p["days_31_60"]),
                "days_61_90": float(p["days_61_90"]),
                "days_91_plus": float(p["days_91_plus"]),
                "total": float(p["total"]),
                "count": p["count"],
            }
            for p in listing[:80]
        ],
        "schedule_total": float(total),
        "gl_amount": float(gl),
        "difference": float(diff),
        "is_tied": abs(diff) < Decimal("0.02"),
        "row_count": len(rows),
    }


def _rollforward_schedule(opening_rows: list[dict], period_rows: list[dict], gl: Decimal) -> dict:
    opening = sum((r["amount"] for r in opening_rows), Decimal("0"))
    additions = Decimal("0")
    reductions = Decimal("0")
    for r in period_rows:
        if r["amount"] >= 0:
            additions += r["amount"]
        else:
            reductions += r["amount"]
    closing = opening + additions + reductions
    diff = closing - gl
    by_account: dict[str, dict] = {}
    for r in opening_rows + period_rows:
        key = r["account_code"]
        acc = by_account.setdefault(
            key,
            {
                "account_code": r["account_code"],
                "account_name": r["account_name"],
                "opening": Decimal("0"),
                "additions": Decimal("0"),
                "reductions": Decimal("0"),
                "closing": Decimal("0"),
            },
        )
    for r in opening_rows:
        acc = by_account[r["account_code"]]
        acc["opening"] += r["amount"]
        acc["closing"] += r["amount"]
    for r in period_rows:
        acc = by_account[r["account_code"]]
        if r["amount"] >= 0:
            acc["additions"] += r["amount"]
        else:
            acc["reductions"] += r["amount"]
        acc["closing"] += r["amount"]

    return {
        "kind": "rollforward",
        "opening": float(opening),
        "additions": float(additions),
        "reductions": float(reductions),
        "closing": float(closing),
        "gl_amount": float(gl),
        "difference": float(diff),
        "is_tied": abs(diff) < Decimal("0.02"),
        "accounts": [
            {
                "account_code": a["account_code"],
                "account_name": a["account_name"],
                "opening": float(a["opening"]),
                "additions": float(a["additions"]),
                "reductions": float(a["reductions"]),
                "closing": float(a["closing"]),
            }
            for a in by_account.values()
        ],
        "period_lines": [
            {
                "transaction_id": r["transaction_id"],
                "txn_date": r["txn_date"],
                "description": r["description"],
                "account_code": r["account_code"],
                "signed_amount": r["signed_amount"],
                "source_type": r["source_type"],
            }
            for r in period_rows[:80]
        ],
        "row_count": len(period_rows),
        "schedule_total": float(closing),
    }


def _ic_schedule(rows: list[dict], gl: Decimal) -> dict:
    matched = [r for r in rows if r["is_matched"]]
    unmatched = [r for r in rows if not r["is_matched"]]
    matched_total = sum((r["amount"] for r in matched), Decimal("0"))
    unmatched_total = sum((r["amount"] for r in unmatched), Decimal("0"))
    total = matched_total + unmatched_total
    diff = total - gl
    return {
        "kind": "intercompany",
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "matched_total": float(matched_total),
        "unmatched_total": float(unmatched_total),
        "schedule_total": float(total),
        "gl_amount": float(gl),
        "difference": float(diff),
        "is_tied": abs(diff) < Decimal("0.02") and len(unmatched) == 0,
        "unmatched": [
            {
                "transaction_id": r["transaction_id"],
                "txn_date": r["txn_date"],
                "description": r["description"],
                "entity_code": r["entity_code"],
                "signed_amount": r["signed_amount"],
            }
            for r in unmatched[:50]
        ],
        "matched": [
            {
                "transaction_id": r["transaction_id"],
                "txn_date": r["txn_date"],
                "description": r["description"],
                "entity_code": r["entity_code"],
                "signed_amount": r["signed_amount"],
            }
            for r in matched[:50]
        ],
        "row_count": len(rows),
    }


def _lead_schedule(rows: list[dict], gl: Decimal) -> dict:
    by_account: dict[str, dict] = {}
    for r in rows:
        acc = by_account.setdefault(
            r["account_code"],
            {"account_code": r["account_code"], "account_name": r["account_name"], "total": Decimal("0"), "count": 0},
        )
        acc["total"] += r["amount"]
        acc["count"] += 1
    total = sum((r["amount"] for r in rows), Decimal("0"))
    diff = total - gl
    return {
        "kind": "lead",
        "accounts": [
            {
                "account_code": a["account_code"],
                "account_name": a["account_name"],
                "total": float(a["total"]),
                "count": a["count"],
            }
            for a in sorted(by_account.values(), key=lambda x: abs(x["total"]), reverse=True)
        ],
        "lines": [
            {
                "transaction_id": r["transaction_id"],
                "txn_date": r["txn_date"],
                "description": r["description"],
                "account_code": r["account_code"],
                "signed_amount": r["signed_amount"],
                "source_type": r["source_type"],
            }
            for r in rows[:80]
        ],
        "schedule_total": float(total),
        "gl_amount": float(gl),
        "difference": float(diff),
        "is_tied": abs(diff) < Decimal("0.05"),
        "row_count": len(rows),
    }


def build_wp_schedule(
    db: Session,
    *,
    key: str,
    year: int,
    month: int,
    entity_id: int | None = None,
) -> dict | None:
    template = get_template(key)
    if not template or key == "cash":
        return None

    start = _month_start(year, month)
    end = _month_end(year, month)
    account_ids = set(_account_ids(db, template))
    ccy = _entity_currency(db, entity_id)
    line_code, gl = _gl_amount(db, template, year, month, entity_id, ccy)
    report_type = template.statement
    period_rows = _fact_rows(
        db,
        account_ids=account_ids,
        date_from=start if report_type != "balance_sheet" else date(2000, 1, 1),
        date_to=end,
        entity_id=entity_id,
        report_type=report_type,
        reporting_currency=ccy,
    )

    if key in AGING_KEYS:
        # Aging uses cumulative BS facts through period end
        body = _aging_schedule(period_rows, end, gl)
    elif key in IC_KEYS:
        body = _ic_schedule(period_rows, gl)
    elif key in ROLLFORWARD_KEYS:
        opening_rows = _fact_rows(
            db,
            account_ids=account_ids,
            date_from=date(2000, 1, 1),
            date_to=start - timedelta(days=1),
            entity_id=entity_id,
            report_type="balance_sheet",
            reporting_currency=ccy,
        )
        in_period = _fact_rows(
            db,
            account_ids=account_ids,
            date_from=start,
            date_to=end,
            entity_id=entity_id,
            report_type="balance_sheet",
            reporting_currency=ccy,
        )
        body = _rollforward_schedule(opening_rows, in_period, gl)
    else:
        body = _lead_schedule(period_rows, gl)

    gate_messages: list[str] = []
    if not body["is_tied"]:
        gate_messages.append(
            f"Schedule {body.get('schedule_total', 0):,.2f} ≠ statement {float(gl):,.2f}"
        )
    if key in IC_KEYS and body.get("unmatched_count"):
        gate_messages.append(f"{body['unmatched_count']} unmatched intercompany item(s)")

    can_prepare = body["is_tied"] or abs(Decimal(str(body.get("gl_amount") or 0))) < Decimal("0.02")
    # Zero GL with empty schedule is preparable (nothing to evidence)
    if abs(gl) < Decimal("0.02") and body.get("row_count", 0) == 0:
        can_prepare = True
        body["is_tied"] = True
        gate_messages = []

    return {
        **body,
        "key": key,
        "line_code": line_code,
        "period_label": f"{year}-{month:02d}",
        "period_end": end.isoformat(),
        "can_prepare": can_prepare,
        "can_review": can_prepare,
        "gate_messages": gate_messages,
    }
