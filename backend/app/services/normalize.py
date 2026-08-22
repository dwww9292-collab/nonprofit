"""명칭 정규화 / 지역·번호 파싱 유틸 (docs/01-schema.md 정규화 규칙)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from app.core.enums import REGION_UNKNOWN, OrgType

# 규칙 2: 제거 대상 접두/괄호 표기 (긴 것부터 매칭해야 부분매칭 사고가 없음)
LEGAL_PREFIXES: list[tuple[str, str | None]] = [
    ("사회복지법인", OrgType.SOCIAL_WELFARE),
    ("재단법인", OrgType.FOUNDATION),
    ("사단법인", OrgType.ASSOCIATION),
    ("학교법인", OrgType.ETC),
    ("의료법인", OrgType.ETC),
    ("비영리법인", None),
    ("(사복)", OrgType.SOCIAL_WELFARE),
    ("(재)", OrgType.FOUNDATION),
    ("(사)", OrgType.ASSOCIATION),
]

# 규칙 3: 제거 대상 특수문자
_PUNCT = "·.,-‐–—_'\"“”()［］[]〔〕{}<>《》「」『』/\\|:;!?~`^*+=@#$%&"
_PUNCT_RE = re.compile("[" + re.escape(_PUNCT) + "]")
_SPACE_RE = re.compile(r"\s+")

# 시도명 → 코드. 긴 표기부터 매칭.
_SIDO_PATTERNS: list[tuple[str, str]] = [
    ("서울특별시", "11"), ("서울시", "11"), ("서울", "11"),
    ("부산광역시", "26"), ("부산시", "26"), ("부산", "26"),
    ("대구광역시", "27"), ("대구시", "27"), ("대구", "27"),
    ("인천광역시", "28"), ("인천시", "28"), ("인천", "28"),
    ("광주광역시", "29"), ("광주시", "29"),
    ("대전광역시", "30"), ("대전시", "30"), ("대전", "30"),
    ("울산광역시", "31"), ("울산시", "31"), ("울산", "31"),
    ("세종특별자치시", "36"), ("세종시", "36"), ("세종", "36"),
    ("경기도", "41"), ("경기", "41"),
    ("강원특별자치도", "42"), ("강원도", "42"), ("강원", "42"),
    ("충청북도", "43"), ("충북", "43"),
    ("충청남도", "44"), ("충남", "44"),
    ("전북특별자치도", "45"), ("전라북도", "45"), ("전북", "45"),
    ("전라남도", "46"), ("전남", "46"),
    ("경상북도", "47"), ("경북", "47"),
    ("경상남도", "48"), ("경남", "48"),
    ("제주특별자치도", "50"), ("제주도", "50"), ("제주", "50"),
    # 특례시는 시도명 없이 단독 표기되는 경우가 많다 (행안부 등록기관 열 실측)
    ("수원특례시", "41"), ("화성특례시", "41"), ("용인특례시", "41"), ("고양특례시", "41"),
    ("창원특례시", "48"),
]
# "광주"는 경기도 광주시와 충돌하므로 광역시 표기가 명확할 때만 29로 본다.
_AMBIGUOUS_BARE = {"광주"}

_DISTRICT_RE = re.compile(r"([가-힣]+(?:시|군|구))")


def normalize_org_name(raw: str | None) -> str:
    """docs/01-schema.md 명칭 정규화 규칙 1~4."""
    if not raw:
        return ""
    # 3(전각→반각) 먼저 적용해야 전각 괄호로 감싼 접두어도 제거된다
    s = unicodedata.normalize("NFKC", str(raw))
    s = _SPACE_RE.sub(" ", s).strip()

    # 2: 접두/괄호 표기 제거 — 공백을 사이에 둔 표기도 함께 제거
    changed = True
    while changed:
        changed = False
        for prefix, _ in LEGAL_PREFIXES:
            for candidate in (prefix, prefix.replace("(", "（").replace(")", "）")):
                if s.startswith(candidate):
                    s = s[len(candidate):].strip()
                    changed = True
    for prefix, _ in LEGAL_PREFIXES:
        s = s.replace(prefix, "")

    s = _PUNCT_RE.sub("", s)
    s = s.lower()          # 4: 영문 소문자화
    s = re.sub(r"\s+", "", s)  # 1: 최종적으로 모든 공백 제거
    return s[:200]


def guess_org_type(raw_name: str | None, default: str = OrgType.ETC) -> str:
    """규칙 5: 제거된 접두어로 org_type 추정."""
    if not raw_name:
        return default
    s = unicodedata.normalize("NFKC", str(raw_name)).strip()
    for prefix, org_type in LEGAL_PREFIXES:
        if org_type and (s.startswith(prefix) or prefix in s):
            return org_type
    return default


# "(301-841)대전 중구 …" 처럼 앞에 붙는 우편번호 (행안부 파일 실측)
_ZIPCODE_PREFIX_RE = re.compile(r"^\(?\d{3}[-\s]?\d{2,3}\)?\s*")


# 명칭 접두어가 나타내는 법인격 그룹. 같은 이름이라도 그룹이 다르면 별개 법인이다.
_LEGAL_FORM_GROUPS: list[tuple[tuple[str, ...], str]] = [
    (("사회복지법인", "(사복)"), "SOCIAL_WELFARE"),
    (("재단법인", "(재)"), "FOUNDATION"),
    (("사단법인", "(사)"), "ASSOCIATION"),
    (("학교법인",), "SCHOOL"),
    (("의료법인",), "MEDICAL"),
]


def legal_form_from_name(raw_name: str | None) -> str | None:
    """명칭에 실제로 표기된 법인격 그룹. 표기가 없으면 None.

    org_type과 달리 '소스 기본값'이 섞이지 않으므로, 중복 판정에서
    "(사)함양군장학회 vs (재)함양군장학회"처럼 서로 다른 법인을 가려내는 데 쓴다.
    """
    if not raw_name:
        return None
    s = unicodedata.normalize("NFKC", str(raw_name)).strip()
    for prefixes, group in _LEGAL_FORM_GROUPS:
        for prefix in prefixes:
            if s.startswith(prefix) or prefix in s:
                return group
    return None


def extract_region_code(address: str | None) -> str:
    """주소(또는 등록기관명) 앞부분에서 시도 코드 추출. 실패 시 '99'."""
    if not address:
        return REGION_UNKNOWN
    s = unicodedata.normalize("NFKC", str(address)).strip()
    s = _ZIPCODE_PREFIX_RE.sub("", s)
    head = s[:12]
    for name, code in _SIDO_PATTERNS:
        if head.startswith(name):
            if name in _AMBIGUOUS_BARE:
                continue
            return code
    # 앞부분 매칭 실패 시 문자열 전체에서 명확한 표기만 재탐색
    for name, code in _SIDO_PATTERNS:
        if len(name) >= 3 and name in s:
            return code
    return REGION_UNKNOWN


def extract_district(address: str | None) -> str | None:
    """시군구명 추출 (시도명 제거 후 첫 시/군/구 토큰)."""
    if not address:
        return None
    s = _ZIPCODE_PREFIX_RE.sub("", unicodedata.normalize("NFKC", str(address)).strip())
    for name, _ in _SIDO_PATTERNS:
        if s.startswith(name):
            s = s[len(name):].strip()
            break
    m = _DISTRICT_RE.search(s)
    return m.group(1) if m else None


def normalize_address(address: str | None) -> str:
    """diff 매칭 키용 주소 정규화 (공백/특수문자 제거)."""
    if not address:
        return ""
    s = unicodedata.normalize("NFKC", str(address))
    s = _PUNCT_RE.sub("", s)
    return re.sub(r"\s+", "", s).lower()


def clean_reg_no(value: str | None, length: int) -> str | None:
    """법인등록번호(13)/사업자·고유번호(10): 숫자만 남기고 자릿수 검증."""
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != length:
        return None
    return digits


def clean_corp_reg_no(value: str | None) -> str | None:
    return clean_reg_no(value, 13)


def clean_biz_reg_no(value: str | None) -> str | None:
    return clean_reg_no(value, 10)


_DATE_PATTERNS = ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d", "%Y년 %m월 %d일", "%Y년%m월%d일")


def parse_date(value) -> date | None:
    """docs/04-data-sources.md 날짜 포맷 전체 지원 (xlsx date 셀 포함)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s or s.lower() in {"nan", "nat", "none", "-"}:
        return None
    s = _SPACE_RE.sub(" ", s)
    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # "2026-01-02 00:00:00" 같은 형태
    m = re.match(r"^(\d{4})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def clean_text(value, limit: int | None = None) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in {"nan", "nat", "none"}:
        return None
    s = _SPACE_RE.sub(" ", s)
    return s[:limit] if limit else s


def normalize_url(value) -> str | None:
    s = clean_text(value, 300)
    if not s:
        return None
    if not s.startswith(("http://", "https://")):
        s = "http://" + s
    return s[:300]
