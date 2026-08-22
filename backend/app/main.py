from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import admin, auth, dashboard, deals, ingest, leads, performance
from app.core.config import settings
from app.core.enums import (
    REGION_CODES,
    ActivityType,
    AssetSize,
    DealStage,
    LeadStatus,
    LostReason,
    OrgType,
    ProductCode,
    Role,
    StageSignal,
)

app = FastAPI(
    title="NPO Sales Radar API",
    description="신규 비영리기구 리드 발굴 + 영업 파이프라인 관리 (아이원소프트뱅크 내부용)",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api/v1")
api.include_router(auth.router)
api.include_router(leads.router)
api.include_router(deals.router)
api.include_router(ingest.router)
api.include_router(dashboard.router)
api.include_router(performance.router)
api.include_router(admin.router)


@api.get("/meta/enums", tags=["meta"])
def enums() -> dict:
    """프론트 드롭다운용 코드/표시명 (docs/02-enums.md 단일 출처)."""
    return {
        "roles": [{"code": r, "label": lbl} for r, lbl in
                  [(Role.ADMIN, "관리자"), (Role.MANAGER, "팀장"), (Role.SALES, "영업사원")]],
        "org_types": [
            {"code": OrgType.FOUNDATION, "label": "재단법인"},
            {"code": OrgType.ASSOCIATION, "label": "사단법인"},
            {"code": OrgType.PUBLIC_INTEREST, "label": "공익법인"},
            {"code": OrgType.NPO_GROUP, "label": "비영리민간단체"},
            {"code": OrgType.SOCIAL_WELFARE, "label": "사회복지법인"},
            {"code": OrgType.RELIGIOUS, "label": "종교단체"},
            {"code": OrgType.ETC, "label": "기타/미상"},
        ],
        "lead_statuses": [
            {"code": LeadStatus.NEW, "label": "신규"},
            {"code": LeadStatus.ASSIGNED, "label": "배정됨"},
            {"code": LeadStatus.CONTACTED, "label": "접촉"},
            {"code": LeadStatus.QUALIFIED, "label": "유효확인"},
            {"code": LeadStatus.CONVERTED, "label": "딜 전환"},
            {"code": LeadStatus.LOST, "label": "실패/제외"},
            {"code": LeadStatus.ON_HOLD, "label": "보류/육성"},
        ],
        "deal_stages": [
            {"code": DealStage.CONTACT, "label": "접촉"},
            {"code": DealStage.MEETING, "label": "미팅"},
            {"code": DealStage.PROPOSAL, "label": "제안"},
            {"code": DealStage.NEGOTIATION, "label": "협상"},
            {"code": DealStage.WON, "label": "계약"},
            {"code": DealStage.LOST, "label": "실패"},
        ],
        "products": [
            {"code": ProductCode.AMARANTH10, "label": "아마란스10 ERP"},
            {"code": ProductCode.WEHAGO, "label": "위하고"},
            {"code": ProductCode.HOMEPAGE, "label": "홈페이지 구축"},
            {"code": ProductCode.SI, "label": "SI/PMS 등 커스텀 개발"},
            {"code": ProductCode.BUNDLE_ERP_HP, "label": "설립초기 번들 (ERP+홈페이지)"},
        ],
        "lost_reasons": [
            {"code": LostReason.COMPETITOR, "label": "타사 솔루션 기도입/선택"},
            {"code": LostReason.NO_BUDGET, "label": "예산 없음"},
            {"code": LostReason.NO_NEED, "label": "니즈 없음"},
            {"code": LostReason.NO_CONTACT, "label": "연락 불가/두절"},
            {"code": LostReason.DISSOLVED, "label": "해산/폐업/활동중단"},
            {"code": LostReason.DUPLICATE, "label": "중복 리드"},
            {"code": LostReason.ETC, "label": "기타 (메모 필수)"},
        ],
        "activity_types": [
            {"code": ActivityType.CALL, "label": "전화"},
            {"code": ActivityType.VISIT, "label": "방문/미팅"},
            {"code": ActivityType.EMAIL, "label": "이메일"},
            {"code": ActivityType.SMS, "label": "문자"},
            {"code": ActivityType.NOTE, "label": "메모"},
        ],
        "asset_sizes": [
            {"code": AssetSize.LARGE, "label": "100억 이상"},
            {"code": AssetSize.MID, "label": "5억~100억"},
            {"code": AssetSize.SMALL, "label": "5억 미만"},
            {"code": AssetSize.UNKNOWN, "label": "미상"},
        ],
        "stage_signals": [
            {"code": StageSignal.NEW_PERMIT, "label": "설립 직후"},
            {"code": StageSignal.NEW_DESIGNATION, "label": "신규 지정"},
            {"code": StageSignal.RECENT, "label": "1년 이내"},
            {"code": StageSignal.MATURE, "label": "1년 초과"},
            {"code": StageSignal.UNKNOWN, "label": "일자 미상"},
        ],
        "regions": [{"code": c, "label": n} for c, n in REGION_CODES.items()],
        # 리드 상세의 외부 검증 링크 (자동조회 아님 — 단순 링크)
        "external_links": [
            {"code": "IROS", "label": "인터넷등기소에서 확인", "url": "https://www.iros.go.kr"},
            {"code": "HOMETAX", "label": "홈택스 공시 확인", "url": "https://www.hometax.go.kr"},
        ],
    }


app.include_router(api)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}
