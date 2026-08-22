"""중복 판정 / 병합 / 기고객 매칭 (docs/01-schema.md 하단 규칙)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.core.enums import REGION_UNKNOWN, AssetSize, OrgType, SourceCode, StageSignal
from app.models import ExistingCustomer, Lead
from app.services.normalize import legal_form_from_name

# 유사도 중복의심 임계값 (자동병합 아님 — 배지 표시만)
SIMILARITY_THRESHOLD = 0.9

# designated_at / asset_size를 덮어써도 되는 고신뢰 소스
TRUSTED_SOURCES = {SourceCode.MOEF_DESIGNATION, SourceCode.HOMETAX}

# 병합 시 "빈 값이면 채운다" 대상 필드
FILLABLE_FIELDS = (
    "corp_reg_no",
    "biz_reg_no",
    "region_code",
    "district",
    "address",
    "representative",
    "phone",
    "email",
    "homepage_url",
    "established_at",
    "designated_at",
    "purpose",
    "authority",
    "memo",
)


@dataclass
class LeadCandidate:
    """파서/수기입력이 만들어내는 정제 완료 리드 후보."""

    org_name: str
    org_name_norm: str
    org_type: str = OrgType.ETC
    corp_reg_no: str | None = None
    biz_reg_no: str | None = None
    region_code: str | None = None
    district: str | None = None
    address: str | None = None
    representative: str | None = None
    phone: str | None = None
    email: str | None = None
    homepage_url: str | None = None
    established_at: date | None = None
    designated_at: date | None = None
    purpose: str | None = None
    authority: str | None = None
    memo: str | None = None
    asset_size: str = AssetSize.UNKNOWN
    stage_signal: str = StageSignal.UNKNOWN
    source_code: str = SourceCode.MANUAL
    collected_at: datetime | None = None
    raw: dict = field(default_factory=dict)

    @property
    def match_key(self) -> str:
        """배치 간 diff 비교 키: 법인등록번호 우선, 없으면 정규화명+정규화주소."""
        if self.corp_reg_no:
            return f"C:{self.corp_reg_no}"
        from app.services.normalize import normalize_address

        return f"N:{self.org_name_norm}|{normalize_address(self.address)}"


@dataclass
class DedupMatch:
    lead: Lead | None
    reason: str | None  # CORP_REG_NO / BIZ_REG_NO / NAME_REGION / None


def find_duplicate(db: Session, cand: LeadCandidate) -> DedupMatch:
    """중복 판정 1~3단계. 일치 시 병합 대상 리드 반환."""
    base = select(Lead).where(Lead.deleted_at.is_(None))

    if cand.corp_reg_no:
        lead = db.scalars(base.where(Lead.corp_reg_no == cand.corp_reg_no)).first()
        if lead:
            return DedupMatch(lead, "CORP_REG_NO")

    if cand.biz_reg_no:
        lead = db.scalars(base.where(Lead.biz_reg_no == cand.biz_reg_no)).first()
        if lead:
            return DedupMatch(lead, "BIZ_REG_NO")

    if cand.org_name_norm:
        # 지역 '99'(미상)는 지역 정보가 없다는 뜻이므로 불일치로 취급하지 않는다.
        # 기재부 지정누계에는 주소 열이 아예 없어(실측) 전 건이 99다. 지역 일치를 강제하면
        # 같은 단체가 소스별로 갈라진다 — 실제 파일에서 1,314개 단체 2,650건이 그랬다.
        stmt = base.where(Lead.org_name_norm == cand.org_name_norm)
        known = cand.region_code and cand.region_code != REGION_UNKNOWN
        if known:
            stmt = stmt.where(
                or_(
                    Lead.region_code == cand.region_code,
                    Lead.region_code == REGION_UNKNOWN,
                    Lead.region_code.is_(None),
                )
            )
            # 지역이 정확히 맞는 리드를 우선 선택
            stmt = stmt.order_by((Lead.region_code == cand.region_code).desc(), Lead.id)
        else:
            stmt = stmt.order_by(Lead.id)
        candidates = db.scalars(stmt).all()
        cand_form = legal_form_from_name(cand.org_name)
        for lead in candidates:
            # 정규화가 법인격 접두어를 지우므로 "(사)함양군장학회"와 "(재)함양군장학회"가
            # 같은 키가 된다. 실제로는 별개 법인이므로, 양쪽 명칭에 법인격이 명시돼 있고
            # 서로 다르면 병합하지 않는다 (기재부 지정누계 실데이터에서 확인된 사례).
            # 한쪽에 표기가 없으면 같은 법인의 다른 표기로 보고 병합한다.
            lead_form = legal_form_from_name(lead.org_name)
            if cand_form and lead_form and cand_form != lead_form:
                continue
            return DedupMatch(lead, "NAME_REGION")

    return DedupMatch(None, None)


def find_possible_duplicate(db: Session, cand: LeadCandidate) -> Lead | None:
    """중복 판정 4단계: 유사도 ≥ 0.9 AND 시군구 일치 → 자동병합하지 않고 의심 표시만."""
    if not cand.org_name_norm or not cand.district:
        return None
    row = db.execute(
        text(
            """
            SELECT id
              FROM leads
             WHERE deleted_at IS NULL
               AND district = :district
               AND similarity(org_name_norm, :norm) >= :threshold
             ORDER BY similarity(org_name_norm, :norm) DESC
             LIMIT 1
            """
        ),
        {"district": cand.district, "norm": cand.org_name_norm, "threshold": SIMILARITY_THRESHOLD},
    ).first()
    if not row:
        return None
    return db.get(Lead, row[0])


def match_existing_customer(db: Session, cand: LeadCandidate) -> ExistingCustomer | None:
    """기고객 필터: 중복 판정과 동일한 키 순서로 대조."""
    if cand.corp_reg_no:
        hit = db.scalars(
            select(ExistingCustomer).where(ExistingCustomer.corp_reg_no == cand.corp_reg_no)
        ).first()
        if hit:
            return hit
    if cand.biz_reg_no:
        hit = db.scalars(
            select(ExistingCustomer).where(ExistingCustomer.biz_reg_no == cand.biz_reg_no)
        ).first()
        if hit:
            return hit
    if cand.org_name_norm:
        stmt = select(ExistingCustomer).where(ExistingCustomer.org_name_norm == cand.org_name_norm)
        if cand.region_code:
            hit = db.scalars(stmt.where(ExistingCustomer.region_code == cand.region_code)).first()
            if hit:
                return hit
        # 기고객 명단에 지역이 비어 있는 경우까지 커버
        hit = db.scalars(stmt.where(ExistingCustomer.region_code.is_(None))).first()
        if hit:
            return hit
    return None


def merge_candidate_into_lead(lead: Lead, cand: LeadCandidate) -> list[str]:
    """병합 규칙: 기존 빈 필드만 채움. designated_at/asset_size는 고신뢰 소스면 갱신.

    반환값: 실제로 변경된 필드명 목록.
    """
    changed: list[str] = []
    trusted = cand.source_code in TRUSTED_SOURCES

    for fname in FILLABLE_FIELDS:
        new_val = getattr(cand, fname)
        if new_val in (None, ""):
            continue
        if fname == "region_code" and new_val == REGION_UNKNOWN:
            continue
        cur_val = getattr(lead, fname)
        # region_code의 '99'는 값이 아니라 '정보 없음'이므로 빈 칸으로 본다
        if fname == "region_code" and cur_val == REGION_UNKNOWN:
            cur_val = None
        if cur_val in (None, ""):
            setattr(lead, fname, new_val)
            changed.append(fname)
        elif trusted and fname == "designated_at" and cur_val != new_val:
            setattr(lead, fname, new_val)
            changed.append(fname)

    if trusted and cand.asset_size != AssetSize.UNKNOWN and lead.asset_size != cand.asset_size:
        lead.asset_size = cand.asset_size
        changed.append("asset_size")

    # 유형이 미상이었다면 더 구체적인 값으로 승격
    if lead.org_type == OrgType.ETC and cand.org_type != OrgType.ETC:
        lead.org_type = cand.org_type
        changed.append("org_type")

    return changed
