"""Swappable bank-feed providers.

`DemoWbcProvider` is the seeded Open Banking catalog.
`CsvFolderProvider` reads `KEYSTONE_FEEDS_DIR/{account_number}.csv` so a real
statement drop-in replaces the demo without changing Work.
`CompositeProvider` (default) prefers the CSV when present, else demo.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import pandas as pd

from app.config import get_settings
from app.engines.importing import BankImportRow, _normalize_columns, _parse_amount, _parse_date
from app.models import BankAccount

DEMO_CATALOG: dict[str, list[tuple[str, str, str, str, str | None]]] = {
    "1010": [
        ("2026-07-28", "WBC LIVE — INTERAC E-TRANSFER A. CHEN", "-250.00", "FIT-1010-1", "A. Chen"),
        ("2026-07-29", "WBC LIVE — STRIPE SETTLEMENT", "4820.15", "FIT-1010-2", "Stripe"),
        ("2026-07-30", "WBC LIVE — SERVICE CHARGE", "-4.50", "FIT-1010-3", "WBC"),
        ("2026-07-31", "WBC LIVE — PAYROLL FUNDING", "-18500.00", "FIT-1010-4", "ADP"),
    ],
    "1015": [
        ("2026-07-29", "WBC LIVE — USD WIRE IN", "3200.00", "FIT-1015-1", "WBC USA"),
        ("2026-07-31", "WBC LIVE — FX SERVICE FEE", "-18.00", "FIT-1015-2", "WBC"),
    ],
    "1030": [
        ("2026-07-28", "WBC LIVE — VENDOR ACH", "-640.00", "FIT-1030-1", "Vendor"),
        ("2026-07-30", "WBC LIVE — INTEREST CREDIT", "12.40", "FIT-1030-2", "WBC"),
    ],
    "1050": [
        ("2026-07-29", "WBC LIVE — CARD SETTLEMENT", "910.22", "FIT-1050-1", "Visa"),
        ("2026-07-31", "WBC LIVE — CARD FEE", "-9.10", "FIT-1050-2", "WBC"),
    ],
    "USA-1010": [
        ("2026-07-15", "WBC LIVE — US OPERATING DEPOSIT", "25000.00", "FIT-USA-1", "Customer"),
        ("2026-07-18", "WBC LIVE — US PAYROLL", "-8200.00", "FIT-USA-2", "Gusto"),
        ("2026-07-22", "WBC LIVE — AWS", "-1420.55", "FIT-USA-3", "Amazon"),
        ("2026-07-28", "WBC LIVE — STRIPE US", "6110.00", "FIT-USA-4", "Stripe"),
        ("2026-07-31", "WBC LIVE — ACCOUNT FEE", "-15.00", "FIT-USA-5", "WBC"),
    ],
}


class FeedProvider(Protocol):
    key: str
    label: str

    def rows(self, bank: BankAccount) -> list[BankImportRow]: ...


def _tuples_to_rows(
    bank: BankAccount, raw: list[tuple[str, str, str, str, str | None]]
) -> list[BankImportRow]:
    rows: list[BankImportRow] = []
    for txn_date, description, amount, external_id, counterparty in raw:
        rows.append(
            BankImportRow(
                txn_date=date.fromisoformat(txn_date),
                description=description,
                amount=Decimal(amount),
                currency=bank.currency,
                external_id=external_id,
                reference=external_id,
                counterparty=counterparty,
                label=external_id,
            )
        )
    return rows


class DemoWbcProvider:
    key = "keystone_open_banking"
    label = "Demo Open Banking (WBC catalog)"

    def rows(self, bank: BankAccount) -> list[BankImportRow]:
        raw = DEMO_CATALOG.get(bank.account_number)
        if not raw:
            suffix = str(bank.id)
            raw = [
                (
                    "2026-07-28",
                    f"LIVE FEED — {bank.name} SETTLEMENT",
                    "1500.00",
                    f"FIT-{suffix}-1",
                    bank.institution,
                ),
                (
                    "2026-07-30",
                    f"LIVE FEED — {bank.name} FEE",
                    "-12.00",
                    f"FIT-{suffix}-2",
                    bank.institution,
                ),
            ]
        return _tuples_to_rows(bank, raw)


class CsvFolderProvider:
    key = "csv_folder"
    label = "CSV folder adapter"

    def __init__(self, feeds_dir: str | Path | None = None) -> None:
        settings = get_settings()
        self.feeds_dir = Path(feeds_dir or settings.feeds_dir)

    def source_path(self, bank: BankAccount) -> Path | None:
        self.feeds_dir.mkdir(parents=True, exist_ok=True)
        for name in (bank.account_number, bank.account_number.replace(" ", "_")):
            for ext in (".csv", ".CSV"):
                path = self.feeds_dir / f"{name}{ext}"
                if path.exists():
                    return path
        return None

    def rows(self, bank: BankAccount) -> list[BankImportRow]:
        path = self.source_path(bank)
        if not path:
            return []
        df = pd.read_csv(path)
        df = _normalize_columns(df)
        rows: list[BankImportRow] = []
        for idx, rec in enumerate(df.to_dict(orient="records")):
            try:
                amount = _parse_amount(rec)
                txn_date = _parse_date(rec.get("date") or rec.get("txn_date"))
            except (ValueError, KeyError, TypeError):
                continue
            ext = rec.get("external_id") or rec.get("reference") or f"CSV-{bank.account_number}-{idx+1}"
            desc = str(rec.get("description") or rec.get("memo") or path.name)
            rows.append(
                BankImportRow(
                    txn_date=txn_date,
                    description=desc,
                    amount=amount,
                    currency=str(rec.get("currency") or bank.currency),
                    external_id=str(ext),
                    reference=str(rec.get("reference") or ext),
                    counterparty=(str(rec["counterparty"]) if rec.get("counterparty") else None),
                    label=str(ext),
                )
            )
        return rows


class CompositeProvider:
    """CSV drop-in when present, otherwise the demo catalog."""

    key = "keystone_open_banking"
    label = "Composite (CSV folder, else demo catalog)"

    def __init__(self) -> None:
        self.csv = CsvFolderProvider()
        self.demo = DemoWbcProvider()

    def rows(self, bank: BankAccount) -> list[BankImportRow]:
        csv_rows = self.csv.rows(bank)
        if csv_rows:
            return csv_rows
        return self.demo.rows(bank)


def get_provider() -> FeedProvider:
    kind = (get_settings().feed_provider or "composite").strip().lower()
    if kind in ("demo", "keystone_open_banking"):
        return DemoWbcProvider()
    if kind in ("csv", "csv_folder"):
        return CsvFolderProvider()
    return CompositeProvider()
