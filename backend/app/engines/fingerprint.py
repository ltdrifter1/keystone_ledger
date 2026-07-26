from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal


def transaction_fingerprint(
    *,
    txn_date: date,
    amount: Decimal,
    description: str,
    currency: str,
    bank_account_id: int | None,
    external_id: str | None = None,
) -> str:
    """Stable hash for duplicate detection across imports."""
    if external_id:
        raw = f"ext|{external_id}|{bank_account_id}"
    else:
        desc = " ".join(description.upper().split())
        raw = f"{txn_date.isoformat()}|{amount:.2f}|{desc}|{currency}|{bank_account_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
