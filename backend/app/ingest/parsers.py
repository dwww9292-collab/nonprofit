"""소스별 파서 (docs/04-data-sources.md).

각 파서는 parse(content, file_name) -> ParseResult 와
to_candidate(row) -> LeadCandidate 를 제공한다.
크롤러 커넥터도 동일 인터페이스로 붙일 수 있게 클래스로 분리.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.enums import REGION_UNKNOWN, OrgType, SourceCode
from app.ingest.base import ParseResult, RawRow, parse_table
from app.services.dedup import LeadCandidate
from app.services.normalize import (
    clean_biz_reg_no,
    clean_corp_reg_no,
    clean_text,
    extract_district,
    extract_region_code,
    guess_org_type,
    normalize_org_name,
    normalize_url,
    parse_date,
)


class BaseFileParser:
    source_code: str = SourceCode.MANUAL
    required_fields: list[str] = ["org_name"]
    preferred_sheet_keywords: tuple[str, ...] = ()
    #: 여러 시트로 쪼개진 파일이면 모두 합친다
    merge_all_sheets: bool = False
    #: 이 소스가 강제하는 org_type (None이면 명칭에서 추정)
    forced_org_type: str | None = None

    def parse(self, content: bytes, file_name: str) -> ParseResult:
        return parse_table(
            content,
            file_name,
            required=self.required_fields,
            preferred_sheet_keywords=self.preferred_sheet_keywords,
            merge_all_sheets=self.merge_all_sheets,
        )

    def to_candidate(
        self,
        row: RawRow,
        *,
        collected_at: datetime | None = None,
        region_override: str | None = None,
    ) -> LeadCandidate:
        f = row.fields
        org_name = clean_text(f.get("org_name"), 200)
        if not org_name:
            raise ValueError("법인명/단체명이 비어 있습니다.")

        address = clean_text(f.get("address"), 300)
        region_code = extract_region_code(address)
        if region_code == "99" and region_override:
            region_code = region_override
        district = extract_district(address)

        org_type = self.forced_org_type or guess_org_type(org_name, default=OrgType.ETC)

        return LeadCandidate(
            org_name=org_name,
            org_name_norm=normalize_org_name(org_name),
            org_type=org_type,
            corp_reg_no=clean_corp_reg_no(clean_text(f.get("corp_reg_no"))),
            biz_reg_no=clean_biz_reg_no(clean_text(f.get("biz_reg_no"))),
            region_code=region_code,
            district=district,
            address=address,
            representative=clean_text(f.get("representative"), 50),
            phone=clean_text(f.get("phone"), 30),
            email=clean_text(f.get("email"), 255),
            homepage_url=normalize_url(f.get("homepage_url")),
            established_at=parse_date(f.get("established_at")),
            designated_at=parse_date(f.get("designated_at")),
            purpose=clean_text(f.get("purpose")),
            authority=clean_text(f.get("authority"), 100),
            source_code=self.source_code,
            collected_at=collected_at or datetime.now(UTC),
            raw=row.payload,
        )


class MoefDesignationParser(BaseFileParser):
    """소스 1: 기재부 공익법인 지정누계 xlsx.

    지정 명단이므로 designated_at이 있으면 공익법인으로 본다.
    """

    source_code = SourceCode.MOEF_DESIGNATION
    required_fields = ["org_name"]
    # 실제 파일 시트명은 "2026.2분기 기준" 형태이고 "지정누계"가 아니다 (samples 실측)
    preferred_sheet_keywords = ("누계", "분기", "기준")

    def to_candidate(self, row: RawRow, **kwargs) -> LeadCandidate:
        cand = super().to_candidate(row, **kwargs)
        # 명칭에서 재단/사단이 확인되면 그 유형을 유지하고, 미상이면 공익법인으로 승격
        if cand.org_type == OrgType.ETC:
            cand.org_type = OrgType.PUBLIC_INTEREST
        return cand


class DataGoKrNpoParser(BaseFileParser):
    """소스 2: 공공데이터포털 비영리민간단체 등록현황.

    법인 전환 확인 전까지 org_type은 ORG_NPO_GROUP 고정.
    """

    source_code = SourceCode.DATA_GO_KR_NPO
    required_fields = ["org_name"]
    # 행안부 원본은 '중앙'/'시도' 두 시트로 나뉘어 있어 둘 다 읽어야 한다 (samples 실측)
    merge_all_sheets = True
    forced_org_type = OrgType.NPO_GROUP

    def to_candidate(self, row: RawRow, **kwargs) -> LeadCandidate:
        cand = super().to_candidate(row, **kwargs)

        # 원본에 '유형' 열이 있으면(사단법인/재단법인 등) 그 사실을 우선한다.
        # 비어 있을 때만 ORG_NPO_GROUP으로 남긴다.
        declared = clean_text(row.payload.get("유형"))
        if declared:
            guessed = guess_org_type(declared, default=OrgType.ETC)
            if guessed != OrgType.ETC:
                cand.org_type = guessed

        # 주소가 시군구부터 시작해 시도를 못 잡는 행이 19% 있었다 (실측).
        # 등록기관은 관할 지자체이므로 지역 보정에 쓸 수 있다.
        if cand.region_code == REGION_UNKNOWN:
            hinted = extract_region_code(clean_text(row.payload.get("등록기관")))
            if hinted != REGION_UNKNOWN:
                cand.region_code = hinted
        return cand


PARSERS: dict[str, BaseFileParser] = {
    SourceCode.MOEF_DESIGNATION: MoefDesignationParser(),
    SourceCode.DATA_GO_KR_NPO: DataGoKrNpoParser(),
}


def get_parser(source_code: str) -> BaseFileParser:
    parser = PARSERS.get(source_code)
    if parser is None:
        raise ValueError(f"파일 업로드를 지원하지 않는 소스입니다: {source_code}")
    return parser


# --- 기고객 명단 (리드가 아니라 existing_customers 로 들어감) ---

EXISTING_CUSTOMER_REQUIRED = ["org_name"]


def parse_existing_customers(content: bytes, file_name: str) -> ParseResult:
    return parse_table(content, file_name, required=EXISTING_CUSTOMER_REQUIRED)
