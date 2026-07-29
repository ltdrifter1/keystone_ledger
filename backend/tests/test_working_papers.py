from app.database import SessionLocal, init_db
from app.engines.drilldown import drill_report_line
from app.engines.reporting import build_report
from app.engines.working_papers import (
    ensure_working_paper_foundation,
    find_template,
    list_templates,
)
from app.schemas.reports import DrillRequest, ReportFilter
from app.services.seed import seed_if_empty


def setup_module(_module):
    init_db()
    db = SessionLocal()
    seed_if_empty(db)
    ensure_working_paper_foundation(db)
    db.close()


def test_all_main_section_templates_exist():
    keys = {t.key for t in list_templates()}
    expected = {
        "cash",
        "ar",
        "prepaid",
        "inventory",
        "interco",
        "shareholder_loan",
        "taxes_payable",
        "ap",
        "unearned_revenue",
        "equity",
        "pnl_analysis",
    }
    assert expected <= keys
    assert len(list_templates()) == 11


def test_template_lookup_by_line_and_account():
    assert find_template(line_code="BS_CASH").key == "cash"
    assert find_template(account_codes=["2000"]).key == "ap"
    assert find_template(line_code="NI").key == "pnl_analysis"
    assert find_template(line_code="BS_SH_LOAN").wp_ref == "D.5"


def test_balance_sheet_uses_wp_refs():
    db = SessionLocal()
    try:
        report = build_report(
            db,
            ReportFilter(report_type="balance_sheet", scenario_id=1, reporting_currency="CAD"),
        )
        by_code = {line.line_code: line for line in report.lines}
        assert "BS_CASH" in by_code
        assert by_code["BS_CASH"].wp_ref == "C.1"
        assert by_code["BS_AR"].wp_ref == "C.2"
        assert by_code["BS_AP"].wp_ref == "D.1"
        assert by_code["BS_TAX"].wp_ref == "D.2"
        assert by_code["BS_EQUITY"].wp_ref == "E.1"
    finally:
        db.close()


def test_drill_attaches_cash_template():
    db = SessionLocal()
    try:
        out = drill_report_line(
            db,
            DrillRequest(
                line_code="BS_CASH",
                filters=ReportFilter(
                    report_type="balance_sheet",
                    scenario_id=1,
                    reporting_currency="CAD",
                ),
            ),
        )
        assert out.wp_ref == "C.1"
        assert out.template is not None
        assert out.template.key == "cash"
        assert len(out.template.procedures) >= 4
        assert "Tie" in out.template.tie_out or "tie" in out.template.tie_out.lower() or "GL" in out.template.tie_out
    finally:
        db.close()


def test_api_lists_working_papers():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    res = client.get("/api/working-papers")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 11
    assert body["templates"][0]["wp_ref"]
    cash = client.get("/api/working-papers/cash")
    assert cash.status_code == 200
    assert cash.json()["title"] == "Cash"
