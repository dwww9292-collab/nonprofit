from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, is_manager_up
from app.core.enums import DealStage, Role
from app.models import Activity, Deal, Lead, User
from app.schemas import DealCreate, DealOut, DealUpdate
from app.services.lead_flow import on_deal_created

router = APIRouter(prefix="/deals", tags=["deals"])

CLOSED_STAGES = {DealStage.WON, DealStage.LOST}


def _to_out(db: DbSession, deal: Deal) -> DealOut:
    out = DealOut.model_validate(deal)
    out.lead_name = deal.lead.org_name if deal.lead else None
    out.owner_name = deal.owner.name if deal.owner else None
    out.next_action_at = db.scalar(
        select(func.min(Activity.next_action_at)).where(
            Activity.deal_id == deal.id, Activity.next_action_at.is_not(None)
        )
    )
    return out


def _get_deal(db: DbSession, deal_id: int) -> Deal:
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "딜을 찾을 수 없습니다.")
    return deal


def _assert_can_edit(user: User, deal: Deal) -> None:
    if is_manager_up(user) or deal.owner_id == user.id:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "본인 담당 딜만 수정할 수 있습니다.")


@router.get("", response_model=list[DealOut])
def list_deals(
    db: DbSession,
    user: CurrentUser,
    owner_id: int | None = None,
    product_code: str | None = None,
    amount_min: int | None = None,
    amount_max: int | None = None,
    lead_id: int | None = None,
) -> list[DealOut]:
    stmt = select(Deal).join(Lead, Lead.id == Deal.lead_id).where(Lead.deleted_at.is_(None))
    # SALES 기본값은 본인 (docs/05-screens.md 5)
    if owner_id is None and user.role == Role.SALES:
        owner_id = user.id
    if owner_id:
        stmt = stmt.where(Deal.owner_id == owner_id)
    if product_code:
        stmt = stmt.where(Deal.product_code == product_code)
    if amount_min is not None:
        stmt = stmt.where(Deal.amount >= amount_min)
    if amount_max is not None:
        stmt = stmt.where(Deal.amount <= amount_max)
    if lead_id:
        stmt = stmt.where(Deal.lead_id == lead_id)
    rows = db.scalars(stmt.order_by(Deal.updated_at.desc().nullslast(), Deal.id.desc())).unique().all()
    return [_to_out(db, d) for d in rows]


@router.post("", response_model=DealOut, status_code=status.HTTP_201_CREATED)
def create_deal(payload: DealCreate, db: DbSession, user: CurrentUser) -> DealOut:
    lead = db.get(Lead, payload.lead_id)
    if lead is None or lead.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "리드를 찾을 수 없습니다.")

    owner_id = payload.owner_id or lead.assignee_id or user.id
    if not is_manager_up(user) and owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "다른 사람에게 딜을 배정할 권한이 없습니다.")

    deal = Deal(
        lead_id=lead.id,
        product_code=payload.product_code,
        stage=payload.stage,
        amount=payload.amount,
        probability=payload.probability,
        expected_close=payload.expected_close,
        owner_id=owner_id,
    )
    if deal.stage in CLOSED_STAGES:
        deal.closed_at = datetime.now(UTC)
    db.add(deal)
    db.flush()
    on_deal_created(lead)
    db.commit()
    return _to_out(db, deal)


@router.patch("/{deal_id}", response_model=DealOut)
def update_deal(deal_id: int, payload: DealUpdate, db: DbSession, user: CurrentUser) -> DealOut:
    deal = _get_deal(db, deal_id)
    _assert_can_edit(user, deal)
    data = payload.model_dump(exclude_unset=True)

    new_stage = data.get("stage", deal.stage)
    if new_stage == DealStage.LOST and not (data.get("lost_reason") or deal.lost_reason):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "실패로 이동하려면 사유가 필요합니다.")

    for key, value in data.items():
        setattr(deal, key, value)

    if deal.stage in CLOSED_STAGES:
        deal.closed_at = deal.closed_at or datetime.now(UTC)
    else:
        deal.closed_at = None
        deal.lost_reason = None
    db.commit()
    return _to_out(db, deal)


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deal(deal_id: int, db: DbSession, user: CurrentUser) -> None:
    deal = _get_deal(db, deal_id)
    _assert_can_edit(user, deal)
    db.delete(deal)
    db.commit()
