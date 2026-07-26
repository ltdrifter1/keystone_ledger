from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.engines.audit import write_audit
from app.models import AuditLog, BankAccount, DimAccount, DimDepartment, DimEntity, DimFx, DimScenario
from app.schemas.common import (
    AccountCreate,
    AccountOut,
    AuditLogOut,
    BankAccountCreate,
    BankAccountOut,
    DepartmentOut,
    EntityCreate,
    EntityOut,
    FxRateCreate,
    FxRateOut,
    ScenarioOut,
)

router = APIRouter()


@router.get("/entities", response_model=list[EntityOut])
def list_entities(db: Session = Depends(get_db)) -> list[EntityOut]:
    return list(db.scalars(select(DimEntity).order_by(DimEntity.code)))


@router.post("/entities", response_model=EntityOut)
def create_entity(payload: EntityCreate, db: Session = Depends(get_db)) -> EntityOut:
    ent = DimEntity(**payload.model_dump())
    db.add(ent)
    db.flush()
    write_audit(db, entity_table="dim_entity", entity_id=ent.id, action="create", actor="controller")
    db.commit()
    db.refresh(ent)
    return ent


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)) -> list[AccountOut]:
    return list(db.scalars(select(DimAccount).order_by(DimAccount.sort_order, DimAccount.code)))


@router.post("/accounts", response_model=AccountOut)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)) -> AccountOut:
    acct = DimAccount(**payload.model_dump())
    db.add(acct)
    db.flush()
    write_audit(db, entity_table="dim_account", entity_id=acct.id, action="create", actor="controller")
    db.commit()
    db.refresh(acct)
    return acct


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(db: Session = Depends(get_db)) -> list[DepartmentOut]:
    return list(db.scalars(select(DimDepartment).order_by(DimDepartment.code)))


@router.get("/scenarios", response_model=list[ScenarioOut])
def list_scenarios(db: Session = Depends(get_db)) -> list[ScenarioOut]:
    return list(db.scalars(select(DimScenario).order_by(DimScenario.id)))


@router.get("/bank-accounts", response_model=list[BankAccountOut])
def list_bank_accounts(db: Session = Depends(get_db)) -> list[BankAccountOut]:
    return list(db.scalars(select(BankAccount).order_by(BankAccount.name)))


@router.post("/bank-accounts", response_model=BankAccountOut)
def create_bank_account(payload: BankAccountCreate, db: Session = Depends(get_db)) -> BankAccountOut:
    bank = BankAccount(**payload.model_dump())
    db.add(bank)
    db.flush()
    write_audit(db, entity_table="bank_accounts", entity_id=bank.id, action="create", actor="controller")
    db.commit()
    db.refresh(bank)
    return bank


@router.get("/fx-rates", response_model=list[FxRateOut])
def list_fx(db: Session = Depends(get_db)) -> list[FxRateOut]:
    return list(db.scalars(select(DimFx).order_by(DimFx.rate_date.desc()).limit(200)))


@router.post("/fx-rates", response_model=FxRateOut)
def create_fx(payload: FxRateCreate, db: Session = Depends(get_db)) -> FxRateOut:
    row = DimFx(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/audit-log", response_model=list[AuditLogOut])
def audit_log(limit: int = 100, db: Session = Depends(get_db)) -> list[AuditLogOut]:
    return list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)))
