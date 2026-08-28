from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_actor
from app.database import get_db
from app.engines.audit import write_audit
from app.models import CategorizationRule
from app.schemas.common import RuleCreate, RuleOut, RulePreviewOut, RulePreviewRequest, RuleUpdate

router = APIRouter(prefix="/rules")


@router.get("", response_model=list[RuleOut])
def list_rules(db: Session = Depends(get_db)) -> list[RuleOut]:
    return list(
        db.scalars(select(CategorizationRule).order_by(CategorizationRule.priority, CategorizationRule.id))
    )


@router.post("/preview", response_model=RulePreviewOut)
def preview_rules(
    payload: RulePreviewRequest, db: Session = Depends(get_db)
) -> RulePreviewOut:
    from app.engines.rules import preview_rule

    if payload.rule_id is not None:
        rule = db.get(CategorizationRule, payload.rule_id)
        if not rule:
            raise HTTPException(404, "Rule not found")
    else:
        rule = CategorizationRule(
            name="preview",
            priority=50,
            is_active=True,
            assign_account_id=1,
            match_description_contains=payload.match_description_contains,
            match_description_regex=payload.match_description_regex,
            match_counterparty=payload.match_counterparty,
            match_amount_min=payload.match_amount_min,
            match_amount_max=payload.match_amount_max,
            match_currency=payload.match_currency,
            match_entity_id=payload.match_entity_id,
            match_bank_account_id=payload.match_bank_account_id,
        )
    result = preview_rule(
        db,
        rule,
        uncategorized_only=payload.uncategorized_only,
        sample_limit=payload.limit,
    )
    return RulePreviewOut(
        matched_uncategorized=result["matched_uncategorized"],
        matched_total=result["matched_total"],
        sample=[
            {
                "id": t.id,
                "txn_date": t.txn_date,
                "description": t.description,
                "amount": t.amount,
                "currency": t.currency,
                "entity_id": t.entity_id,
                "bank_account_id": t.bank_account_id,
                "status": t.status,
            }
            for t in result["sample"]
        ],
    )


@router.post("", response_model=RuleOut)
def create_rule(
    payload: RuleCreate, db: Session = Depends(get_db), actor: str = Depends(get_actor)
) -> RuleOut:
    rule = CategorizationRule(**payload.model_dump())
    db.add(rule)
    db.flush()
    write_audit(db, entity_table="categorization_rules", entity_id=rule.id, action="create", actor=actor)
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: int, payload: RuleUpdate, db: Session = Depends(get_db), actor: str = Depends(get_actor)
) -> RuleOut:
    rule = db.get(CategorizationRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(rule, k, v)
    write_audit(db, entity_table="categorization_rules", entity_id=rule.id, action="update", actor=actor)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), actor: str = Depends(get_actor)) -> dict:
    rule = db.get(CategorizationRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    write_audit(db, entity_table="categorization_rules", entity_id=rule.id, action="delete", actor=actor)
    db.delete(rule)
    db.commit()
    return {"deleted": rule_id}
