from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, is_manager_up
from app.core.enums import DealStage, LeadStatus
from app.models import Activity, Deal, Lead, Source
from app.schemas import (
    DashboardLeadBrief,
    DashboardResponse,
    ProductSummary,
    StageSummary,
    WeeklyPoint,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

STALE_DAYS = 7
WEEKS = 12


def _quarter_bounds(now: datetime) -> tuple[datetime, datetime, str]:
    q = (now.month - 1) // 3 + 1
    start = datetime(now.year, 3 * (q - 1) + 1, 1, tzinfo=UTC)
    end = datetime(now.year + (q == 4), (3 * q) % 12 + 1, 1, tzinfo=UTC)
    return start, end, f"{now.year}Q{q}"


@router.get("", response_model=DashboardResponse)
def dashboard(db: DbSession, user: CurrentUser) -> DashboardResponse:
    now = datetime.now(UTC)
    mine_only = not is_manager_up(user)

    # 1. 즉시 배정 필요: A등급 & 미배정
    urgent_stmt = select(Lead).where(
        Lead.deleted_at.is_(None),
        Lead.is_existing_customer.is_(False),
        Lead.grade == "A",
        Lead.assignee_id.is_(None),
        Lead.status.notin_([LeadStatus.LOST, LeadStatus.ON_HOLD]),
    )
    urgent_count = db.scalar(urgent_stmt.with_only_columns(func.count(Lead.id))) or 0
    urgent = (
        db.scalars(urgent_stmt.order_by(Lead.score.desc(), Lead.collected_at.desc()).limit(5))
        .unique()
        .all()
    )

    # 2. 장기 미접촉: 배정 후 7일 경과 & 활동기록 0건
    cutoff = now - timedelta(days=STALE_DAYS)
    no_activity = ~select(Activity.id).where(Activity.lead_id == Lead.id).exists()
    stale_stmt = select(Lead).where(
        Lead.deleted_at.is_(None),
        Lead.assignee_id.is_not(None),
        Lead.assigned_at < cutoff,
        Lead.status.notin_([LeadStatus.LOST, LeadStatus.CONVERTED]),
        no_activity,
    )
    if mine_only:
        stale_stmt = stale_stmt.where(Lead.assignee_id == user.id)
    stale_rows = db.scalars(stale_stmt.order_by(Lead.assigned_at.asc())).unique().all()
    stale_top = stale_rows[:5]

    # 3. 최근 12주 주별 유입 (소스별)
    since = now - timedelta(weeks=WEEKS)
    week_expr = func.to_char(func.date_trunc("week", Lead.collected_at), "IYYY-IW")
    weekly_rows = db.execute(
        select(week_expr.label("week"), Source.code, func.count(Lead.id))
        .join(Source, Source.id == Lead.source_id)
        .where(Lead.deleted_at.is_(None), Lead.collected_at >= since)
        .group_by("week", Source.code)
        .order_by("week")
    ).all()

    # 4. 등급 분포
    grade_rows = db.execute(
        select(Lead.grade, func.count(Lead.id))
        .where(Lead.deleted_at.is_(None), Lead.is_existing_customer.is_(False))
        .group_by(Lead.grade)
    ).all()
    grade_dist = {g: 0 for g in "ABCD"}
    for g, c in grade_rows:
        grade_dist[g] = int(c)

    # 5. 파이프라인 요약
    pipe_stmt = (
        select(Deal.stage, func.count(Deal.id), func.coalesce(func.sum(Deal.amount), 0))
        .join(Lead, Lead.id == Deal.lead_id)
        .where(Lead.deleted_at.is_(None))
        .group_by(Deal.stage)
    )
    if mine_only:
        pipe_stmt = pipe_stmt.where(Deal.owner_id == user.id)
    pipe_map = {s: (int(c), int(a)) for s, c, a in db.execute(pipe_stmt).all()}
    pipeline = [
        StageSummary(stage=str(s), count=pipe_map.get(s, (0, 0))[0], amount=pipe_map.get(s, (0, 0))[1])
        for s in DealStage
    ]

    # 6. 이번 분기 수주
    q_start, q_end, q_label = _quarter_bounds(now)
    won_stmt = (
        select(Deal.product_code, func.count(Deal.id), func.coalesce(func.sum(Deal.amount), 0))
        .where(Deal.stage == DealStage.WON, Deal.closed_at >= q_start, Deal.closed_at < q_end)
        .group_by(Deal.product_code)
    )
    if mine_only:
        won_stmt = won_stmt.where(Deal.owner_id == user.id)
    quarter_won = [
        ProductSummary(product_code=str(p), count=int(c), amount=int(a))
        for p, c, a in db.execute(won_stmt).all()
    ]

    def _brief(lead: Lead) -> DashboardLeadBrief:
        return DashboardLeadBrief(
            id=lead.id,
            org_name=lead.org_name,
            score=lead.score,
            grade=lead.grade,
            collected_at=lead.collected_at,
            assignee_name=lead.assignee.name if lead.assignee else None,
            days_since_assigned=(now - lead.assigned_at).days if lead.assigned_at else None,
        )

    return DashboardResponse(
        urgent_unassigned_count=int(urgent_count),
        urgent_unassigned=[_brief(x) for x in urgent],
        stale_assigned_count=len(stale_rows),
        stale_assigned=[_brief(x) for x in stale_top],
        weekly_inflow=[WeeklyPoint(week=w, source_code=s, count=int(c)) for w, s, c in weekly_rows],
        grade_distribution=grade_dist,
        pipeline_summary=pipeline,
        quarter_won=quarter_won,
        quarter_label=q_label,
    )
