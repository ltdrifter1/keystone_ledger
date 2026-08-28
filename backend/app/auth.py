"""Named session user. SPA sends X-Keystone-Actor; cookie is a fallback."""

from __future__ import annotations

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.engines.identity import ensure_users, serialize_user
from app.models import AppUser

ACTOR_HEADER = "X-Keystone-Actor"
COOKIE_NAME = "keystone_user"


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    x_keystone_actor: str | None = Header(default=None, alias=ACTOR_HEADER),
) -> AppUser:
    ensure_users(db)
    token = (x_keystone_actor or request.cookies.get(COOKIE_NAME) or "").strip()
    if token:
        user = db.scalar(
            select(AppUser).where(
                AppUser.is_active == True,  # noqa: E712
                (AppUser.username == token) | (AppUser.initials == token),
            )
        )
        if user:
            return user
    fallback = db.scalar(select(AppUser).where(AppUser.is_active == True).order_by(AppUser.id))  # noqa: E712
    if not fallback:
        raise RuntimeError("No app users seeded")
    return fallback


def get_actor(user: AppUser = Depends(get_current_user)) -> str:
    return user.initials


def user_payload(user: AppUser) -> dict:
    return serialize_user(user)
