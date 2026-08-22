"""설정 화면 API: 스코어링 가중치 / 사용자 / 소스 / 배정 규칙 (docs/05-screens.md 8)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import AdminOnly, CurrentUser, DbSession, ManagerUp, write_audit
from app.core.enums import AuditAction, Role
from app.core.security import hash_password
from app.models import AppSetting, ScoringSetting, Source, User
from app.schemas import (
    AppSettingOut,
    RescoreResponse,
    ScoringSettingOut,
    ScoringSettingUpdate,
    SourceOut,
    SourceUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services.scoring import rescore_all

router = APIRouter(prefix="/settings", tags=["settings"])


# --- 스코어링 가중치 ---


@router.get("/scoring", response_model=list[ScoringSettingOut])
def list_scoring(db: DbSession, user: ManagerUp) -> list[ScoringSettingOut]:
    rows = db.scalars(select(ScoringSetting).order_by(ScoringSetting.rule_key)).all()
    return [ScoringSettingOut.model_validate(r) for r in rows]


@router.patch("/scoring/{rule_key}", response_model=ScoringSettingOut)
def update_scoring(
    rule_key: str, payload: ScoringSettingUpdate, db: DbSession, user: AdminOnly
) -> ScoringSettingOut:
    row = db.scalars(select(ScoringSetting).where(ScoringSetting.rule_key == rule_key)).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"알 수 없는 규칙입니다: {rule_key}")
    data = payload.model_dump(exclude_unset=True)
    if "points" in data and data["points"] is not None:
        row.points = data["points"]
    if "value_json" in data:
        row.value_json = data["value_json"]
    write_audit(db, user, AuditAction.UPDATE_SCORING, target_type="SCORING", target_id=row.id, detail=data)
    db.commit()
    return ScoringSettingOut.model_validate(row)


@router.post("/scoring/rescore", response_model=RescoreResponse)
def rescore(db: DbSession, user: AdminOnly) -> RescoreResponse:
    """전체 재계산 (docs/03-scoring.md 재계산 트리거)."""
    updated = rescore_all(db)
    write_audit(db, user, AuditAction.RESCORE_ALL, detail={"updated": updated})
    db.commit()
    return RescoreResponse(updated=updated)


# --- 사용자 관리 ---


@router.get("/users", response_model=list[UserOut])
def list_users(db: DbSession, user: CurrentUser) -> list[UserOut]:
    rows = db.scalars(select(User).order_by(User.is_active.desc(), User.name)).all()
    return [UserOut.model_validate(u) for u in rows]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: DbSession, user: AdminOnly) -> UserOut:
    if db.scalars(select(User).where(User.email == str(payload.email))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 등록된 이메일입니다.")
    new = User(
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        name=payload.name,
        role=payload.role,
        region_codes=payload.region_codes,
        is_active=True,
    )
    db.add(new)
    db.commit()
    return UserOut.model_validate(new)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: DbSession, user: AdminOnly) -> UserOut:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다.")
    data = payload.model_dump(exclude_unset=True)
    if data.pop("password", None):
        target.password_hash = hash_password(payload.password)
    if target.id == user.id and data.get("is_active") is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "본인 계정은 비활성화할 수 없습니다.")
    if target.role == Role.ADMIN and data.get("role") and data["role"] != Role.ADMIN:
        remaining = db.scalars(
            select(User).where(User.role == Role.ADMIN, User.is_active.is_(True), User.id != target.id)
        ).first()
        if remaining is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "마지막 관리자 계정의 롤은 변경할 수 없습니다.")
    for key, value in data.items():
        setattr(target, key, value)
    if data.get("is_active") is True:
        target.failed_login_count, target.locked_until = 0, None
    db.commit()
    return UserOut.model_validate(target)


# --- 소스 관리 ---


@router.get("/sources", response_model=list[SourceOut])
def list_sources(db: DbSession, user: CurrentUser) -> list[SourceOut]:
    rows = db.scalars(select(Source).order_by(Source.id)).all()
    return [SourceOut.model_validate(s) for s in rows]


@router.patch("/sources/{source_id}", response_model=SourceOut)
def update_source(source_id: int, payload: SourceUpdate, db: DbSession, user: AdminOnly) -> SourceOut:
    src = db.get(Source, source_id)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "소스를 찾을 수 없습니다.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(src, key, value)
    db.commit()
    return SourceOut.model_validate(src)


# --- 앱 설정 (배정 규칙 등) ---


@router.get("/app", response_model=list[AppSettingOut])
def list_app_settings(db: DbSession, user: CurrentUser) -> list[AppSettingOut]:
    rows = db.scalars(select(AppSetting).order_by(AppSetting.key)).all()
    return [AppSettingOut.model_validate(r) for r in rows]


@router.put("/app/{key}", response_model=AppSettingOut)
def update_app_setting(key: str, value: dict, db: DbSession, user: AdminOnly) -> AppSettingOut:
    row = db.scalars(select(AppSetting).where(AppSetting.key == key)).first()
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
    return AppSettingOut.model_validate(row)
