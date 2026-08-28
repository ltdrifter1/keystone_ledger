"""Bootstrap WBC CAN + USA entities, chart of accounts, banks, and report layouts from mapping files."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.working_papers import balance_sheet_layout_spec
from app.models import (
    BankAccount,
    DimAccount,
    DimDepartment,
    DimEntity,
    DimFx,
    DimReportLayout,
    DimScenario,
)

SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "sample_data"
MAPPINGS = SAMPLE_ROOT / "mappings"


def _load_json(name: str) -> dict:
    path = MAPPINGS / name
    if not path.exists():
        raise FileNotFoundError(f"Missing mapping file: {path}")
    return json.loads(path.read_text())


def bootstrap_wbc_dimensions(db: Session) -> dict:
    """Create CAN/USA world from mapping JSON. Caller commits."""
    coa = _load_json("wbc_chart_of_accounts.json")
    entities_cfg = _load_json("wbc_entities_banks.json")

    # Scenarios
    scenarios = []
    for code, name, stype in [
        ("ACTUAL", "Actual", "actual"),
        ("BUDGET", "Budget", "budget"),
        ("FORECAST", "Forecast", "forecast"),
        ("PRIOR", "Prior Year", "prior_year"),
    ]:
        scenarios.append(DimScenario(code=code, name=name, scenario_type=stype))
    db.add_all(scenarios)
    db.flush()

    # Shared CoA from synoptic header + cash bank children + clearing stubs
    accounts: list[DimAccount] = []
    sort = 10
    for row in coa["accounts"]:
        accounts.append(
            DimAccount(
                code=row["code"],
                name=row["name"],
                account_type=row["account_type"],
                statement=row["statement"],
                normal_balance=row["normal_balance"],
                is_cash=bool(row.get("is_cash")),
                is_intercompany=bool(row.get("is_intercompany")),
                cash_flow_section=row.get("cash_flow_section"),
                sort_order=sort,
            )
        )
        sort += 10
    db.add_all(accounts)
    db.flush()
    by_code = {a.code: a for a in accounts}

    parent_cash = by_code.get("1000")
    for row in coa.get("cash_bank_accounts") or []:
        if row["code"] in by_code:
            continue
        acct = DimAccount(
            code=row["code"],
            name=row["name"],
            account_type="asset",
            statement="balance_sheet",
            normal_balance="debit",
            parent_account_id=parent_cash.id if parent_cash else None,
            is_cash=True,
            sort_order=sort,
        )
        db.add(acct)
        accounts.append(acct)
        sort += 10
    db.flush()

    for row in coa.get("clearing_accounts") or []:
        if row["code"] in by_code or any(a.code == row["code"] for a in accounts):
            continue
        acct = DimAccount(
            code=row["code"],
            name=row["name"],
            account_type=row["account_type"],
            statement=row["statement"],
            normal_balance=row["normal_balance"],
            sort_order=sort,
        )
        db.add(acct)
        accounts.append(acct)
        sort += 10
    db.flush()
    by_code = {a.code: a for a in db.scalars(select(DimAccount)).all()}

    # Entities + departments + banks (strictly separate — no parent consolidation)
    entity_map: dict[str, DimEntity] = {}
    bank_map: dict[str, BankAccount] = {}
    for ent_cfg in entities_cfg["entities"]:
        ent = DimEntity(
            code=ent_cfg["code"],
            name=ent_cfg["name"],
            country=ent_cfg["country"],
            functional_currency=ent_cfg["functional_currency"],
            consolidation_method=ent_cfg.get("consolidation_method") or "none",
            fiscal_year_end_month=int(ent_cfg.get("fiscal_year_end_month") or 7),
            parent_entity_id=None,
        )
        db.add(ent)
        db.flush()
        entity_map[ent.code] = ent

        for dept in ent_cfg.get("departments") or []:
            # Department codes are globally unique — prefix USA codes already distinct
            db.add(
                DimDepartment(
                    code=dept["code"],
                    name=dept["name"],
                    entity_id=ent.id,
                )
            )

        for bank_cfg in ent_cfg.get("banks") or []:
            gl = by_code.get(bank_cfg["gl_code"]) or by_code.get("1000")
            bank = BankAccount(
                entity_id=ent.id,
                name=bank_cfg["name"],
                account_number=str(bank_cfg["account_number"]),
                currency=bank_cfg["currency"],
                institution=bank_cfg.get("institution") or "WBC",
                gl_account_id=gl.id if gl else None,
                opening_balance=Decimal("0"),
                is_active=True,
            )
            db.add(bank)
            db.flush()
            bank_map[f"{ent.code}:{bank_cfg['account_number']}"] = bank

    db.flush()

    # FX USD→CAD covering synoptic history (2025-07 through today+margin)
    start = date(2025, 7, 1)
    end = date.today() + timedelta(days=60)
    d = start
    while d <= end:
        for rate_type, rate in (("spot", "1.3700"), ("average", "1.3650"), ("closing", "1.3720")):
            db.add(
                DimFx(
                    from_currency="USD",
                    to_currency="CAD",
                    rate_date=d,
                    rate=Decimal(rate),
                    rate_type=rate_type,
                )
            )
        d += timedelta(days=7)

    _seed_report_layouts(db, by_code)

    return {
        "entities": {c: e.id for c, e in entity_map.items()},
        "banks": {k: b.id for k, b in bank_map.items()},
        "accounts": len(by_code),
    }


def _seed_report_layouts(db: Session, by_code: dict[str, DimAccount]) -> None:
    """Income statement + balance sheet layouts aligned to WBC synoptic CoA."""

    def acct(*codes: str) -> int | None:
        for c in codes:
            if c in by_code:
                return by_code[c].id
        return None

    is_layout = [
        ("REV", "Revenue", "revenue", None, None, None, 0, True, False, 10),
        ("REV_PROD", "Product Sales", "revenue", acct("4000"), None, None, 1, False, False, 20),
        ("REV_SVC", "Service Revenue", "revenue", acct("4100"), None, None, 1, False, False, 30),
        ("REV_SHIP", "Shipping Revenue", "revenue", acct("4200"), None, None, 1, False, False, 40),
        ("REV_RET", "Returns / Discounts", "revenue", acct("4300"), None, None, 1, False, False, 50),
        ("TOT_REV", "Total Revenue", "revenue", None, None, "REV_PROD + REV_SVC + REV_SHIP + REV_RET", 0, True, True, 60),
        ("COGS", "Cost of Goods Sold", "expense", None, None, None, 0, True, False, 70),
        ("COGS_MAT", "Materials", "expense", acct("5000"), None, None, 1, False, False, 80),
        ("COGS_FRT", "Freight In", "expense", acct("5100"), None, None, 1, False, False, 90),
        ("COGS_LAB", "Direct Labour", "expense", acct("5200"), None, None, 1, False, False, 100),
        ("COGS_ADJ", "Inventory Adjustments", "expense", acct("5300"), None, None, 1, False, False, 110),
        ("TOT_COGS", "Total COGS", "expense", None, None, "COGS_MAT + COGS_FRT + COGS_LAB + COGS_ADJ", 0, True, True, 120),
        ("GP", "Gross Profit", "totals", None, None, "TOT_REV - TOT_COGS", 0, True, True, 130),
        ("OPEX", "Operating Expenses", "expense", None, None, None, 0, True, False, 140),
        ("EXP_MKT", "Marketing", "expense", acct("6000"), None, None, 1, False, False, 150),
        ("EXP_FRTO", "Freight Out", "expense", acct("6100"), None, None, 1, False, False, 160),
        ("EXP_SFT", "Software", "expense", acct("6200"), None, None, 1, False, False, 170),
        ("EXP_OCC", "Occupancy", "expense", acct("6300"), None, None, 1, False, False, 180),
        ("EXP_PROF", "Professional Fees", "expense", acct("6400"), None, None, 1, False, False, 190),
        ("EXP_ADM", "Office / Admin", "expense", acct("6500"), None, None, 1, False, False, 200),
        ("EXP_OTH", "Other OpEx", "expense", acct("6600"), None, None, 1, False, False, 210),
        ("EXP_DEP", "Depreciation", "expense", acct("7000"), None, None, 1, False, False, 220),
        (
            "TOT_OPEX",
            "Total Operating Expenses",
            "expense",
            None,
            None,
            "EXP_MKT + EXP_FRTO + EXP_SFT + EXP_OCC + EXP_PROF + EXP_ADM + EXP_OTH + EXP_DEP",
            0,
            True,
            True,
            230,
        ),
        ("TOT_EXP", "Total Expenses", "expense", None, None, "TOT_COGS + TOT_OPEX", 0, True, True, 235),
        ("OI", "Operating Income", "totals", None, None, "GP - TOT_OPEX", 0, True, True, 240),
        ("BTL", "Below The Line", "expense", None, None, None, 0, True, False, 250),
        ("BTL_FXR", "Realized FX", "expense", acct("8000"), None, None, 1, False, False, 260),
        ("BTL_FXU", "Unrealized FX", "expense", acct("8100"), None, None, 1, False, False, 270),
        ("BTL_INTI", "Interest Income", "revenue", acct("8200"), None, None, 1, False, False, 280),
        ("BTL_INTE", "Interest Expense", "expense", acct("8300"), None, None, 1, False, False, 290),
        ("BTL_TAX", "Income Tax", "expense", acct("8400"), None, None, 1, False, False, 300),
        (
            "TOT_BTL",
            "Total Below The Line",
            "expense",
            None,
            None,
            "BTL_FXR + BTL_FXU - BTL_INTI + BTL_INTE + BTL_TAX",
            0,
            True,
            True,
            310,
        ),
        ("NI", "Net Income", "totals", None, None, "OI - TOT_BTL", 0, True, True, 320),
    ]
    for code, label, section, acct_id, type_f, formula, indent, bold, total, order in is_layout:
        db.add(
            DimReportLayout(
                report_type="income_statement",
                section=section,
                line_code=code,
                line_label=label,
                account_id=acct_id,
                account_type_filter=type_f,
                calc_formula=formula,
                indent_level=indent,
                is_bold=bold,
                is_total=total,
                sort_order=order,
                notes="wp:pnl_analysis" if code == "NI" else None,
            )
        )

    bs_layout = balance_sheet_layout_spec(by_code)
    for code, label, section, acct_id, type_f, formula, indent, bold, total, order in bs_layout:
        db.add(
            DimReportLayout(
                report_type="balance_sheet",
                section=section,
                line_code=code,
                line_label=label,
                account_id=acct_id,
                account_type_filter=type_f,
                calc_formula=formula,
                indent_level=indent,
                is_bold=bold,
                is_total=total,
                sort_order=order,
                notes="wp:pnl_analysis" if code == "BS_CURRENT_EARNINGS" else None,
            )
        )
