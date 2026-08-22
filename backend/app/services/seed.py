"""시드: 소스 / 스코어링 설정 / 앱 설정 / 관리자 계정."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import SOURCE_SEED, Role
from app.core.security import hash_password
from app.models import AppSetting, ScoringSetting, Source, User
from app.services.scoring import SCORING_SEED

APP_SETTING_DEFAULTS: dict[str, dict] = {
    # docs/05-screens.md 8. 설정 > 배정 규칙
    "region_assignment_suggestion": {"enabled": True},
}


def seed_sources(db: Session) -> int:
    created = 0
    for code, name, method in SOURCE_SEED:
        src = db.scalars(select(Source).where(Source.code == code)).first()
        if src is None:
            db.add(Source(code=code, name=name, collect_method=method, is_active=True))
            created += 1
        else:
            src.name = name
            src.collect_method = method
    db.flush()
    return created


def seed_scoring(db: Session, *, overwrite: bool = False) -> int:
    """배점 시드. 관리자가 수정한 값은 overwrite=False면 보존한다."""
    created = 0
    for rule_key, points, description, value_json in SCORING_SEED:
        row = db.scalars(select(ScoringSetting).where(ScoringSetting.rule_key == rule_key)).first()
        if row is None:
            db.add(
                ScoringSetting(
                    rule_key=rule_key, points=points, description=description, value_json=value_json
                )
            )
            created += 1
        elif overwrite:
            row.points = points
            row.description = description
            row.value_json = value_json
    db.flush()
    return created


def seed_app_settings(db: Session) -> int:
    created = 0
    for key, value in APP_SETTING_DEFAULTS.items():
        row = db.scalars(select(AppSetting).where(AppSetting.key == key)).first()
        if row is None:
            db.add(AppSetting(key=key, value=value))
            created += 1
    db.flush()
    return created


def ensure_admin(db: Session, email: str | None = None, password: str | None = None) -> User:
    email = email or settings.admin_email
    password = password or settings.admin_password
    user = db.scalars(select(User).where(User.email == email)).first()
    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="시스템 관리자",
            role=Role.ADMIN,
            is_active=True,
        )
        db.add(user)
        db.flush()
    return user


def seed_all(db: Session) -> dict[str, int]:
    return {
        "sources": seed_sources(db),
        "scoring_settings": seed_scoring(db),
        "app_settings": seed_app_settings(db),
    }
