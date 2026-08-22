from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, is_manager_up
from app.core.enums import ActivityType, DealStage
from app.models import Activity, Deal, Lead, User
from app.schemas import PerformanceResponse, PerformanceRow, ProductSummary

router = APIRouter(prefix="/performance", tags=["performance"])


def _period_bounds(period: str, year: int, unit: int) -> tuple[datetime, datetime, str]:
    if period == "quarter":
        start = datetime(year, 3 * (unit - 1) + 1, 1, tzinfo=UTC)
        end = datetime(year + (unit == 4), (3 * unit) % 12 + 1, 1, tzinfo=UTC)
        return start, end, f"{year}Q{unit}"
    start = datetime(year, unit, 1, tzinfo=UTC)
    end = datetime(year + (unit == 12), unit % 12 + 1, 1, tzinfo=UTC)
    return start, end, f"{year}-{unit:02d}"


@router.get("", response_model=PerformanceResponse)
def performance(
    db: DbSession,
    user: CurrentUser,
    period: str = Query("month", pattern="^(month|quarter)$"),
    year: int | None = None,
    unit: int | None = None,
) -> PerformanceResponse:
    now = datetime.now(UTC)
    year = year or now.year
    unit = unit or (now.month if period == "month" else (now.month - 1) // 3 + 1)
    start, end, label = _period_bounds(period, year, unit)

    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name)).all()
    if not is_manager_up(user):
        users = [u for u in users if u.id == user.id]
    user_ids = [u.id for u in users]

    assigned = dict(
        db.execute(
            select(Lead.assignee_id, func.count())
            .where(Lead.deleted_at.is_(None), Lead.assignee_id.in_(user_ids), Lead.assigned_at >= start,
                   Lead.assigned_at < end)
            .group_by(Lead.assignee_id)
        ).all()
    )
    contacted = dict(
        db.execute(
            select(Lead.assignee_id, func.count())
            .where(Lead.deleted_at.is_(None), Lead.assignee_id.in_(user_ids),
                   Lead.first_contacted_at >= start, Lead.first_contacted_at < end)
            .group_by(Lead.assignee_id)
        ).all()
    )
    avg_hours = dict(
        db.execute(
            select(
                Lead.assignee_id,
                func.avg(func.extract("epoch", Lead.first_contacted_at - Lead.assigned_at) / 3600.0),
            )
            .where(
                Lead.deleted_at.is_(None), Lead.assignee_id.in_(user_ids),
                Lead.first_contacted_at.is_not(None), Lead.assigned_at.is_not(None),
                Lead.first_contacted_at >= start, Lead.first_contacted_at < end,
            )
            .group_by(Lead.assignee_id)
        ).all()
    )
    meetings = dict(
        db.execute(
            select(Activity.actor_id, func.count())
            .where(Activity.actor_id.in_(user_ids), Activity.type == ActivityType.VISIT,
                   Activity.occurred_at >= start, Activity.occurred_at < end)
            .group_by(Activity.actor_id)
        ).all()
    )
    proposals = dict(
        db.execute(
            select(Deal.owner_id, func.count())
            .where(Deal.owner_id.in_(user_ids), Deal.stage.in_([DealStage.PROPOSAL, DealStage.NEGOTIATION,
                   DealStage.WON]), Deal.updated_at >= start, Deal.updated_at < end)
            .group_by(Deal.owner_id)
        ).all()
    )
    won = {
        oid: (int(c), int(a))
        for oid, c, a in db.execute(
            select(Deal.owner_id, func.count(), func.coalesce(func.sum(Deal.amount), 0))
            .where(Deal.owner_id.in_(user_ids), Deal.stage == DealStage.WON,
                   Deal.closed_at >= start, Deal.closed_at < end)
            .group_by(Deal.owner_id)
        ).all()
    }

    rows = []
    for u in users:
        a_cnt = int(assigned.get(u.id, 0))
        c_cnt = int(contacted.get(u.id, 0))
        w_cnt, w_amt = won.get(u.id, (0, 0))
        avg = avg_hours.get(u.id)
        rows.append(
            PerformanceRow(
                user_id=u.id,
                name=u.name,
                assigned_leads=a_cnt,
                contacted_leads=c_cnt,
                contact_rate=round(c_cnt / a_cnt * 100, 1) if a_cnt else 0.0,
                meetings=int(meetings.get(u.id, 0)),
                proposals=int(proposals.get(u.id, 0)),
                won_count=w_cnt,
                won_amount=w_amt,
                avg_first_contact_hours=round(float(avg), 1) if avg is not None else None,
            )
        )

    product_stmt = (
        select(Deal.product_code, func.count(), func.coalesce(func.sum(Deal.amount), 0))
        .where(Deal.stage == DealStage.WON, Deal.closed_at >= start, Deal.closed_at < end)
        .group_by(Deal.product_code)
    )
    if not is_manager_up(user):
        product_stmt = product_stmt.where(Deal.owner_id == user.id)

    return PerformanceResponse(
        period_label=label,
        rows=rows,
        product_summary=[
            ProductSummary(product_code=str(p), count=int(c), amount=int(a))
            for p, c, a in db.execute(product_stmt).all()
        ],
    )
