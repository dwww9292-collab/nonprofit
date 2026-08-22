from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, or_, select

from app.api.deps import CurrentUser, DbSession, ManagerUp, is_manager_up, write_audit
from app.core.enums import REGION_CODES, AuditAction, LeadStatus
from app.ingest.pipeline import build_manual_candidate, create_lead_from_candidate
from app.models import Activity, AppSetting, Lead, Source, User
from app.schemas import (
    ActivityCreate,
    ActivityOut,
    AssigneeSuggestion,
    DupCandidate,
    DupCheckRequest,
    DupCheckResponse,
    LeadAssignRequest,
    LeadBulkStatusRequest,
    LeadCreateManual,
    LeadDetail,
    LeadListItem,
    LeadStatusUpdate,
    LeadUpdate,
    Page,
    SourceOut,
)
from app.services.dedup import find_duplicate, find_possible_duplicate, match_existing_customer
from app.services.lead_flow import (
    assign_lead,
    lead_sources,
    on_activity_created,
    suggest_assignees,
)
from app.services.normalize import (
    clean_biz_reg_no,
    clean_corp_reg_no,
    extract_district,
    extract_region_code,
    normalize_org_name,
)
from app.services.scoring import ScoringConfig, determine_stage_signal, score_lead

router = APIRouter(prefix="/leads", tags=["leads"])

RESCORE_FIELDS = {
    "org_type",
    "region_code",
    "asset_size",
    "homepage_url",
    "established_at",
    "designated_at",
}


def _to_list_item(lead: Lead) -> LeadListItem:
    item = LeadListItem.model_validate(lead)
    item.assignee_name = lead.assignee.name if lead.assignee else None
    item.source_code = lead.source.code if lead.source else None
    return item


def _apply_filters(
    stmt: Select,
    *,
    grade: list[str] | None,
    lead_status: list[str] | None,
    org_type: list[str] | None,
    region_code: str | None,
    source_code: str | None,
    assignee_id: int | None,
    unassigned: bool,
    collected_from: date | None,
    collected_to: date | None,
    include_customers: bool,
    only_possible_dup: bool,
    q: str | None,
) -> Select:
    stmt = stmt.where(Lead.deleted_at.is_(None))
    if not include_customers:
        stmt = stmt.where(Lead.is_existing_customer.is_(False))
    if grade:
        stmt = stmt.where(Lead.grade.in_(grade))
    if lead_status:
        stmt = stmt.where(Lead.status.in_(lead_status))
    if org_type:
        stmt = stmt.where(Lead.org_type.in_(org_type))
    if region_code:
        stmt = stmt.where(Lead.region_code == region_code)
    if source_code:
        stmt = stmt.join(Source, Source.id == Lead.source_id).where(Source.code == source_code)
    if unassigned:
        stmt = stmt.where(Lead.assignee_id.is_(None))
    elif assignee_id:
        stmt = stmt.where(Lead.assignee_id == assignee_id)
    if collected_from:
        stmt = stmt.where(Lead.collected_at >= datetime.combine(collected_from, datetime.min.time()))
    if collected_to:
        stmt = stmt.where(Lead.collected_at <= datetime.combine(collected_to, datetime.max.time()))
    if only_possible_dup:
        stmt = stmt.where(Lead.possible_dup_lead_id.is_not(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Lead.org_name.ilike(like),
                Lead.org_name_norm.ilike(f"%{normalize_org_name(q)}%"),
                Lead.address.ilike(like),
            )
        )
    return stmt


SORTABLE = {
    "score": Lead.score,
    "collected_at": Lead.collected_at,
    "org_name": Lead.org_name,
    "grade": Lead.grade,
    "status": Lead.status,
    "established_at": Lead.established_at,
}


@router.get("", response_model=Page[LeadListItem])
def list_leads(
    db: DbSession,
    user: CurrentUser,
    grade: Annotated[list[str] | None, Query()] = None,
    lead_status: Annotated[list[str] | None, Query(alias="status")] = None,
    org_type: Annotated[list[str] | None, Query()] = None,
    region_code: str | None = None,
    source_code: str | None = None,
    assignee_id: int | None = None,
    unassigned: bool = False,
    collected_from: date | None = None,
    collected_to: date | None = None,
    include_customers: bool = False,
    only_possible_dup: bool = False,
    q: str | None = None,
    sort: str = "score",
    order: str = "desc",
    page: int = 1,
    size: int = Query(50, le=200),
) -> Page[LeadListItem]:
    stmt = _apply_filters(
        select(Lead),
        grade=grade,
        lead_status=lead_status,
        org_type=org_type,
        region_code=region_code,
        source_code=source_code,
        assignee_id=assignee_id,
        unassigned=unassigned,
        collected_from=collected_from,
        collected_to=collected_to,
        include_customers=include_customers,
        only_possible_dup=only_possible_dup,
        q=q,
    )
    count_stmt = stmt.with_only_columns(func.count(Lead.id)).order_by(None)
    total = db.scalar(count_stmt) or 0

    col = SORTABLE.get(sort, Lead.score)
    primary = col.desc() if order == "desc" else col.asc()
    # 기본 정렬: 점수 내림차순 → 수집일 최신순 (docs/05-screens.md 3)
    stmt = stmt.order_by(primary, Lead.collected_at.desc()).offset((page - 1) * size).limit(size)
    items = [_to_list_item(x) for x in db.scalars(stmt).unique().all()]
    return Page(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_leads(
    db: DbSession,
    user: ManagerUp,
    grade: Annotated[list[str] | None, Query()] = None,
    lead_status: Annotated[list[str] | None, Query(alias="status")] = None,
    org_type: Annotated[list[str] | None, Query()] = None,
    region_code: str | None = None,
    source_code: str | None = None,
    assignee_id: int | None = None,
    unassigned: bool = False,
    collected_from: date | None = None,
    collected_to: date | None = None,
    include_customers: bool = False,
    only_possible_dup: bool = False,
    q: str | None = None,
) -> StreamingResponse:
    """현재 필터 결과 CSV 내보내기 (ADMIN·MANAGER, audit_logs에 EXPORT 기록)."""
    stmt = _apply_filters(
        select(Lead),
        grade=grade,
        lead_status=lead_status,
        org_type=org_type,
        region_code=region_code,
        source_code=source_code,
        assignee_id=assignee_id,
        unassigned=unassigned,
        collected_from=collected_from,
        collected_to=collected_to,
        include_customers=include_customers,
        only_possible_dup=only_possible_dup,
        q=q,
    ).order_by(Lead.score.desc(), Lead.collected_at.desc())
    leads = db.scalars(stmt).unique().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["등급", "점수", "법인명", "유형", "시도", "시군구", "주소", "대표자", "전화", "이메일",
         "홈페이지", "설립일", "지정일", "주무관청", "상태", "담당자", "소스", "수집일", "기고객"]
    )
    for x in leads:
        writer.writerow(
            [
                x.grade, x.score, x.org_name, x.org_type,
                REGION_CODES.get(x.region_code or "", ""), x.district or "", x.address or "",
                x.representative or "", x.phone or "", x.email or "", x.homepage_url or "",
                x.established_at or "", x.designated_at or "", x.authority or "", x.status,
                x.assignee.name if x.assignee else "", x.source.code if x.source else "",
                x.collected_at.strftime("%Y-%m-%d"), "Y" if x.is_existing_customer else "N",
            ]
        )
    write_audit(db, user, AuditAction.EXPORT, target_type="LEAD", detail={"count": len(leads)})
    db.commit()

    content = "﻿" + buf.getvalue()  # 엑셀 한글 깨짐 방지용 BOM
    filename = f"leads_{datetime.now(UTC).strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/dup-check", response_model=DupCheckResponse)
def dup_check(payload: DupCheckRequest, db: DbSession, user: CurrentUser) -> DupCheckResponse:
    """수기입력 폼 실시간 중복검사 (docs/04-data-sources.md 소스 3)."""
    from app.services.dedup import LeadCandidate

    address = payload.address
    cand = LeadCandidate(
        org_name=payload.org_name,
        org_name_norm=normalize_org_name(payload.org_name),
        corp_reg_no=clean_corp_reg_no(payload.corp_reg_no),
        biz_reg_no=clean_biz_reg_no(payload.biz_reg_no),
        region_code=extract_region_code(address),
        district=extract_district(address),
        address=address,
    )

    def _brief(lead: Lead, reason: str) -> DupCandidate:
        return DupCandidate(
            lead_id=lead.id,
            org_name=lead.org_name,
            address=lead.address,
            region_code=lead.region_code,
            status=lead.status,
            assignee_name=lead.assignee.name if lead.assignee else None,
            match_reason=reason,
        )

    match = find_duplicate(db, cand)
    similar = find_possible_duplicate(db, cand)
    return DupCheckResponse(
        exact=_brief(match.lead, match.reason) if match.lead else None,
        similar=[_brief(similar, "SIMILAR_NAME_DISTRICT")] if similar and similar is not match.lead else [],
        existing_customer=match_existing_customer(db, cand) is not None,
    )


@router.post("", response_model=LeadDetail, status_code=status.HTTP_201_CREATED)
def create_lead(payload: LeadCreateManual, db: DbSession, user: CurrentUser) -> LeadDetail:
    src = db.scalars(select(Source).where(Source.code == payload.source_code)).first()
    if src is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"등록되지 않은 소스입니다: {payload.source_code}")
    if src.collect_method != "MANUAL":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "수기입력은 MANUAL 계열 소스만 선택할 수 있습니다.")

    try:
        cand = build_manual_candidate(payload.model_dump(), payload.source_code)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    match = find_duplicate(db, cand)
    if match.lead is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"이미 등록된 리드입니다 (사유: {match.reason}, lead_id={match.lead.id}).",
        )

    customer = match_existing_customer(db, cand)
    cfg = ScoringConfig.load(db)
    lead = create_lead_from_candidate(db, cand, src, cfg, is_existing_customer=customer is not None)
    possible = find_possible_duplicate(db, cand)
    if possible is not None and possible.id != lead.id:
        lead.possible_dup_lead_id = possible.id
    from app.models import LeadSource

    db.add(LeadSource(lead_id=lead.id, source_id=src.id, batch_id=None))
    write_audit(
        db, user, AuditAction.UPDATE_LEAD, target_type="LEAD", target_id=lead.id,
        detail={"manual": True},
    )
    db.commit()
    return _to_detail(db, lead)


def _to_detail(db: DbSession, lead: Lead) -> LeadDetail:
    detail = LeadDetail.model_validate(lead)
    detail.assignee_name = lead.assignee.name if lead.assignee else None
    detail.source_code = lead.source.code if lead.source else None
    detail.sources = [SourceOut.model_validate(s) for s in lead_sources(db, lead.id)]
    return detail


def _get_lead(db: DbSession, lead_id: int) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None or lead.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "리드를 찾을 수 없습니다.")
    return lead


def _assert_can_edit(user: User, lead: Lead) -> None:
    if is_manager_up(user):
        return
    if lead.assignee_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "본인 담당 리드만 수정할 수 있습니다.")


@router.get("/{lead_id}", response_model=LeadDetail)
def get_lead(lead_id: int, db: DbSession, user: CurrentUser) -> LeadDetail:
    lead = _get_lead(db, lead_id)
    # 대표자 성명 등 개인정보 열람 추적 (CLAUDE.md 개발 규칙)
    write_audit(db, user, AuditAction.VIEW_LEAD_DETAIL, target_type="LEAD", target_id=lead.id)
    db.commit()
    return _to_detail(db, lead)


@router.patch("/{lead_id}", response_model=LeadDetail)
def update_lead(lead_id: int, payload: LeadUpdate, db: DbSession, user: CurrentUser) -> LeadDetail:
    lead = _get_lead(db, lead_id)
    _assert_can_edit(user, lead)

    data = payload.model_dump(exclude_unset=True)
    if "corp_reg_no" in data:
        data["corp_reg_no"] = clean_corp_reg_no(data["corp_reg_no"])
    if "biz_reg_no" in data:
        data["biz_reg_no"] = clean_biz_reg_no(data["biz_reg_no"])
    if "org_name" in data and data["org_name"]:
        lead.org_name_norm = normalize_org_name(data["org_name"])
    if "address" in data and data["address"] and "region_code" not in data:
        data["region_code"] = extract_region_code(data["address"])
        data["district"] = extract_district(data["address"])

    for key, value in data.items():
        setattr(lead, key, value)

    if RESCORE_FIELDS & set(data):
        lead.stage_signal = determine_stage_signal(lead.established_at, lead.designated_at, lead.collected_at)
        score_lead(db, lead, reference=lead.collected_at)
        if lead.is_existing_customer:
            lead.score, lead.grade = 0, "D"

    write_audit(db, user, AuditAction.UPDATE_LEAD, target_type="LEAD", target_id=lead.id, detail=list(data))
    db.commit()
    return _to_detail(db, lead)


@router.patch("/{lead_id}/status", response_model=LeadDetail)
def update_status(lead_id: int, payload: LeadStatusUpdate, db: DbSession, user: CurrentUser) -> LeadDetail:
    lead = _get_lead(db, lead_id)
    _assert_can_edit(user, lead)
    if payload.status == LeadStatus.LOST and payload.lost_reason is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "실패 처리에는 사유가 필요합니다.")
    lead.status = payload.status
    lead.lost_reason = payload.lost_reason if payload.status == LeadStatus.LOST else None
    if payload.memo:
        lead.memo = f"{lead.memo}\n{payload.memo}" if lead.memo else payload.memo
    write_audit(
        db, user, AuditAction.UPDATE_LEAD, target_type="LEAD", target_id=lead.id,
        detail={"status": payload.status, "lost_reason": payload.lost_reason},
    )
    db.commit()
    return _to_detail(db, lead)


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(lead_id: int, db: DbSession, user: ManagerUp) -> None:
    lead = _get_lead(db, lead_id)
    lead.deleted_at = datetime.now(UTC)
    write_audit(db, user, AuditAction.DELETE_LEAD, target_type="LEAD", target_id=lead.id)
    db.commit()


@router.get("/{lead_id}/assignee-suggestions", response_model=list[AssigneeSuggestion])
def assignee_suggestions(lead_id: int, db: DbSession, user: ManagerUp) -> list[AssigneeSuggestion]:
    lead = _get_lead(db, lead_id)
    setting = db.scalars(select(AppSetting).where(AppSetting.key == "region_assignment_suggestion")).first()
    enabled = bool(setting.value.get("enabled", True)) if setting else True
    return [AssigneeSuggestion(**row) for row in suggest_assignees(db, lead, enabled=enabled)]


@router.post("/assign", response_model=list[LeadListItem])
def assign_leads(payload: LeadAssignRequest, db: DbSession, user: ManagerUp) -> list[LeadListItem]:
    assignee = db.get(User, payload.assignee_id)
    if assignee is None or not assignee.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "배정 대상 사용자를 찾을 수 없습니다.")
    updated = []
    for lead_id in payload.lead_ids:
        lead = _get_lead(db, lead_id)
        assign_lead(db, lead, assignee)
        write_audit(
            db, user, AuditAction.ASSIGN_LEAD, target_type="LEAD", target_id=lead.id,
            detail={"assignee_id": assignee.id},
        )
        updated.append(lead)
    db.commit()
    return [_to_list_item(x) for x in updated]


@router.post("/bulk-status", response_model=list[LeadListItem])
def bulk_status(payload: LeadBulkStatusRequest, db: DbSession, user: ManagerUp) -> list[LeadListItem]:
    if payload.status == LeadStatus.LOST and payload.lost_reason is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "실패 처리에는 사유가 필요합니다.")
    updated = []
    for lead_id in payload.lead_ids:
        lead = _get_lead(db, lead_id)
        lead.status = payload.status
        lead.lost_reason = payload.lost_reason if payload.status == LeadStatus.LOST else None
        updated.append(lead)
    write_audit(
        db, user, AuditAction.UPDATE_LEAD, target_type="LEAD",
        detail={"bulk": payload.lead_ids, "status": payload.status},
    )
    db.commit()
    return [_to_list_item(x) for x in updated]


# --- 활동기록 ---


@router.get("/{lead_id}/activities", response_model=list[ActivityOut])
def list_activities(lead_id: int, db: DbSession, user: CurrentUser) -> list[ActivityOut]:
    _get_lead(db, lead_id)
    rows = db.scalars(
        select(Activity).where(Activity.lead_id == lead_id).order_by(Activity.occurred_at.desc())
    ).unique().all()
    out = []
    for a in rows:
        item = ActivityOut.model_validate(a)
        item.actor_name = a.actor.name if a.actor else None
        out.append(item)
    return out


@router.post("/{lead_id}/activities", response_model=ActivityOut, status_code=status.HTTP_201_CREATED)
def create_activity(
    lead_id: int, payload: ActivityCreate, db: DbSession, user: CurrentUser
) -> ActivityOut:
    lead = _get_lead(db, lead_id)
    activity = Activity(
        lead_id=lead.id,
        deal_id=payload.deal_id,
        type=payload.type,
        summary=payload.summary,
        next_action=payload.next_action,
        next_action_at=payload.next_action_at,
        actor_id=user.id,
        occurred_at=payload.occurred_at or datetime.now(UTC),
    )
    db.add(activity)
    db.flush()
    on_activity_created(lead, activity)
    db.commit()
    out = ActivityOut.model_validate(activity)
    out.actor_name = user.name
    return out


@router.get("/meta/sources", response_model=list[SourceOut])
def manual_sources(db: DbSession, user: CurrentUser) -> list[SourceOut]:
    """수기입력 폼용 MANUAL 소스 목록."""
    rows = db.scalars(
        select(Source)
        .where(Source.collect_method == "MANUAL", Source.is_active.is_(True))
        .order_by(Source.id)
    ).all()
    return [SourceOut.model_validate(s) for s in rows]
