"""Period-scoped Working Paper Binder — CaseWare-style engagement file."""

from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.cash_wp import build_cash_recon_schedule, cash_signoff_allowed
from app.engines.close_pack import month_close_overview
from app.engines.drilldown import drill_report_line
from app.engines.reporting import build_report
from app.engines.working_papers import get_template, list_templates
from app.models import DimAccount, WorkingPaperDocument
from app.schemas.reports import DrillRequest, ReportFilter


def period_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _primary_line_code(template) -> str:
    for code in template.line_codes:
        if code.startswith("BS_") or code in ("NI", "NET_INCOME", "TOT_REV", "TOT_EXP"):
            return code
    return template.line_codes[0] if template.line_codes else template.key.upper()


def _report_filters(template, year: int, month: int) -> ReportFilter:
    end = period_end(year, month)
    if template.statement == "balance_sheet":
        return ReportFilter(
            report_type="balance_sheet",
            as_of_date=end,
            year=year,
            month=month,
            scenario_id=1,
            reporting_currency="CAD",
            consolidate=True,
        )
    return ReportFilter(
        report_type="income_statement",
        period="ytd",
        year=year,
        month=month,
        date_to=end,
        as_of_date=end,
        scenario_id=1,
        reporting_currency="CAD",
        consolidate=True,
    )


def _load_docs(db: Session, year: int, month: int) -> dict[str, WorkingPaperDocument]:
    rows = db.scalars(
        select(WorkingPaperDocument).where(
            WorkingPaperDocument.period_year == year,
            WorkingPaperDocument.period_month == month,
        )
    ).all()
    return {r.template_key: r for r in rows}


def _checked_list(doc: WorkingPaperDocument | None) -> list[int]:
    if not doc or not doc.checked_json:
        return []
    try:
        data = json.loads(doc.checked_json)
        return [int(x) for x in data] if isinstance(data, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _derive_status(doc: WorkingPaperDocument | None, checked: list[int], procedure_count: int) -> str:
    if doc and doc.status in ("prepared", "reviewed"):
        # Keep reviewed even if checklist edits; clear reviewed only via explicit API
        if doc.reviewer:
            return "reviewed"
        if doc.preparer or doc.status == "prepared":
            return "prepared"
    if procedure_count and len(checked) >= procedure_count and (doc and doc.preparer):
        return "prepared"
    if checked or (doc and (doc.notes or doc.preparer)):
        return "open"
    return "open"


def _statement_amount_for_template(db: Session, template, year: int, month: int) -> tuple[str, Decimal, str | None]:
    """Return (line_code, amount, wp_ref from report)."""
    filters = _report_filters(template, year, month)
    report = build_report(db, filters)
    by_code = {line.line_code: line for line in report.lines}
    for code in template.line_codes:
        if code in by_code:
            line = by_code[code]
            return code, Decimal(line.amount), line.wp_ref
    # Fall back to summing account codes from BS/IS aggregates via matching lines
    accounts = {a.code: a for a in db.scalars(select(DimAccount)).all()}
    ids = [accounts[c].id for c in template.account_codes if c in accounts]
    if ids:
        matched = [line for line in report.lines if line.account_id in ids]
        if matched:
            total = sum((Decimal(m.amount) for m in matched), Decimal("0"))
            return matched[0].line_code, total, matched[0].wp_ref
    return _primary_line_code(template), Decimal("0"), template.wp_ref


def build_binder_index(db: Session, year: int, month: int) -> dict:
    docs = _load_docs(db, year, month)
    close = month_close_overview(db, year, month)
    cash_schedule = build_cash_recon_schedule(db, year, month)
    cash_close = {
        "banks_total": cash_schedule["banks_total"],
        "banks_locked": cash_schedule["banks_locked"],
        "banks_ready_to_lock": cash_schedule["banks_ready_or_locked"],
        "all_locked": cash_schedule["all_locked"],
        "blocking_total": sum(int(p.get("blocking_count") or 0) for p in close["packs"]),
    }

    # Cache reports per statement type
    report_cache: dict[str, object] = {}

    def amount_for(template) -> tuple[str, Decimal, str | None]:
        stmt = template.statement
        if stmt not in report_cache:
            report_cache[stmt] = build_report(db, _report_filters(template, year, month))
        report = report_cache[stmt]
        by_code = {line.line_code: line for line in report.lines}
        for code in template.line_codes:
            if code in by_code:
                line = by_code[code]
                return code, Decimal(line.amount), line.wp_ref or template.wp_ref
        return _primary_line_code(template), Decimal("0"), template.wp_ref

    documents = []

    for tmpl in list_templates():
        doc = docs.get(tmpl.key)
        checked = _checked_list(doc)
        if tmpl.key == "cash":
            # Merge recon-driven auto-checks into progress
            checked = sorted(set(checked) | set(cash_schedule["auto_checked"]))
        procedure_count = len(tmpl.procedures)
        done = len(checked)
        if doc and doc.status == "reviewed":
            status = "reviewed"
        elif doc and doc.status == "prepared":
            status = "prepared"
        else:
            status = _derive_status(doc, checked, procedure_count)

        line_code, amount, wp_ref = amount_for(tmpl)

        # Tie status: Cash uses bank recon proof; others use GL drill
        is_tied = None
        difference = None
        if tmpl.key == "cash":
            amount = Decimal(str(cash_schedule["gl_statement_amount"]))
            wp_ref = tmpl.wp_ref
            is_tied = cash_schedule["is_tied"]
            difference = float(cash_schedule["gl_vs_books_difference"])
            if not cash_schedule["all_bank_tied"]:
                # Prefer sum of open bank diffs when banks aren't tied
                difference = sum(
                    abs(float(b["difference"]))
                    for b in cash_schedule["banks"]
                    if b["difference"] is not None
                )
            close_status = cash_schedule["close_status"]
        else:
            close_status = None
            try:
                drill = drill_report_line(
                    db,
                    DrillRequest(
                        line_code=line_code,
                        filters=_report_filters(tmpl, year, month),
                    ),
                )
                is_tied = drill.is_tied
                difference = float(drill.difference)
                amount = Decimal(drill.statement_amount)
                if drill.wp_ref:
                    wp_ref = drill.wp_ref
            except ValueError:
                is_tied = True if amount == 0 else None

        documents.append(
            {
                "key": tmpl.key,
                "wp_ref": wp_ref or tmpl.wp_ref,
                "title": tmpl.title,
                "statement": tmpl.statement,
                "section": tmpl.section,
                "purpose": tmpl.purpose,
                "line_code": line_code,
                "statement_amount": float(amount),
                "currency": "CAD",
                "is_tied": is_tied,
                "difference": difference,
                "status": status,
                "procedure_count": procedure_count,
                "procedures_done": done,
                "procedure_pct": round((done / procedure_count) * 100) if procedure_count else 0,
                "preparer": doc.preparer if doc else None,
                "preparer_at": doc.preparer_at.isoformat() if doc and doc.preparer_at else None,
                "reviewer": doc.reviewer if doc else None,
                "reviewer_at": doc.reviewer_at.isoformat() if doc and doc.reviewer_at else None,
                "close_status": close_status,
                "href": f"/working-papers?year={year}&month={month}&key={tmpl.key}",
                "report_href": (
                    f"/reports?type={tmpl.statement}&year={year}&month={month}&line={line_code}"
                ),
                "close_href": f"/close?year={year}&month={month}" if tmpl.key == "cash" else None,
            }
        )

    summary = _fix_summary_counts(documents)
    summary["cash_close"] = cash_close
    return {
        "period_year": year,
        "period_month": month,
        "period_label": f"{year}-{month:02d}",
        "period_end": period_end(year, month).isoformat(),
        "documents": documents,
        "summary": summary,
        "cash_schedule": cash_schedule,
    }


def _fix_summary_counts(documents: list[dict]) -> dict:
    total = len(documents)
    reviewed = sum(1 for d in documents if d["status"] == "reviewed")
    prepared = sum(1 for d in documents if d["status"] in ("prepared", "reviewed"))
    open_count = total - prepared
    untied = sum(1 for d in documents if d.get("is_tied") is False)
    return {
        "total": total,
        "prepared": prepared,
        "reviewed": reviewed,
        "open": open_count,
        "untied": untied,
    }


def build_binder(db: Session, year: int, month: int) -> dict:
    return build_binder_index(db, year, month)


def get_binder_document(db: Session, year: int, month: int, key: str) -> dict:
    tmpl = get_template(key)
    if not tmpl:
        raise ValueError(f"Unknown working paper '{key}'")

    binder = build_binder(db, year, month)
    index_row = next((d for d in binder["documents"] if d["key"] == key), None)
    if not index_row:
        raise ValueError(f"Working paper '{key}' not in binder")

    docs = _load_docs(db, year, month)
    doc = docs.get(key)
    checked = _checked_list(doc)
    cash_schedule = binder.get("cash_schedule") if key == "cash" else None
    if cash_schedule:
        checked = sorted(set(checked) | set(cash_schedule["auto_checked"]))

    filters = _report_filters(tmpl, year, month)
    line_code = index_row["line_code"]
    drill_payload = None
    # For cash, drill is secondary — bank schedule is the primary evidence
    if key != "cash":
        try:
            drill = drill_report_line(
                db,
                DrillRequest(line_code=line_code, filters=filters),
            )
            drill_payload = {
                "line_code": drill.line_code,
                "line_label": drill.line_label,
                "wp_ref": drill.wp_ref,
                "statement_amount": float(drill.statement_amount),
                "detail_total": float(drill.detail_total),
                "difference": float(drill.difference),
                "is_tied": drill.is_tied,
                "row_count": drill.row_count,
                "period_label": drill.period_label,
                "currency": drill.currency,
                "lines": [
                    {
                        "transaction_id": r.transaction_id,
                        "txn_date": r.txn_date.isoformat(),
                        "description": r.description,
                        "entity_code": r.entity_code,
                        "account_code": r.account_code,
                        "account_name": r.account_name,
                        "signed_amount": float(r.signed_amount),
                        "currency": r.currency,
                        "is_reconciled": r.is_reconciled,
                    }
                    for r in drill.lines[:200]
                ],
            }
        except ValueError:
            pass

    return {
        **index_row,
        "period_year": year,
        "period_month": month,
        "period_label": binder["period_label"],
        "period_end": binder["period_end"],
        "objective": tmpl.objective,
        "tie_out": tmpl.tie_out,
        "procedures": list(tmpl.procedures),
        "evidence": list(tmpl.evidence),
        "checked": checked,
        "procedures_done": len(checked),
        "procedure_pct": round((len(checked) / len(tmpl.procedures)) * 100) if tmpl.procedures else 0,
        "notes": doc.notes if doc else None,
        "drill": drill_payload,
        "cash_schedule": cash_schedule,
        "can_prepare": cash_schedule["can_prepare"] if cash_schedule else True,
        "can_review": cash_schedule["can_review"] if cash_schedule else True,
        "gate_messages": cash_schedule["gate_messages"] if cash_schedule else [],
        "filters": filters.model_dump(mode="json"),
    }


def upsert_binder_document(
    db: Session,
    *,
    year: int,
    month: int,
    key: str,
    checked: list[int] | None = None,
    notes: str | None = None,
    preparer: str | None = None,
    reviewer: str | None = None,
    status: str | None = None,
    actor: str = "controller",
) -> dict:
    tmpl = get_template(key)
    if not tmpl:
        raise ValueError(f"Unknown working paper '{key}'")

    doc = db.scalar(
        select(WorkingPaperDocument).where(
            WorkingPaperDocument.period_year == year,
            WorkingPaperDocument.period_month == month,
            WorkingPaperDocument.template_key == key,
        )
    )
    if not doc:
        doc = WorkingPaperDocument(
            period_year=year,
            period_month=month,
            template_key=key,
            status="open",
        )
        db.add(doc)

    now = datetime.utcnow()
    cash_schedule = build_cash_recon_schedule(db, year, month) if key == "cash" else None

    if checked is not None:
        # validate indices
        max_idx = len(tmpl.procedures) - 1
        clean = sorted({int(i) for i in checked if 0 <= int(i) <= max_idx})
        if cash_schedule:
            clean = sorted(set(clean) | set(cash_schedule["auto_checked"]))
        doc.checked_json = json.dumps(clean)
    elif cash_schedule:
        # Persist recon-driven auto-checks even when only signing off
        existing = _checked_list(doc)
        doc.checked_json = json.dumps(sorted(set(existing) | set(cash_schedule["auto_checked"])))

    if notes is not None:
        doc.notes = notes

    # Resolve intended preparer/reviewer before gating status changes
    next_preparer = doc.preparer
    next_reviewer = doc.reviewer
    if preparer is not None:
        next_preparer = preparer.strip() or None
    if reviewer is not None:
        next_reviewer = reviewer.strip() or None

    intended_status = status
    if intended_status is None:
        if reviewer is not None and next_reviewer:
            intended_status = "reviewed"
        elif preparer is not None and next_preparer and doc.status == "open":
            intended_status = "prepared"

    if key == "cash" and intended_status in ("prepared", "reviewed"):
        cash_signoff_allowed(
            cash_schedule or build_cash_recon_schedule(db, year, month),
            status=intended_status,
            preparer=next_preparer or (actor if intended_status == "prepared" else doc.preparer),
            reviewer=next_reviewer or (actor if intended_status == "reviewed" else doc.reviewer),
        )

    if preparer is not None:
        doc.preparer = next_preparer
        doc.preparer_at = now if doc.preparer else None
        if doc.preparer and doc.status == "open":
            doc.status = "prepared"
    if reviewer is not None:
        doc.reviewer = next_reviewer
        doc.reviewer_at = now if doc.reviewer else None
        if doc.reviewer:
            doc.status = "reviewed"
        elif doc.preparer:
            doc.status = "prepared"
        else:
            doc.status = "open"
    if status is not None:
        if status not in ("open", "prepared", "reviewed"):
            raise ValueError("status must be open|prepared|reviewed")
        doc.status = status
        if status == "prepared" and not doc.preparer:
            doc.preparer = actor
            doc.preparer_at = now
        if status == "reviewed" and not doc.reviewer:
            doc.reviewer = actor
            doc.reviewer_at = now
        if status == "open":
            doc.reviewer = None
            doc.reviewer_at = None

    doc.updated_at = now
    doc.updated_by = actor
    db.flush()
    return get_binder_document(db, year, month, key)
