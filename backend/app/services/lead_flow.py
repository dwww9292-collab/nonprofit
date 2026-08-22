"""리드 상태 전이 규칙 (docs/02-enums.md 리드 상태 진입 조건)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import ActivityType, LeadStatus
from app.models import Activity, Lead, LeadSource, Source, User

CONTACT_TYPES = {ActivityType.CALL, ActivityType.VISIT, ActivityType.EMAIL, ActivityType.SMS}

# 수동 전환만 허용되는 상태
MANUAL_STATUSES = {LeadStatus.QUALIFIED, LeadStatus.LOST, LeadStatus.ON_HOLD, LeadStatus.CONTACTED}

# 자동 전이가 덮어써도 되는 상태 (담당자가 명시적으로 정한 상태는 보존)
AUTO_OVERRIDABLE = {LeadStatus.NEW, LeadStatus.ASSIGNED, LeadStatus.CONTACTED}


def assign_lead(db: Session, lead: Lead, assignee: User) -> None:
    lead.assignee_id = assignee.id
    lead.assigned_at = datetime.now(UTC)
    if lead.status == LeadStatus.NEW:
        lead.status = LeadStatus.ASSIGNED


def on_activity_created(lead: Lead, activity: Activity) -> None:
    """첫 접촉 활동 시 CONTACTED 전이 + first_contacted_at 기록."""
    if activity.type not in CONTACT_TYPES:
        return
    if lead.first_contacted_at is None:
        lead.first_contacted_at = activity.occurred_at
    if lead.status in {LeadStatus.NEW, LeadStatus.ASSIGNED}:
        lead.status = LeadStatus.CONTACTED


def on_deal_created(lead: Lead) -> None:
    """첫 딜 생성 시 CONVERTED 전이."""
    if lead.status in AUTO_OVERRIDABLE or lead.status == LeadStatus.QUALIFIED:
        lead.status = LeadStatus.CONVERTED


def lead_sources(db: Session, lead_id: int) -> list[Source]:
    return list(
        db.scalars(
            select(Source)
            .join(LeadSource, LeadSource.source_id == Source.id)
            .where(LeadSource.lead_id == lead_id)
            .distinct()
        ).all()
    )


def suggest_assignees(db: Session, lead: Lead, *, enabled: bool = True) -> list[dict]:
    """지역 기반 배정 '제안' (자동 배정 아님 — docs/05-screens.md 8)."""
    users = db.scalars(select(User).where(User.is_active.is_(True))).all()
    open_counts = dict(
        db.execute(
            select(Lead.assignee_id, func.count())
            .where(
                Lead.assignee_id.is_not(None),
                Lead.deleted_at.is_(None),
                Lead.status.notin_([LeadStatus.LOST, LeadStatus.CONVERTED]),
            )
            .group_by(Lead.assignee_id)
        ).all()
    )
    rows = []
    for u in users:
        match = bool(enabled and lead.region_code and u.region_codes and lead.region_code in u.region_codes)
        rows.append(
            {
                "user_id": u.id,
                "name": u.name,
                "region_match": match,
                "open_lead_count": int(open_counts.get(u.id, 0)),
            }
        )
    rows.sort(key=lambda r: (not r["region_match"], r["open_lead_count"], r["name"]))
    return rows
