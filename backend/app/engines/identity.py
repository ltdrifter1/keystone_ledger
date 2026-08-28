"""Seeded close-team identities for SoD and audit."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppUser

DEFAULT_USERS = (
    {
        "username": "alex",
        "display_name": "Alex Chen",
        "initials": "AC",
        "role": "preparer",
    },
    {
        "username": "riley",
        "display_name": "Riley Park",
        "initials": "RP",
        "role": "reviewer",
    },
    {
        "username": "kai",
        "display_name": "Kai Admin",
        "initials": "KA",
        "role": "admin",
    },
)


def ensure_users(db: Session) -> int:
    created = 0
    for spec in DEFAULT_USERS:
        existing = db.scalar(select(AppUser).where(AppUser.username == spec["username"]))
        if existing:
            continue
        db.add(AppUser(**spec, is_active=True))
        created += 1
    if created:
        db.flush()
    return created


def list_users(db: Session) -> list[AppUser]:
    ensure_users(db)
    return list(db.scalars(select(AppUser).where(AppUser.is_active == True).order_by(AppUser.id)))  # noqa: E712


def get_user_by_token(db: Session, token: str) -> AppUser | None:
    token = (token or "").strip()
    if not token:
        return None
    return db.scalar(
        select(AppUser).where(
            AppUser.is_active == True,  # noqa: E712
            (AppUser.username == token) | (AppUser.initials == token),
        )
    )


def serialize_user(user: AppUser) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "initials": user.initials,
        "role": user.role,
    }
