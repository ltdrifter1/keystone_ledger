"""Basic working-paper templates for each main statement section.

Templates are code-defined so every environment gets a consistent CaseWare-style
pack without relying on DB migrations. They attach to report lines / drills by
line_code and account_code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DimAccount, DimReportLayout


@dataclass(frozen=True)
class WorkingPaperTemplate:
    key: str
    wp_ref: str
    title: str
    statement: str  # balance_sheet | income_statement
    section: str  # asset | liability | equity | pnl
    purpose: str
    objective: str
    tie_out: str
    procedures: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    line_codes: list[str] = field(default_factory=list)
    account_codes: list[str] = field(default_factory=list)
    sort_order: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


TEMPLATES: list[WorkingPaperTemplate] = [
    WorkingPaperTemplate(
        key="cash",
        wp_ref="C.1",
        title="Cash",
        statement="balance_sheet",
        section="asset",
        purpose="Prove cash & bank balances to the statement and bank reconciliations.",
        objective="Agree GL cash to reconciled bank balances; investigate uncleared items and FX.",
        tie_out="GL cash (by bank/currency) = sum of reconciled statement ending balances ± outstanding items.",
        procedures=[
            "Pull cash GL balance by bank account and currency as of period end.",
            "Obtain bank statement ending balance for each account.",
            "Complete / review bank reconciliation: beginning + cleared = book; book vs statement = difference.",
            "Investigate uncleared deposits > cut-off and outstanding cheques older than policy threshold.",
            "Confirm FX translation of foreign-currency accounts to reporting currency (closing rate).",
            "Agree total cash to Balance Sheet cash line and Close Pack status (locked where required).",
        ],
        evidence=[
            "Bank statements / CSV imports",
            "Bank reconciliations (Close Pack / Reconciliation workspace)",
            "GL cash detail / transaction drill",
            "FX closing rates",
        ],
        line_codes=["BS_CASH", "1000"],
        account_codes=["1000"],
        sort_order=10,
    ),
    WorkingPaperTemplate(
        key="ar",
        wp_ref="C.2",
        title="Accounts Receivable",
        statement="balance_sheet",
        section="asset",
        purpose="Support trade receivables and recoverability at period end.",
        objective="Agree AR subledger/GL; assess collectibility and cut-off.",
        tie_out="AR GL = aged AR listing total; net AR = gross − allowance (if any).",
        procedures=[
            "Agree AR GL to aged receivables listing (or transaction detail by customer/counterparty).",
            "Review aging for overdue balances and subsequent collections.",
            "Test sales cut-off around period end (shipments / revenue vs cash receipts).",
            "Identify credit balances in AR and reclass if material.",
            "Document allowance / bad-debt assessment (or note N/A if not applied).",
            "Agree AR line to Balance Sheet.",
        ],
        evidence=[
            "AR aging / customer listing",
            "Subsequent cash receipts",
            "Sales invoices / revenue detail",
            "Allowance calculation (if used)",
        ],
        line_codes=["BS_AR", "1100"],
        account_codes=["1100"],
        sort_order=20,
    ),
    WorkingPaperTemplate(
        key="prepaid",
        wp_ref="C.3",
        title="Prepaid Expenses",
        statement="balance_sheet",
        section="asset",
        purpose="Confirm prepaid balances represent future economic benefit.",
        objective="Roll forward prepaids and expense the correct period portion.",
        tie_out="Opening prepaid + additions − amortization = closing prepaid; expense hits P&L.",
        procedures=[
            "Prepare prepaid rollforward: opening, additions, amortization, closing.",
            "Vouch material additions to invoices / contracts and amortization schedule.",
            "Confirm remaining term extends beyond period end.",
            "Expense current-period amortization to the correct P&L account.",
            "Agree closing balance to Balance Sheet prepaid line.",
        ],
        evidence=[
            "Prepaid schedule / rollforward",
            "Vendor invoices & contracts",
            "Amortization calculation",
        ],
        line_codes=["BS_PREPAID", "1300"],
        account_codes=["1300"],
        sort_order=30,
    ),
    WorkingPaperTemplate(
        key="inventory",
        wp_ref="C.4",
        title="Inventory",
        statement="balance_sheet",
        section="asset",
        purpose="Support inventory existence, completeness, and valuation.",
        objective="Agree inventory listing to GL; assess NRV and cut-off.",
        tie_out="Inventory GL = detailed inventory listing; adjust for NRV / obsolescence.",
        procedures=[
            "Agree inventory subledger / count sheets to GL.",
            "Review count procedures or perpetual roll if no physical count this period.",
            "Test purchases / COGS cut-off around period end.",
            "Assess slow-moving / obsolete items and NRV write-downs.",
            "Agree inventory to Balance Sheet and related COGS impact on P&L.",
        ],
        evidence=[
            "Inventory listing / count sheets",
            "Costing / valuation report",
            "NRV / obsolescence analysis",
            "Purchase & COGS cut-off samples",
        ],
        line_codes=["BS_INV", "1200"],
        account_codes=["1200"],
        sort_order=40,
    ),
    WorkingPaperTemplate(
        key="interco",
        wp_ref="D.4",
        title="Intercompany",
        statement="balance_sheet",
        section="liability",
        purpose="Prove intercompany balances eliminate / match across entities (CAN vs USA kept separate).",
        objective="Match IC receivables/payables and transfers; clear unmatched items.",
        tie_out="Entity A IC asset = Entity B IC liability (same FX basis); unmatched = exception.",
        procedures=[
            "List IC balances by counter-entity and currency.",
            "Run / review auto-match for IC transfers; investigate unmatched pairs.",
            "Confirm mirror balances (AR/AP or transfer legs) agree within FX tolerance.",
            "Document timing differences and resolve before consolidation.",
            "Agree IC lines to Balance Sheet — do not blend CAN and USA without an elimination pack.",
        ],
        evidence=[
            "IC balance listing by entity",
            "Matched / unmatched IC transfer report",
            "FX rates used for IC",
        ],
        line_codes=["BS_IC", "2100"],
        account_codes=["2100"],
        sort_order=80,
    ),
    WorkingPaperTemplate(
        key="shareholder_loan",
        wp_ref="D.5",
        title="Shareholder Loan",
        statement="balance_sheet",
        section="liability",
        purpose="Support due to/from shareholder balances and classification.",
        objective="Roll forward shareholder loan; confirm classification (current vs equity-like).",
        tie_out="Opening + advances − repayments ± interest = closing shareholder loan.",
        procedures=[
            "Prepare shareholder loan rollforward for the period.",
            "Vouch material advances and repayments to bank evidence.",
            "Confirm interest (if any) accrued per agreement.",
            "Assess presentation: liability vs equity contribution / draw.",
            "Agree balance to Balance Sheet shareholder loan line.",
        ],
        evidence=[
            "Shareholder loan agreement / board minutes",
            "Rollforward schedule",
            "Bank evidence of advances/repayments",
        ],
        line_codes=["BS_SH_LOAN", "2400"],
        account_codes=["2400"],
        sort_order=90,
    ),
    WorkingPaperTemplate(
        key="bank_transfers",
        wp_ref="D.6",
        title="Due to / from other bank accounts",
        statement="balance_sheet",
        section="liability",
        purpose="Park cashbook GL 1000 sweeps whose contra bank is not on these books.",
        objective="Agree Cash Sweep In/Out/Visa (GL 1000) to the due-to-other-banks liability; do not double-count as cash.",
        tie_out="BS due-to-other-banks = GL 1000 (cashbook); BS cash = reconciled bank book, not GL 1000.",
        procedures=[
            "List GL 1000 Cash Sweep In / Out / Visa activity through period end.",
            "Confirm these are transfers to/from bank accounts not imported on this entity.",
            "Agree the net to the Balance Sheet due-to-other-banks line.",
            "Agree cash to the bank book (opening + activity), not to GL 1000.",
        ],
        evidence=[
            "Synoptic cashbook GL 1000 columns",
            "Bank book / reconciliation (C.1)",
        ],
        line_codes=["BS_CASH_XFER"],
        account_codes=[],
        sort_order=95,
    ),
    WorkingPaperTemplate(
        key="taxes_payable",
        wp_ref="D.2",
        title="Taxes Payable",
        statement="balance_sheet",
        section="liability",
        purpose="Support income / sales / payroll tax liabilities at period end.",
        objective="Agree tax payable to filings, remittances, and provision.",
        tie_out="Opening + provision / assessments − payments / remittances = closing payable.",
        procedures=[
            "Roll forward each tax payable (income tax, GST/HST/sales, payroll).",
            "Agree provisions to tax computation / payroll registers.",
            "Vouch remittances to bank and filing confirmations.",
            "Review notices of assessment / credits for unrecorded liabilities.",
            "Agree totals to Balance Sheet taxes payable line.",
        ],
        evidence=[
            "Tax provision / computation",
            "Filing confirmations & remittance receipts",
            "Payroll tax registers",
            "Notices of assessment",
        ],
        line_codes=["BS_TAX", "2300"],
        account_codes=["2300"],
        sort_order=60,
    ),
    WorkingPaperTemplate(
        key="ap",
        wp_ref="D.1",
        title="Accounts Payable",
        statement="balance_sheet",
        section="liability",
        purpose="Support trade payables completeness and cut-off.",
        objective="Agree AP GL to vendor listing; test unrecorded liabilities.",
        tie_out="AP GL = aged AP listing; search for unrecorded liabilities in subsequent payments.",
        procedures=[
            "Agree AP GL to aged payables / vendor listing.",
            "Review debit balances in AP and reclass if material.",
            "Perform search for unrecorded liabilities (subsequent disbursements / unmatched invoices).",
            "Test purchase cut-off around period end.",
            "Agree AP to Balance Sheet.",
        ],
        evidence=[
            "AP aging / vendor listing",
            "Subsequent payment testing",
            "Unmatched invoices / accruals",
        ],
        line_codes=["BS_AP", "2000"],
        account_codes=["2000"],
        sort_order=50,
    ),
    WorkingPaperTemplate(
        key="unearned_revenue",
        wp_ref="D.3",
        title="Unearned Revenue",
        statement="balance_sheet",
        section="liability",
        purpose="Support deferred / unearned revenue balances at period end.",
        objective="Agree unearned revenue to contract / deferred schedule; release earned amounts.",
        tie_out="Opening + billings − revenue recognized = closing unearned.",
        procedures=[
            "Obtain deferred revenue / contract liability schedule by customer.",
            "Roll forward opening, additions, recognized revenue, closing.",
            "Test material releases to shipping / service evidence.",
            "Confirm classification current vs long-term if applicable.",
            "Agree balance to Balance Sheet unearned revenue line.",
        ],
        evidence=[
            "Deferred revenue schedule",
            "Customer contracts / SOWs",
            "Revenue recognition support",
        ],
        line_codes=["BS_UNEARNED", "2200"],
        account_codes=["2200"],
        sort_order=70,
    ),
    WorkingPaperTemplate(
        key="equity",
        wp_ref="E.1",
        title="Equity",
        statement="balance_sheet",
        section="equity",
        purpose="Support equity continuity: capital, draws, and retained earnings.",
        objective="Roll forward equity components and agree to statement of equity / BS.",
        tie_out="Opening equity + contributions − draws ± OCI + NI = closing equity.",
        procedures=[
            "Prepare equity rollforward (capital, draws/distributions, retained earnings).",
            "Agree net income / loss bridge from P&L working paper.",
            "Vouch contributions and owner draws to bank evidence / resolutions.",
            "Confirm no unauthorized equity movements.",
            "Agree equity total to Balance Sheet.",
        ],
        evidence=[
            "Equity rollforward",
            "P&L / NI tie-out",
            "Bank evidence of contributions & draws",
            "Share / ownership register (if applicable)",
        ],
        line_codes=["BS_EQUITY", "BS_DRAWS", "3000", "3100"],
        account_codes=["3000", "3100"],
        sort_order=100,
    ),
    WorkingPaperTemplate(
        key="pnl_analysis",
        wp_ref="Z.1",
        title="P&L Analysis",
        statement="income_statement",
        section="pnl",
        purpose="Explain period performance and tie Net Income to the statements.",
        objective="Analyze revenue & expense variances; agree NI to equity bridge.",
        tie_out="Total revenue − total expenses = Net Income; NI feeds equity retained earnings.",
        procedures=[
            "Agree Income Statement totals (revenue, expenses, NI) to GL / drill detail.",
            "Review material revenue streams and expense categories vs prior / budget.",
            "Investigate unusual items, large uncategorized activity, and reclasses.",
            "Confirm department / entity filters used for management vs statutory view — keep CAN and USA separate.",
            "Bridge Net Income to equity rollforward (retained earnings).",
            "Document key drivers and residual questions for review.",
        ],
        evidence=[
            "Income Statement with drill-through",
            "Budget / prior-period comparison",
            "Variance commentary",
            "Equity bridge schedule",
        ],
        line_codes=["NI", "NET_INCOME", "TOT_REV", "TOT_EXP", "REV", "EXP", "BS_CURRENT_EARNINGS"],
        account_codes=[
            "4000",
            "4100",
            "4200",
            "4300",
            "5000",
            "5100",
            "5200",
            "5300",
            "6000",
            "6100",
            "6200",
            "6300",
            "6400",
            "6500",
            "6600",
            "7000",
        ],
        sort_order=110,
    ),
]


_BY_KEY = {t.key: t for t in TEMPLATES}


def list_templates() -> list[WorkingPaperTemplate]:
    return sorted(TEMPLATES, key=lambda t: t.sort_order)


def get_template(key: str) -> WorkingPaperTemplate | None:
    return _BY_KEY.get(key)


def find_template(
    *,
    line_code: str | None = None,
    account_codes: list[str] | None = None,
    wp_ref: str | None = None,
) -> WorkingPaperTemplate | None:
    if line_code:
        for tmpl in TEMPLATES:
            if line_code in tmpl.line_codes:
                return tmpl
    if wp_ref:
        for tmpl in TEMPLATES:
            if tmpl.wp_ref == wp_ref:
                return tmpl
    if account_codes:
        codes = set(account_codes)
        # Prefer exact single-account section templates over broad P&L
        ranked = sorted(TEMPLATES, key=lambda t: (0 if t.key != "pnl_analysis" else 1, t.sort_order))
        for tmpl in ranked:
            if codes & set(tmpl.account_codes):
                return tmpl
    return None


def template_for_report_line(
    *,
    line_code: str,
    account_codes: list[str] | None = None,
    wp_ref: str | None = None,
) -> WorkingPaperTemplate | None:
    return find_template(line_code=line_code, account_codes=account_codes, wp_ref=wp_ref)


# --- CoA / BS layout foundation -------------------------------------------------

_REQUIRED_ACCOUNTS = [
    ("1000", "Cash & Banks", "asset", "balance_sheet", "debit", True, False, 10),
    ("1100", "Accounts Receivable", "asset", "balance_sheet", "debit", False, False, 20),
    ("1200", "Inventory", "asset", "balance_sheet", "debit", False, False, 25),
    ("1300", "Prepaid Expenses", "asset", "balance_sheet", "debit", False, False, 28),
    ("1400", "Property & Equipment", "asset", "balance_sheet", "debit", False, False, 30),
    ("2000", "Accounts Payable", "liability", "balance_sheet", "credit", False, False, 40),
    ("2100", "Due to / From Intercompany", "liability", "balance_sheet", "credit", False, True, 50),
    ("2200", "Unearned Revenue", "liability", "balance_sheet", "credit", False, False, 55),
    ("2300", "Taxes Payable", "liability", "balance_sheet", "credit", False, False, 58),
    ("2400", "Shareholder Loan", "liability", "balance_sheet", "credit", False, False, 65),
    ("3000", "Retained Earnings", "equity", "balance_sheet", "credit", False, False, 70),
    ("3100", "Owner Contributions / Draws", "equity", "balance_sheet", "credit", False, False, 80),
]


def balance_sheet_layout_spec(by_code: dict[str, DimAccount]) -> list[tuple]:
    """Canonical BS rows: current earnings close the equation without a year-end JE."""

    def acct(*codes: str):
        for c in codes:
            if c in by_code:
                return by_code[c].id
        return None

    return [
        ("BS_ASSETS", "Assets", "asset", None, None, None, 0, True, False, 10),
        ("BS_CASH", "Cash", "asset", acct("1000"), None, None, 1, False, False, 20),
        ("BS_AR", "Accounts Receivable", "asset", acct("1100"), None, None, 1, False, False, 30),
        ("BS_INV", "Inventory", "asset", acct("1200"), None, None, 1, False, False, 40),
        ("BS_PREPAID", "Prepaid Expenses", "asset", acct("1300"), None, None, 1, False, False, 50),
        ("BS_FA", "Property & Equipment", "asset", acct("1400"), None, None, 1, False, False, 60),
        (
            "BS_TOT_ASSETS",
            "Total Assets",
            "asset",
            None,
            None,
            "BS_CASH + BS_AR + BS_INV + BS_PREPAID + BS_FA",
            0,
            True,
            True,
            70,
        ),
        ("BS_LIAB", "Liabilities", "liability", None, None, None, 0, True, False, 80),
        ("BS_AP", "Accounts Payable", "liability", acct("2000"), None, None, 1, False, False, 90),
        ("BS_IC", "Due to / From Intercompany", "liability", acct("2100"), None, None, 1, False, False, 100),
        ("BS_UNEARNED", "Unearned Revenue", "liability", acct("2200"), None, None, 1, False, False, 110),
        ("BS_TAX", "Taxes Payable", "liability", acct("2300"), None, None, 1, False, False, 120),
        ("BS_SH_LOAN", "Shareholder Loan", "liability", acct("2400"), None, None, 1, False, False, 130),
        (
            "BS_CASH_XFER",
            "Due to / from other bank accounts",
            "liability",
            acct("1000"),
            None,
            None,
            1,
            False,
            False,
            135,
        ),
        (
            "BS_TOT_LIAB",
            "Total Liabilities",
            "liability",
            None,
            None,
            "BS_AP + BS_IC + BS_UNEARNED + BS_TAX + BS_SH_LOAN + BS_CASH_XFER",
            0,
            True,
            True,
            140,
        ),
        ("BS_EQ_HDR", "Equity", "equity", None, None, None, 0, True, False, 150),
        ("BS_EQUITY", "Retained Earnings", "equity", acct("3000"), None, None, 1, False, False, 160),
        ("BS_DRAWS", "Owner Contributions / Draws", "equity", acct("3100"), None, None, 1, False, False, 170),
        (
            "BS_CURRENT_EARNINGS",
            "Current earnings",
            "equity",
            None,
            None,
            None,
            1,
            False,
            False,
            175,
        ),
        (
            "BS_TOT_EQUITY",
            "Total Equity",
            "equity",
            None,
            None,
            "BS_EQUITY + BS_DRAWS + BS_CURRENT_EARNINGS",
            0,
            True,
            True,
            180,
        ),
        (
            "BS_TOT_L_AND_E",
            "Total liabilities and equity",
            "totals",
            None,
            None,
            "BS_TOT_LIAB + BS_TOT_EQUITY",
            0,
            True,
            True,
            190,
        ),
    ]


def ensure_working_paper_foundation(db: Session) -> dict[str, int]:
    """Idempotently ensure CoA accounts and BS layout lines exist for WP sections."""
    created_accounts = 0
    created_layouts = 0
    updated_layouts = 0

    existing = {a.code: a for a in db.scalars(select(DimAccount)).all()}
    for code, name, acct_type, statement, normal, is_cash, is_ic, sort_order in _REQUIRED_ACCOUNTS:
        if code in existing:
            continue
        acct = DimAccount(
            code=code,
            name=name,
            account_type=acct_type,
            statement=statement,
            normal_balance=normal,
            is_cash=is_cash,
            is_intercompany=is_ic,
            sort_order=sort_order,
        )
        db.add(acct)
        created_accounts += 1
    db.flush()
    by_code = {a.code: a for a in db.scalars(select(DimAccount)).all()}

    existing_bs = {
        row.line_code: row
        for row in db.scalars(
            select(DimReportLayout).where(DimReportLayout.report_type == "balance_sheet")
        ).all()
    }

    for code, label, section, acct_id, type_f, formula, indent, bold, total, order in balance_sheet_layout_spec(
        by_code
    ):
        notes = None
        tmpl = find_template(line_code=code)
        if tmpl:
            notes = f"wp:{tmpl.key}"
        if code == "BS_CURRENT_EARNINGS":
            notes = "wp:pnl_analysis"
        if code == "BS_CASH_XFER":
            notes = "wp:bank_transfers"
        if code in existing_bs:
            row = existing_bs[code]
            changed = False
            if row.line_label != label:
                row.line_label = label
                changed = True
            if row.calc_formula != formula:
                row.calc_formula = formula
                changed = True
            if row.sort_order != order:
                row.sort_order = order
                changed = True
            if row.account_id != acct_id:
                row.account_id = acct_id
                changed = True
            if row.section != section:
                row.section = section
                changed = True
            if row.indent_level != indent:
                row.indent_level = indent
                changed = True
            if row.is_bold != bold:
                row.is_bold = bold
                changed = True
            if row.is_total != total:
                row.is_total = total
                changed = True
            if notes and row.notes != notes:
                row.notes = notes
                changed = True
            if changed:
                updated_layouts += 1
            continue
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
                notes=notes,
            )
        )
        created_layouts += 1

    # Tag existing IS NI line with pnl template note if blank
    ni = db.scalar(
        select(DimReportLayout).where(
            DimReportLayout.report_type == "income_statement",
            DimReportLayout.line_code == "NI",
        )
    )
    if ni and not ni.notes:
        ni.notes = "wp:pnl_analysis"

    db.commit()

    return {
        "accounts_created": created_accounts,
        "layouts_created": created_layouts,
        "layouts_updated": updated_layouts,
    }
