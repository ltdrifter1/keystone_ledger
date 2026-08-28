from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME, get_current_user
from app.database import get_db
from app.engines.identity import get_user_by_token, list_users, serialize_user
from app.models import AppUser
from app.schemas.session import SessionOut, SessionSwitch, UserOut

router = APIRouter(prefix="/session", tags=["session"])


@router.get("", response_model=SessionOut)
def read_session(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)) -> SessionOut:
    users = [UserOut(**serialize_user(u)) for u in list_users(db)]
    return SessionOut(user=UserOut(**serialize_user(user)), users=users)


@router.post("/switch", response_model=SessionOut)
def switch_session(
    payload: SessionSwitch,
    response: Response,
    db: Session = Depends(get_db),
) -> SessionOut:
    user = get_user_by_token(db, payload.username)
    if not user:
        raise HTTPException(404, f"Unknown user '{payload.username}'")
    response.set_cookie(COOKIE_NAME, user.username, httponly=False, samesite="lax")
    users = [UserOut(**serialize_user(u)) for u in list_users(db)]
    return SessionOut(user=UserOut(**serialize_user(user)), users=users)
