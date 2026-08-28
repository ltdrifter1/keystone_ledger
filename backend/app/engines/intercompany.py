"""Monthly intercompany rec — match split legs across CAN/USA with FX."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.engines.audit import write_audit
from app.engines.fx import translate_amount
from app.models import DimAccount, DimEntity, Transaction
from app.schemas.transactions import IntercompanyMatchOut

IC_CODES = {"1100", "2000", "2100"}
DEDICATED_IC_CODES = {"2100"}
IC_KEYWORDS = ("INTERCO", "INTERCOMPANY", "IC TRANSFER", "DUE TO", "DUE FROM")
FX_TOLERANCE = Decimal("50.00")  # monthly rec tolerance in CAD
FX_PCT = Decimal("0.02")


def _blob(txn: Transaction, extra: str = "") -> str:
    return f"{txn.description or ''} {txn.counterparty or ''} {txn.memo or ''} {extra}".upper()


def account_is_ic_leg(acct: DimAccount | None, txn: Transaction, extra: str = "") -> bool:
    """1100/2000 count only when the voucher is actually intercompany (not third-party AR/AP)."""
    if not acct:
        return False
    if acct.is_intercompany or acct.account_type in ("transfer", "intercompany"):
        return True
    if acct.code in DEDICATED_IC_CODES:
        return True
    blob = _blob(txn, extra)
    keyword = any(k in blob for k in IC_KEYWORDS)
    if acct.code in ("1100", "2000"):
        return bool(txn.counter_entity_id) or keyword
    return keyword


def _iter_ic_splits(txn: Transaction, accounts: dict[int, DimAccount]):
    splits = list(txn.splits) if txn.is_split and txn.splits else []
    if not splits and txn.account_id:
        splits = [type("S", (), {"account_id": txn.account_id, "amount": txn.amount, "memo": txn.memo})()]
    for split in splits:
        acct = accounts.get(split.account_id)
        if account_is_ic_leg(acct, txn, getattr(split, "memo", "") or ""):
            yield split, acct


def _is_ic_txn(txn: Transaction, accounts: dict[int, DimAccount]) -> bool:
    return any(True for _ in _iter_ic_splits(txn, accounts))


def _leg_amount(txn: Transaction, accounts: dict[int, DimAccount]) -> Decimal:
    total = Decimal("0")
    found = False
    for split, _acct in _iter_ic_splits(txn, accounts):
        total += Decimal(split.amount)
        found = True
    if found:
        return total
    return Decimal("0")


def _month_window(txn_date: date) -> tuple[date, date]:
    return date(txn_date.year, txn_date.month, 1), date(
        txn_date.year, txn_date.month, monthrange(txn_date.year, txn_date.month)[1]
    )


def _accounts_map(db: Session) -> dict[int, DimAccount]:
    return {a.id: a for a in db.scalars(select(DimAccount)).all()}


def find_intercompany_candidates(db: Session, lookback_days: int = 7) -> list[IntercompanyMatchOut]:
    """Match opposite IC legs across entities in the same month (monthly rec)."""
    _ = lookback_days  # kept for API compatibility; matching is month-scoped
    accounts = _accounts_map(db)
    txns = list(
        db.scalars(
            select(Transaction)
            .options(joinedload(Transaction.splits))
            .where(
                Transaction.status != "void",
                Transaction.intercompany_match_id.is_(None),
            )
        ).unique()
    )
    candidates = [t for t in txns if _is_ic_txn(t, accounts) and _leg_amount(t, accounts) != 0]
    matches: list[IntercompanyMatchOut] = []
    used: set[int] = set()

    for left in candidates:
        if left.id in used:
            continue
        left_amt = _leg_amount(left, accounts)
        left_cad, _ = translate_amount(
            db, amount=left_amt, from_currency=left.currency, to_currency="CAD", as_of=left.txn_date, rate_type="closing"
        )
        start, end = _month_window(left.txn_date)
        for right in candidates:
            if right.id in used or right.id == left.id:
                continue
            if left.entity_id == right.entity_id:
                continue
            if not (start <= right.txn_date <= end):
                continue
            if left.counter_entity_id and left.counter_entity_id != right.entity_id:
                continue
            if right.counter_entity_id and right.counter_entity_id != left.entity_id:
                continue
            right_amt = _leg_amount(right, accounts)
            right_cad, _ = translate_amount(
                db,
                amount=right_amt,
                from_currency=right.currency,
                to_currency="CAD",
                as_of=right.txn_date,
                rate_type="closing",
            )
            combined = left_cad + right_cad
            cap = max(abs(left_cad), abs(right_cad), Decimal("1")) * FX_PCT
            if abs(combined) > max(FX_TOLERANCE, cap):
                continue
            confidence = "high" if left.currency == right.currency else "medium"
            if not left.counter_entity_id and not right.counter_entity_id:
                confidence = "medium"
            matches.append(
                IntercompanyMatchOut(
                    left_id=left.id,
                    right_id=right.id,
                    amount=abs(left_amt),
                    left_entity_id=left.entity_id,
                    right_entity_id=right.entity_id,
                    confidence=confidence,
                )
            )
            used.add(left.id)
            used.add(right.id)
            break
    return matches


def apply_intercompany_match(
    db: Session,
    left_id: int,
    right_id: int,
    actor: str = "system",
) -> tuple[Transaction, Transaction]:
    left = db.get(Transaction, left_id)
    right = db.get(Transaction, right_id)
    if not left or not right:
        raise ValueError("Transaction not found")
    accounts = _accounts_map(db)
    left_amt = _leg_amount(left, accounts)
    right_amt = _leg_amount(right, accounts)
    left_cad, _ = translate_amount(
        db, amount=left_amt, from_currency=left.currency, to_currency="CAD", as_of=left.txn_date, rate_type="closing"
    )
    right_cad, _ = translate_amount(
        db, amount=right_amt, from_currency=right.currency, to_currency="CAD", as_of=right.txn_date, rate_type="closing"
    )
    cap = max(abs(left_cad), abs(right_cad), Decimal("1")) * FX_PCT
    if abs(left_cad + right_cad) > max(FX_TOLERANCE, cap):
        raise ValueError("Amounts must be opposite within monthly FX tolerance")

    left.intercompany_match_id = right.id
    right.intercompany_match_id = left.id
    left.counter_entity_id = right.entity_id
    right.counter_entity_id = left.entity_id
    if left.status == "uncategorized":
        left.status = "matched"
    if right.status == "uncategorized":
        right.status = "matched"

    write_audit(
        db,
        entity_table="transactions",
        entity_id=left.id,
        action="ic_match",
        new_value=right.id,
        actor=actor,
    )
    write_audit(
        db,
        entity_table="transactions",
        entity_id=right.id,
        action="ic_match",
        new_value=left.id,
        actor=actor,
    )
    return left, right


def auto_match_intercompany(db: Session, actor: str = "system") -> int:
    matches = find_intercompany_candidates(db)
    count = 0
    for m in matches:
        if m.confidence in ("high", "medium"):
            apply_intercompany_match(db, m.left_id, m.right_id, actor=actor)
            count += 1
    return count


def unmatched_intercompany_count(
    db: Session, *, entity_id: int | None = None, year: int | None = None, month: int | None = None
) -> int:
    accounts = _accounts_map(db)
    q = select(Transaction).options(joinedload(Transaction.splits)).where(
        Transaction.intercompany_match_id.is_(None),
        Transaction.status != "void",
    )
    if entity_id:
        q = q.where(Transaction.entity_id == entity_id)
    if year and month:
        start, end = date(year, month, 1), date(year, month, monthrange(year, month)[1])
        q = q.where(Transaction.txn_date >= start, Transaction.txn_date <= end)
    txns = list(db.scalars(q).unique())
    return sum(1 for t in txns if _is_ic_txn(t, accounts) and _leg_amount(t, accounts) != 0)


def ic_mirror(db: Session, *, entity_id: int, year: int, month: int) -> dict:
    """This company's IC AR/AP vs the other company's opposite balance (monthly rec, CAD)."""
    entities = {e.id: e for e in db.scalars(select(DimEntity)).all()}
    entity = entities.get(entity_id)
    other = next((e for e in entities.values() if e.id != entity_id), None)
    accounts = _accounts_map(db)
    end = date(year, month, monthrange(year, month)[1])

    def position(eid: int) -> dict[str, Decimal]:
        out = {"ar": Decimal("0"), "ap": Decimal("0"), "ic": Decimal("0")}
        txns = list(
            db.scalars(
                select(Transaction)
                .options(joinedload(Transaction.splits))
                .where(
                    Transaction.entity_id == eid,
                    Transaction.status != "void",
                    Transaction.txn_date >= date(2000, 1, 1),
                    Transaction.txn_date <= end,
                )
            ).unique()
        )
        for txn in txns:
            for split, acct in _iter_ic_splits(txn, accounts):
                amt = Decimal(split.amount)
                cad, _ = translate_amount(
                    db, amount=amt, from_currency=txn.currency, to_currency="CAD", as_of=end, rate_type="closing"
                )
                if acct and acct.code == "1100":
                    out["ar"] += cad
                elif acct and acct.code == "2000":
                    out["ap"] += cad
                else:
                    out["ic"] += cad
        return out

    ours = position(entity_id)
    theirs = position(other.id) if other else {"ar": Decimal("0"), "ap": Decimal("0"), "ic": Decimal("0")}
    ours_net = ours["ar"] + ours["ap"] + ours["ic"]
    theirs_net = theirs["ar"] + theirs["ap"] + theirs["ic"]
    diff = ours_net + theirs_net
    return {
        "entity_code": entity.code if entity else None,
        "counter_entity_code": other.code if other else None,
        "ours": {k: float(v) for k, v in ours.items()},
        "theirs": {k: float(v) for k, v in theirs.items()},
        "ours_net": float(ours_net),
        "theirs_net": float(theirs_net),
        "difference": float(diff),
        "is_mirrored": abs(diff) <= max(FX_TOLERANCE, Decimal("1")),
        "currency": "CAD",
        "period_label": f"{year}-{month:02d}",
    }
