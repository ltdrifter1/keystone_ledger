from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import get_actor
from app.database import get_db
from app.engines.close_pack import (
    build_close_pack_status,
    lock_close_pack,
    lock_month,
    month_close_overview,
    resolve_exception_categorize,
    resolve_exception_clear,
    resolve_exception_void_duplicate,
    run_close_pack_from_feed,
    run_statement_close_pack,
)
from app.models import Reconciliation
from app.schemas.close_pack import (
    CategorizeExceptionRequest,
    ClearExceptionRequest,
    ClosePackStatus,
    MonthCloseOverview,
)

router = APIRouter(prefix="/close-pack", tags=["close-pack"])


def _status_model(data: dict) -> ClosePackStatus:
    return ClosePackStatus.model_validate(data)


@router.get("/month", response_model=MonthCloseOverview)
def get_month(year: int, month: int, db: Session = Depends(get_db)) -> MonthCloseOverview:
    return MonthCloseOverview.model_validate(month_close_overview(db, year, month))


@router.post("/run", response_model=ClosePackStatus)
async def run_pack(
    bank_account_id: int = Form(...),
    period_year: int = Form(...),
    period_month: int = Form(...),
    statement_ending_balance: Decimal = Form(...),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    actor: str = Depends(get_actor),
) -> ClosePackStatus:
    file_bytes = None
    filename = None
    if file is not None:
        file_bytes = await file.read()
        filename = file.filename or "statement.csv"
        if not file_bytes:
            raise HTTPException(400, "Empty file")
    try:
        result = run_statement_close_pack(
            db,
            bank_account_id=bank_account_id,
            period_year=period_year,
            period_month=period_month,
            statement_ending_balance=statement_ending_balance,
            file_bytes=file_bytes,
            filename=filename,
            actor=actor,
        )
        db.commit()
        return _status_model(result)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.post("/run-from-feed", response_model=ClosePackStatus)
def run_pack_from_feed(
    bank_account_id: int = Form(...),
    period_year: int = Form(...),
    period_month: int = Form(...),
    db: Session = Depends(get_db),
    actor: str = Depends(get_actor),
) -> ClosePackStatus:
    try:
        result = run_close_pack_from_feed(
            db,
            bank_account_id=bank_account_id,
            period_year=period_year,
            period_month=period_month,
            actor=actor,
        )
        db.commit()
        return _status_model(result)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.get("/{recon_id}", response_model=ClosePackStatus)
def get_pack(recon_id: int, db: Session = Depends(get_db)) -> ClosePackStatus:
    recon = db.get(Reconciliation, recon_id)
    if not recon:
        raise HTTPException(404, "Not found")
    data = build_close_pack_status(db, recon)
    db.commit()
    return _status_model(data)


@router.post("/{recon_id}/refresh", response_model=ClosePackStatus)
def refresh_pack(
    recon_id: int, db: Session = Depends(get_db), actor: str = Depends(get_actor)
) -> ClosePackStatus:
    from app.engines.close_pack import auto_clear_statement_items
    from app.engines.rules import apply_rules_batch
    from sqlalchemy import select
    from app.models import Transaction

    recon = db.get(Reconciliation, recon_id)
    if not recon:
        raise HTTPException(404, "Not found")
    if recon.status == "locked":
        raise HTTPException(409, "Period is locked")
    uncat = list(
        db.scalars(
            select(Transaction).where(
                Transaction.bank_account_id == recon.bank_account_id,
                Transaction.status == "uncategorized",
            )
        )
    )
    apply_rules_batch(db, uncat, actor=actor)
    auto_clear_statement_items(db, recon, actor=actor)
    data = build_close_pack_status(db, recon)
    db.commit()
    return _status_model(data)


@router.post("/{recon_id}/exceptions/{txn_id}/categorize", response_model=ClosePackStatus)
def categorize_exception(
    recon_id: int,
    txn_id: int,
    payload: CategorizeExceptionRequest,
    db: Session = Depends(get_db),
    actor: str = Depends(get_actor),
) -> ClosePackStatus:
    try:
        data = resolve_exception_categorize(
            db,
            reconciliation_id=recon_id,
            transaction_id=txn_id,
            account_id=payload.account_id,
            create_rule=payload.create_rule,
            clear_after=payload.clear_after,
            actor=actor,
        )
        db.commit()
        return _status_model(data)
    except ValueError as exc:
        db.rollback()
        status = 409 if "locked" in str(exc).lower() else 400
        raise HTTPException(status, str(exc)) from exc


@router.post("/{recon_id}/exceptions/{txn_id}/clear", response_model=ClosePackStatus)
def clear_exception(
    recon_id: int,
    txn_id: int,
    payload: ClearExceptionRequest,
    db: Session = Depends(get_db),
    actor: str = Depends(get_actor),
) -> ClosePackStatus:
    try:
        data = resolve_exception_clear(
            db,
            reconciliation_id=recon_id,
            transaction_id=txn_id,
            is_cleared=payload.is_cleared,
            actor=actor,
        )
        db.commit()
        return _status_model(data)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.post("/{recon_id}/exceptions/{txn_id}/void-duplicate", response_model=ClosePackStatus)
def void_duplicate(
    recon_id: int, txn_id: int, db: Session = Depends(get_db), actor: str = Depends(get_actor)
) -> ClosePackStatus:
    try:
        data = resolve_exception_void_duplicate(
            db,
            reconciliation_id=recon_id,
            transaction_id=txn_id,
            actor=actor,
        )
        db.commit()
        return _status_model(data)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.post("/{recon_id}/lock", response_model=ClosePackStatus)
def lock_pack(
    recon_id: int, db: Session = Depends(get_db), actor: str = Depends(get_actor)
) -> ClosePackStatus:
    try:
        data = lock_close_pack(db, recon_id, actor=actor)
        db.commit()
        return _status_model(data)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


@router.post("/month/lock", response_model=MonthCloseOverview)
def lock_month_endpoint(
    year: int, month: int, db: Session = Depends(get_db), actor: str = Depends(get_actor)
) -> MonthCloseOverview:
    data = lock_month(db, year, month, actor=actor)
    db.commit()
    return MonthCloseOverview.model_validate(data)
