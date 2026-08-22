"""인증/권한 의존성 (RBAC: ADMIN / MANAGER / SALES)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import Role
from app.core.security import decode_access_token
from app.models import AuditLog, User

bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "인증이 필요합니다.")
    payload = decode_access_token(creds.credentials)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "토큰이 유효하지 않거나 만료됐습니다.")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "사용할 수 없는 계정입니다.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[[User], User]:
    allowed = {str(r) for r in roles}

    def _dep(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "이 작업을 수행할 권한이 없습니다.")
        return user

    return _dep


ManagerUp = Annotated[User, Depends(require_roles(Role.ADMIN, Role.MANAGER))]
AdminOnly = Annotated[User, Depends(require_roles(Role.ADMIN))]


def is_manager_up(user: User) -> bool:
    return user.role in {Role.ADMIN, Role.MANAGER}


def write_audit(
    db: Session,
    user: User | None,
    action: str,
    *,
    target_type: str | None = None,
    target_id: int | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )
    )
