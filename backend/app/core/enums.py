"""docs/02-enums.md 확정본. 임의 추가/변경 금지."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    SALES = "SALES"


class OrgType(StrEnum):
    FOUNDATION = "ORG_FOUNDATION"
    ASSOCIATION = "ORG_ASSOCIATION"
    PUBLIC_INTEREST = "ORG_PUBLIC_INTEREST"
    NPO_GROUP = "ORG_NPO_GROUP"
    SOCIAL_WELFARE = "ORG_SOCIAL_WELFARE"
    RELIGIOUS = "ORG_RELIGIOUS"
    ETC = "ORG_ETC"


class StageSignal(StrEnum):
    NEW_PERMIT = "STAGE_NEW_PERMIT"
    NEW_DESIGNATION = "STAGE_NEW_DESIGNATION"
    RECENT = "STAGE_RECENT"
    MATURE = "STAGE_MATURE"
    UNKNOWN = "STAGE_UNKNOWN"


class LeadStatus(StrEnum):
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    CONTACTED = "CONTACTED"
    QUALIFIED = "QUALIFIED"
    CONVERTED = "CONVERTED"
    LOST = "LOST"
    ON_HOLD = "ON_HOLD"


class DealStage(StrEnum):
    CONTACT = "CONTACT"
    MEETING = "MEETING"
    PROPOSAL = "PROPOSAL"
    NEGOTIATION = "NEGOTIATION"
    WON = "WON"
    LOST = "LOST"


class ProductCode(StrEnum):
    AMARANTH10 = "AMARANTH10"
    WEHAGO = "WEHAGO"
    HOMEPAGE = "HOMEPAGE"
    SI = "SI"
    BUNDLE_ERP_HP = "BUNDLE_ERP_HP"


class LostReason(StrEnum):
    COMPETITOR = "LOST_COMPETITOR"
    NO_BUDGET = "LOST_NO_BUDGET"
    NO_NEED = "LOST_NO_NEED"
    NO_CONTACT = "LOST_NO_CONTACT"
    DISSOLVED = "LOST_DISSOLVED"
    DUPLICATE = "LOST_DUPLICATE"
    ETC = "LOST_ETC"


class SourceCode(StrEnum):
    MOEF_DESIGNATION = "SRC_MOEF_DESIGNATION"
    DATA_GO_KR_NPO = "SRC_DATA_GO_KR_NPO"
    MINISTRY_NOTICE = "SRC_MINISTRY_NOTICE"
    LOCAL_GOV = "SRC_LOCAL_GOV"
    HOMETAX = "SRC_HOMETAX"
    NANUM_1365 = "SRC_NANUM_1365"
    GWANBO = "SRC_GWANBO"
    GUIDESTAR = "SRC_GUIDESTAR"
    G2B = "SRC_G2B"
    MANUAL = "SRC_MANUAL"


class CollectMethod(StrEnum):
    FILE_UPLOAD = "FILE_UPLOAD"
    MANUAL = "MANUAL"
    CRAWLER = "CRAWLER"  # 1차 고도화 예약 — MVP에서 사용 금지


class AssetSize(StrEnum):
    LARGE = "ASSET_LARGE"
    MID = "ASSET_MID"
    SMALL = "ASSET_SMALL"
    UNKNOWN = "ASSET_UNKNOWN"


class ActivityType(StrEnum):
    CALL = "CALL"
    VISIT = "VISIT"
    EMAIL = "EMAIL"
    SMS = "SMS"
    NOTE = "NOTE"


class BatchStatus(StrEnum):
    PENDING = "PENDING"
    PARSED = "PARSED"
    FAILED = "FAILED"


class DedupResult(StrEnum):
    NEW = "NEW"
    MERGED = "MERGED"
    SKIPPED_DUP = "SKIPPED_DUP"
    SKIPPED_CUSTOMER = "SKIPPED_CUSTOMER"
    ERROR = "ERROR"


class AuditAction(StrEnum):
    VIEW_LEAD_DETAIL = "VIEW_LEAD_DETAIL"
    UPDATE_LEAD = "UPDATE_LEAD"
    DELETE_LEAD = "DELETE_LEAD"
    ASSIGN_LEAD = "ASSIGN_LEAD"
    EXPORT = "EXPORT"
    INGEST = "INGEST"
    RESCORE_ALL = "RESCORE_ALL"
    UPDATE_SCORING = "UPDATE_SCORING"


# 시도 코드 (docs/02-enums.md)
REGION_CODES: dict[str, str] = {
    "11": "서울",
    "26": "부산",
    "27": "대구",
    "28": "인천",
    "29": "광주",
    "30": "대전",
    "31": "울산",
    "36": "세종",
    "41": "경기",
    "42": "강원",
    "43": "충북",
    "44": "충남",
    "45": "전북",
    "46": "전남",
    "47": "경북",
    "48": "경남",
    "50": "제주",
    "99": "미상",
}
REGION_UNKNOWN = "99"

# 소스 시드 정의: (code, 표시명, collect_method)
SOURCE_SEED: list[tuple[str, str, str]] = [
    (SourceCode.MOEF_DESIGNATION, "기재부 공익법인 지정누계", CollectMethod.FILE_UPLOAD),
    (SourceCode.DATA_GO_KR_NPO, "공공데이터포털 비영리민간단체 등록현황", CollectMethod.FILE_UPLOAD),
    (SourceCode.MINISTRY_NOTICE, "중앙부처 설립허가 공고", CollectMethod.MANUAL),
    (SourceCode.LOCAL_GOV, "지자체 허가현황/공고", CollectMethod.MANUAL),
    (SourceCode.HOMETAX, "국세청 홈택스 공익법인 공시", CollectMethod.MANUAL),
    (SourceCode.NANUM_1365, "1365 기부포털", CollectMethod.MANUAL),
    (SourceCode.GWANBO, "전자관보", CollectMethod.MANUAL),
    (SourceCode.GUIDESTAR, "한국가이드스타", CollectMethod.MANUAL),
    (SourceCode.G2B, "나라장터", CollectMethod.MANUAL),
    (SourceCode.MANUAL, "수기입력(현장/기타)", CollectMethod.MANUAL),
]
