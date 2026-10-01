"""데모 데이터 (리드 30건 + 사용자/딜/활동). 운영 시드와 분리 — --demo 옵션에서만 실행."""

from __future__ import annotations

import os
import random
import secrets
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import (
    ActivityType,
    AssetSize,
    DealStage,
    LeadStatus,
    OrgType,
    ProductCode,
    Role,
    SourceCode,
)
from app.core.security import hash_password
from app.models import Activity, Deal, Lead, LeadSource, Source, User
from app.services.lead_flow import assign_lead, on_activity_created, on_deal_created
from app.services.normalize import extract_district, extract_region_code, normalize_org_name
from app.services.scoring import ScoringConfig, determine_stage_signal, score_lead

DEMO_USERS = [
    ("manager@ionesoftbank.co.kr", "팀장 김수현", Role.MANAGER, ["11", "41", "28"]),
    ("sales1@ionesoftbank.co.kr", "영업 박지훈", Role.SALES, ["11"]),
    ("sales2@ionesoftbank.co.kr", "영업 이서연", Role.SALES, ["41", "28"]),
    ("sales3@ionesoftbank.co.kr", "영업 최민호", Role.SALES, ["26", "48"]),
]

PREFIXES = ["재단법인", "사단법인", "사회복지법인", ""]
KEYWORDS = [
    "한빛나눔", "푸른내일", "행복드림", "미래희망", "새싹돌봄", "온기나눔", "하늘사랑", "밝은세상",
    "다솜복지", "이음문화", "초록지구", "가온누리", "한마음후원", "열린배움", "참좋은이웃",
]
SUFFIXES = ["재단", "협회", "회", "센터", "복지회"]

ADDRESSES = [
    ("서울특별시 종로구 세종대로 1", "기획재정부"),
    ("서울특별시 마포구 월드컵북로 100", "문화체육관광부"),
    ("서울특별시 강남구 테헤란로 500", "보건복지부"),
    ("경기도 성남시 분당구 판교로 200", "경기도"),
    ("경기도 고양시 일산동구 중앙로 1036", "경기도"),
    ("인천광역시 남동구 정각로 29", "인천광역시"),
    ("부산광역시 해운대구 센텀로 30", "부산광역시"),
    ("대전광역시 서구 둔산로 100", "대전광역시"),
    ("경상남도 창원시 의창구 중앙대로 300", "경상남도"),
    ("강원특별자치도 춘천시 중앙로 1", "강원특별자치도"),
]

HOT_LEAD_COUNT = 3

ACTIVITY_SUMMARIES = [
    "첫 통화 — 담당자 연결",
    "설립 초기 ERP 니즈 확인",
    "홈페이지 구축 견적 문의",
    "방문 미팅 진행",
]

ORG_TYPES = [
    OrgType.FOUNDATION,
    OrgType.ASSOCIATION,
    OrgType.SOCIAL_WELFARE,
    OrgType.NPO_GROUP,
    OrgType.PUBLIC_INTEREST,
]


def create_demo_users(db: Session, password: str | None = None) -> tuple[list[User], str]:
    """데모 계정 생성. 비밀번호는 DEMO_PASSWORD 환경변수, 없으면 임의 생성해 함께 반환한다."""
    password = password or os.getenv("DEMO_PASSWORD") or secrets.token_urlsafe(12)
    users = []
    for email, name, role, regions in DEMO_USERS:
        user = db.scalars(select(User).where(User.email == email)).first()
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(password),
                name=name,
                role=role,
                region_codes=regions,
                is_active=True,
            )
            db.add(user)
        users.append(user)
    db.flush()
    return users, password


def _free_corp_reg_no(db: Session, rng: random.Random) -> str | None:
    """아직 쓰이지 않은 13자리 법인등록번호를 고른다.

    번호를 순번으로 만들면 --demo를 두 번 돌릴 때 유니크 제약에 걸린다.
    """
    for _ in range(50):
        candidate = f"1101110{rng.randint(0, 999999):06d}"
        if db.scalars(select(Lead).where(Lead.corp_reg_no == candidate)).first() is None:
            return candidate
    return None


def create_demo_leads(db: Session, count: int = 30, seed: int = 20260822) -> list[Lead]:
    rng = random.Random(seed)
    cfg = ScoringConfig.load(db)
    now = datetime.now(UTC)
    sources = {s.code: s for s in db.scalars(select(Source)).all()}
    leads: list[Lead] = []

    # 앞의 HOT_LEAD_COUNT건은 대시보드 '즉시 배정 필요' 위젯이 비지 않도록 A등급으로 고정 생성
    for i in range(count):
        hot = i < HOT_LEAD_COUNT
        name = f"{rng.choice(PREFIXES)} {rng.choice(KEYWORDS)}{rng.choice(SUFFIXES)}".strip()
        if db.scalars(select(Lead).where(Lead.org_name == name)).first():
            name = f"{name}{i}"
        address, authority = ADDRESSES[i % 3] if hot else rng.choice(ADDRESSES)
        source_code = (
            SourceCode.MOEF_DESIGNATION
            if hot
            else rng.choice(
                [
                    SourceCode.MOEF_DESIGNATION,
                    SourceCode.DATA_GO_KR_NPO,
                    SourceCode.LOCAL_GOV,
                    SourceCode.MANUAL,
                ]
            )
        )
        source = sources[source_code]

        collected = now - timedelta(days=rng.randint(0, 5) if hot else rng.randint(0, 120))
        base: date = collected.date() - timedelta(days=rng.randint(0, 30) if hot else rng.randint(0, 500))
        designated = base if source_code == SourceCode.MOEF_DESIGNATION else None
        established = base if designated is None else base - timedelta(days=rng.randint(0, 400))

        lead = Lead(
            org_name=name,
            org_name_norm=normalize_org_name(name),
            org_type=(
                OrgType.FOUNDATION
                if hot
                else (
                    OrgType.NPO_GROUP
                    if source_code == SourceCode.DATA_GO_KR_NPO
                    else rng.choice(ORG_TYPES)
                )
            ),
            corp_reg_no=_free_corp_reg_no(db, rng) if rng.random() < 0.7 else None,
            region_code=extract_region_code(address),
            district=extract_district(address),
            address=address,
            representative=f"{rng.choice('김이박최정강조윤장임')}{rng.choice('민서지우현준도윤')}",
            phone=f"0{rng.randint(2, 64)}-{rng.randint(200, 999)}-{rng.randint(1000, 9999)}",
            homepage_url=None if hot else ("https://example.or.kr" if rng.random() < 0.25 else None),
            established_at=established,
            designated_at=designated,
            purpose="지역사회 복지 증진 및 문화예술 지원 사업",
            authority=authority,
            asset_size=(
                AssetSize.LARGE
                if hot
                else rng.choice(
                    [AssetSize.UNKNOWN, AssetSize.UNKNOWN, AssetSize.SMALL, AssetSize.MID, AssetSize.LARGE]
                )
            ),
            source_id=source.id,
            collected_at=collected,
        )
        lead.stage_signal = determine_stage_signal(established, designated, collected)
        score_lead(cfg, lead, reference=now)
        db.add(lead)
        db.flush()
        db.add(LeadSource(lead_id=lead.id, source_id=source.id, batch_id=None))
        leads.append(lead)

    return leads


def create_demo_pipeline(db: Session, leads: list[Lead], users: list[User], seed: int = 20260822) -> None:
    rng = random.Random(seed + 1)
    sales = [u for u in users if u.role == Role.SALES]
    if not sales:
        return
    now = datetime.now(UTC)

    for idx, lead in enumerate(leads):
        if idx < HOT_LEAD_COUNT:
            continue  # A등급 미배정 상태로 남겨 '즉시 배정 필요' 위젯을 채운다
        if rng.random() < 0.35:
            continue  # 미배정 리드도 남겨 대시보드 위젯이 의미를 갖도록
        owner = rng.choice(sales)
        assign_lead(db, lead, owner)
        lead.assigned_at = now - timedelta(days=rng.randint(0, 30))

        if rng.random() < 0.65:
            act = Activity(
                lead_id=lead.id,
                type=rng.choice([ActivityType.CALL, ActivityType.EMAIL, ActivityType.VISIT]),
                summary=rng.choice(ACTIVITY_SUMMARIES),
                next_action=rng.choice(["제안서 발송", "재통화", "견적 재산출", None]),
                next_action_at=now + timedelta(days=rng.randint(-3, 14)),
                actor_id=owner.id,
                occurred_at=lead.assigned_at + timedelta(days=rng.randint(0, 5)),
            )
            db.add(act)
            db.flush()
            on_activity_created(lead, act)

            if rng.random() < 0.5:
                stage = rng.choice(
                    [DealStage.CONTACT, DealStage.MEETING, DealStage.PROPOSAL,
                     DealStage.NEGOTIATION, DealStage.WON, DealStage.LOST]
                )
                deal = Deal(
                    lead_id=lead.id,
                    product_code=rng.choice(list(ProductCode)),
                    stage=stage,
                    amount=rng.choice([5, 8, 12, 20, 25, 40]) * 1_000_000,
                    probability=rng.choice([20, 40, 60, 80, 100]),
                    expected_close=(now + timedelta(days=rng.randint(10, 90))).date(),
                    owner_id=owner.id,
                )
                if stage in (DealStage.WON, DealStage.LOST):
                    deal.closed_at = now - timedelta(days=rng.randint(0, 40))
                if stage == DealStage.LOST:
                    deal.lost_reason = "LOST_NO_BUDGET"
                db.add(deal)
                db.flush()
                on_deal_created(lead)
        elif rng.random() < 0.3:
            lead.status = LeadStatus.ON_HOLD

    db.flush()


def create_demo_data(db: Session, count: int = 30) -> dict:
    users, password = create_demo_users(db)
    leads = create_demo_leads(db, count)
    create_demo_pipeline(db, leads, users)
    return {"users": len(users), "leads": len(leads), "demo_password": password}
