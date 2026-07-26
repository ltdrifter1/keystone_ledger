# Keystone Ledger

A lightweight Controller/CFO reporting application for bank reconciliations, transaction management, and financial reporting.

This is **not** an ERP or bookkeeping system. It replaces an Excel finance workbook with a modern desktop/web app while preserving the underlying accounting logic.

## Design principle

**Transactions are the center of the system.** Bank accounts, entities, departments, and currencies are attributes of each transaction. That scales from two companies today to dozens of entities and future ERP imports (QuickBooks, Business Central) without redesign.

## Architecture

```
Database (star schema)
  FACT grain  → transactions (+ transaction_splits)
  Dimensions  → DIM_ACCOUNT, DIM_ENTITY, DIM_DEPARTMENT,
                DIM_DATE, DIM_SCENARIO, DIM_FX, DIM_REPORT_LAYOUT
  Ops tables  → bank_accounts, reconciliations, categorization_rules,
                audit_log, attachments

Business logic
  Categorization · Rule engine · Reconciliation
  Reporting · Consolidation · FX translation · Intercompany matching

UI
  Dashboard · Transactions · Bank Accounts
  Reconciliation · Reports · Settings
```

### Stack

| Layer | Technology |
|-------|------------|
| API | FastAPI + SQLAlchemy |
| DB | SQLite (Postgres-ready URL) |
| UI | React + Vite + TypeScript |
| Import | pandas / openpyxl (CSV & Excel) |

## Quick start

### Backend

```bash
cd backend
python3 -m pip install -r requirements.txt
export PATH="$HOME/.local/bin:$PATH"
uvicorn app.main:app --reload --port 8000
```

API docs: http://127.0.0.1:8000/docs

On first boot the app seeds Canada/USA entities, chart of accounts, bank accounts, categorization rules, FX rates, and sample transactions.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

UI: http://127.0.0.1:5173

## Core workflows

1. **Import** bank CSV/Excel → stored as transactions with fingerprint-based duplicate detection
2. **Rules** auto-categorize known patterns; one-click manual recode can create a new rule
3. **Split** a transaction across multiple reporting accounts
4. **Match** intercompany transfers across entities
5. **Reconcile** each bank account monthly; lock completed periods
6. **Report** Income Statement / Balance Sheet / Cash Flow from categorized facts + dimensions
7. **Dashboard** cash, P&L, working capital, FX exposure, open reconciliations, IC balances

## Keyboard shortcuts (Transactions)

| Key | Action |
|-----|--------|
| `/` | Focus search |
| `C` | Categorize selection |
| `R` | Apply categorization rules |
| `I` | Auto-match intercompany |

## Extensibility

The layered layout is ready for future modules without changing the core:

- AP / AR subledgers (additional transaction `source_type` values)
- Budgeting & forecasting (already modeled via `DIM_SCENARIO`)
- Consolidations & eliminations (entity hierarchy + IC matching)
- Variance analysis (compare scenarios in the reporting engine)

## Project layout

```
backend/
  app/
    api/          # HTTP routes
    engines/      # business logic
    models/       # SQLAlchemy star schema + domain
    schemas/      # Pydantic contracts
    services/     # seed & app services
frontend/
  src/
    pages/        # Dashboard, Transactions, Reconciliation, Reports, Settings
    api.ts        # typed API client
```

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `KEYSTONE_DATABASE_URL` | `sqlite:///…/data/keystone.db` | Database URL |
| `KEYSTONE_DEFAULT_REPORTING_CURRENCY` | `CAD` | Dashboard/report currency |
