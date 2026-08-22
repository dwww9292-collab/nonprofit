"""리드 스코어링 v1 (docs/03-scoring.md). 배점은 전부 scoring_settings 테이블에서 읽는다."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AssetSize, OrgType, StageSignal
from app.models import Lead, ScoringSetting

# --- stage_signal 판정 기준일수 (docs/02-enums.md) ---
NEW_PERMIT_DAYS = 90
NEW_DESIGNATION_DAYS = 180
RECENT_DAYS = 365

# --- 신선도 구간 (docs/03-scoring.md 5) ---
FRESHNESS_BANDS: list[tuple[int | None, str]] = [
    (7, "FRESH.7D"),
    (30, "FRESH.30D"),
    (90, "FRESH.90D"),
    (None, "FRESH.OLD"),
]

# --- 등급 컷 (docs/02-enums.md 리드 등급) ---
GRADE_A, GRADE_B, GRADE_C = 85, 70, 55

STAGE_RULES = {
    StageSignal.NEW_DESIGNATION: "STAGE.NEW_DESIGNATION",
    StageSignal.NEW_PERMIT: "STAGE.NEW_PERMIT",
    StageSignal.RECENT: "STAGE.RECENT",
    StageSignal.MATURE: "STAGE.MATURE",
    StageSignal.UNKNOWN: "STAGE.UNKNOWN",
}
TYPE_RULES = {
    OrgType.FOUNDATION: "TYPE.FOUNDATION",
    OrgType.PUBLIC_INTEREST: "TYPE.PUBLIC_INTEREST",
    OrgType.ASSOCIATION: "TYPE.ASSOCIATION",
    OrgType.SOCIAL_WELFARE: "TYPE.SOCIAL_WELFARE",
    OrgType.NPO_GROUP: "TYPE.NPO_GROUP",
    OrgType.RELIGIOUS: "TYPE.RELIGIOUS",
    OrgType.ETC: "TYPE.ETC",
}
ASSET_RULES = {
    AssetSize.LARGE: "ASSET.LARGE",
    AssetSize.MID: "ASSET.MID",
    AssetSize.SMALL: "ASSET.SMALL",
    AssetSize.UNKNOWN: "ASSET.UNKNOWN",
}

# rule_key, points, description, value_json — 시드 정본 (docs/03-scoring.md v1)
SCORING_SEED: list[tuple[str, int, str, dict | None]] = [
    ("STAGE.NEW_DESIGNATION", 30, "공익법인 신규 지정 직후(180일 이내)", None),
    ("STAGE.NEW_PERMIT", 30, "설립허가/등록 직후(90일 이내)", None),
    ("STAGE.RECENT", 15, "설립/지정 1년 이내", None),
    ("STAGE.MATURE", 5, "설립/지정 1년 초과", None),
    ("STAGE.UNKNOWN", 10, "일자 정보 없음", None),
    ("TYPE.FOUNDATION", 20, "재단법인", None),
    ("TYPE.PUBLIC_INTEREST", 18, "공익법인", None),
    ("TYPE.ASSOCIATION", 18, "사단법인", None),
    ("TYPE.SOCIAL_WELFARE", 16, "사회복지법인", None),
    ("TYPE.NPO_GROUP", 12, "비영리민간단체", None),
    ("TYPE.RELIGIOUS", 4, "종교단체", None),
    ("TYPE.ETC", 8, "기타/미상", None),
    ("ASSET.LARGE", 20, "총자산 100억 이상", None),
    ("ASSET.MID", 15, "총자산 5억~100억", None),
    ("ASSET.SMALL", 8, "총자산 5억 미만", None),
    ("ASSET.UNKNOWN", 8, "자산규모 미상(기본값)", None),
    ("REGION.CORE", 15, "핵심 지역(서울·경기·인천)", {"codes": ["11", "41", "28"]}),
    ("REGION.METRO", 10, "광역시·세종", {"codes": ["26", "27", "29", "30", "31", "36"]}),
    ("REGION.OTHER", 6, "그 외 지역", None),
    ("REGION.UNKNOWN", 6, "지역 미상", None),
    ("FRESH.7D", 15, "수집 7일 이내", None),
    ("FRESH.30D", 10, "수집 30일 이내", None),
    ("FRESH.90D", 5, "수집 90일 이내", None),
    ("FRESH.OLD", 2, "수집 90일 초과", None),
    ("PENALTY.HAS_HOMEPAGE", -5, "홈페이지 보유(홈페이지 수요 낮음 신호)", None),
]


class ScoringConfig:
    """scoring_settings 스냅샷. 리드 여러 건을 채점할 때 재조회를 피한다."""

    def __init__(self, points: dict[str, int], values: dict[str, dict | None]):
        self.points = points
        self.values = values

    @classmethod
    def load(cls, db: Session) -> ScoringConfig:
        rows = db.scalars(select(ScoringSetting)).all()
        points = {r.rule_key: r.points for r in rows}
        values = {r.rule_key: r.value_json for r in rows}
        # 설정이 비어 있어도(시드 이전) 계산이 죽지 않도록 기본값으로 보충
        for key, pts, _desc, val in SCORING_SEED:
            points.setdefault(key, pts)
            values.setdefault(key, val)
        return cls(points, values)

    def p(self, rule_key: str) -> int:
        return int(self.points.get(rule_key, 0))

    def codes(self, rule_key: str) -> list[str]:
        v = self.values.get(rule_key) or {}
        return list(v.get("codes", []))


def _as_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


def determine_stage_signal(
    established_at: date | None,
    designated_at: date | None,
    reference: datetime | date | None = None,
) -> str:
    """docs/02-enums.md 설립단계 신호 판정. 두 조건 충족 시 NEW_DESIGNATION 우선."""
    ref = _as_date(reference) or datetime.now(UTC).date()
    est = _as_date(established_at)
    des = _as_date(designated_at)

    if des is not None and 0 <= (ref - des).days <= NEW_DESIGNATION_DAYS:
        return StageSignal.NEW_DESIGNATION
    if est is not None and 0 <= (ref - est).days <= NEW_PERMIT_DAYS:
        return StageSignal.NEW_PERMIT

    latest = max([d for d in (est, des) if d is not None], default=None)
    if latest is None:
        return StageSignal.UNKNOWN
    days = (ref - latest).days
    if days <= RECENT_DAYS:
        return StageSignal.RECENT
    return StageSignal.MATURE


def freshness_rule(collected_at: datetime | date | None, reference: datetime | date | None = None) -> str:
    ref = _as_date(reference) or datetime.now(UTC).date()
    col = _as_date(collected_at)
    if col is None:
        return "FRESH.OLD"
    days = (ref - col).days
    for limit, rule in FRESHNESS_BANDS:
        if limit is None or days <= limit:
            return rule
    return "FRESH.OLD"


def region_rule(cfg: ScoringConfig, region_code: str | None) -> str:
    code = region_code or "99"
    if code == "99":
        return "REGION.UNKNOWN"
    if code in cfg.codes("REGION.CORE"):
        return "REGION.CORE"
    if code in cfg.codes("REGION.METRO"):
        return "REGION.METRO"
    return "REGION.OTHER"


def grade_for(score: int, is_existing_customer: bool = False) -> str:
    """PENALTY.EXISTING_CUSTOMER: 기고객은 점수 무관 강제 D."""
    if is_existing_customer:
        return "D"
    if score >= GRADE_A:
        return "A"
    if score >= GRADE_B:
        return "B"
    if score >= GRADE_C:
        return "C"
    return "D"


def compute_score(
    cfg: ScoringConfig,
    *,
    stage_signal: str,
    org_type: str,
    asset_size: str,
    region_code: str | None,
    collected_at: datetime | date | None,
    homepage_url: str | None,
    is_existing_customer: bool = False,
    reference: datetime | date | None = None,
) -> tuple[int, str, dict]:
    """(score, grade, breakdown) 반환. breakdown은 leads.score_breakdown에 저장."""
    breakdown: dict[str, int] = {}

    stage_key = STAGE_RULES.get(stage_signal, "STAGE.UNKNOWN")
    type_key = TYPE_RULES.get(org_type, "TYPE.ETC")
    asset_key = ASSET_RULES.get(asset_size, "ASSET.UNKNOWN")
    region_key = region_rule(cfg, region_code)
    fresh_key = freshness_rule(collected_at, reference)

    for key in (stage_key, type_key, asset_key, region_key, fresh_key):
        breakdown[key] = cfg.p(key)

    penalty = cfg.p("PENALTY.HAS_HOMEPAGE") if homepage_url else 0
    breakdown["PENALTY.HAS_HOMEPAGE"] = penalty

    total = sum(breakdown.values())
    total = max(0, min(100, total))
    breakdown["total"] = total

    return total, grade_for(total, is_existing_customer), breakdown


def score_lead(db_or_cfg, lead: Lead, reference: datetime | date | None = None) -> Lead:
    """리드 1건 채점 후 필드 갱신. db 세션 또는 ScoringConfig 둘 다 받는다."""
    cfg = db_or_cfg if isinstance(db_or_cfg, ScoringConfig) else ScoringConfig.load(db_or_cfg)
    score, grade, breakdown = compute_score(
        cfg,
        stage_signal=lead.stage_signal,
        org_type=lead.org_type,
        asset_size=lead.asset_size,
        region_code=lead.region_code,
        collected_at=lead.collected_at,
        homepage_url=lead.homepage_url,
        is_existing_customer=lead.is_existing_customer,
        reference=reference,
    )
    lead.score = score
    lead.grade = grade
    lead.score_breakdown = breakdown
    return lead


def rescore_all(db: Session, reference: datetime | date | None = None) -> int:
    """관리자 '전체 재계산'. stage_signal도 함께 재판정한다."""
    cfg = ScoringConfig.load(db)
    leads = db.scalars(select(Lead).where(Lead.deleted_at.is_(None))).all()
    for lead in leads:
        lead.stage_signal = determine_stage_signal(
            lead.established_at, lead.designated_at, reference or lead.collected_at
        )
        score_lead(cfg, lead, reference)
    db.flush()
    return len(leads)
