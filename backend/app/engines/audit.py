from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog


def write_audit(
    db: Session,
    *,
    entity_table: str,
    entity_id: int,
    action: str,
    field_name: Optional[str] = None,
    old_value: Any = None,
    new_value: Any = None,
    actor: str = "system",
    meta: Optional[dict] = None,
) -> AuditLog:
    entry = AuditLog(
        entity_table=entity_table,
        entity_id=entity_id,
        action=action,
        field_name=field_name,
        old_value=None if old_value is None else str(old_value),
        new_value=None if new_value is None else str(new_value),
        actor=actor,
        meta_json=json.dumps(meta) if meta else None,
    )
    db.add(entry)
    return entry


def audit_field_changes(
    db: Session,
    *,
    entity_table: str,
    entity_id: int,
    changes: dict[str, tuple[Any, Any]],
    actor: str = "system",
    action: str = "update",
) -> None:
    for field, (old, new) in changes.items():
        if old != new:
            write_audit(
                db,
                entity_table=entity_table,
                entity_id=entity_id,
                action=action,
                field_name=field,
                old_value=old,
                new_value=new,
                actor=actor,
            )
