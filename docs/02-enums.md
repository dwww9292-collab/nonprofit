# 02. Enum 정의 (확정 — 임의 추가/변경 금지)

## 사용자 롤 (users.role)

| 코드 | 설명 |
|---|---|
| ADMIN | 시스템 관리자: 전체 + 설정 + 사용자 관리 |
| MANAGER | 팀장: 전체 리드/딜 조회, 배정, 실적 조회 |
| SALES | 영업사원: 본인 담당 리드/딜 CRUD, 전체 리드 목록 조회(읽기) |

## 조직 유형 (leads.org_type)

| 코드 | 설명 |
|---|---|
| ORG_FOUNDATION | 재단법인 |
| ORG_ASSOCIATION | 사단법인 |
| ORG_PUBLIC_INTEREST | 공익법인 (지정 확인된 경우 — org_type과 별개로 designated_at 존재 여부로도 판단) |
| ORG_NPO_GROUP | 비영리민간단체 (법인격 없음) |
| ORG_SOCIAL_WELFARE | 사회복지법인 |
| ORG_RELIGIOUS | 종교단체 |
| ORG_ETC | 기타/미상 |

## 설립단계 신호 (leads.stage_signal)

| 코드 | 설명 | 판정 기준 |
|---|---|---|
| STAGE_NEW_PERMIT | 설립허가/등록 직후 | established_at이 수집일 기준 90일 이내 |
| STAGE_NEW_DESIGNATION | 공익법인 신규 지정 직후 | designated_at이 수집일 기준 180일 이내 |
| STAGE_RECENT | 설립/지정 1년 이내 | 위 미해당 + 최근일자 365일 이내 |
| STAGE_MATURE | 1년 초과 | |
| STAGE_UNKNOWN | 일자 정보 없음 | |

판정은 수집(collected_at) 시 1회 계산 후 저장. 두 조건 충족 시 STAGE_NEW_DESIGNATION 우선.

## 리드 상태 (leads.status)

| 코드 | 표시명 | 진입 조건 |
|---|---|---|
| NEW | 신규 | 수집/생성 직후 |
| ASSIGNED | 배정됨 | assignee 지정 시 자동 전이 |
| CONTACTED | 접촉 | 첫 활동기록(CALL/VISIT/EMAIL/SMS) 생성 시 자동 전이, first_contacted_at 기록 |
| QUALIFIED | 유효확인(SQL) | 담당자가 수동 전환 (니즈/예산 확인) |
| CONVERTED | 딜 전환 | 첫 deal 생성 시 자동 전이 |
| LOST | 실패/제외 | 수동, lost_reason 필수 |
| ON_HOLD | 보류/육성 | 수동 |

## 딜 단계 (deals.stage) — 칸반 컬럼

| 코드 | 표시명 |
|---|---|
| CONTACT | 접촉 |
| MEETING | 미팅 |
| PROPOSAL | 제안 |
| NEGOTIATION | 협상 |
| WON | 계약 |
| LOST | 실패 |

## 상품 (deals.product_code)

| 코드 | 표시명 |
|---|---|
| AMARANTH10 | 아마란스10 ERP |
| WEHAGO | 위하고 |
| HOMEPAGE | 홈페이지 구축 |
| SI | SI/PMS 등 커스텀 개발 |
| BUNDLE_ERP_HP | 설립초기 번들 (ERP+홈페이지) |

## 실패 사유 (leads.lost_reason / deals.lost_reason)

| 코드 | 표시명 |
|---|---|
| LOST_COMPETITOR | 타사 솔루션 기도입/선택 |
| LOST_NO_BUDGET | 예산 없음 |
| LOST_NO_NEED | 니즈 없음 |
| LOST_NO_CONTACT | 연락 불가/두절 |
| LOST_DISSOLVED | 해산/폐업/활동중단 |
| LOST_DUPLICATE | 중복 리드 |
| LOST_ETC | 기타 (메모 필수) |

## 수집 소스 (sources.code)

| 코드 | 표시명 | collect_method (MVP) |
|---|---|---|
| SRC_MOEF_DESIGNATION | 기재부 공익법인 지정누계 | FILE_UPLOAD |
| SRC_DATA_GO_KR_NPO | 공공데이터포털 비영리민간단체 등록현황 | FILE_UPLOAD |
| SRC_MINISTRY_NOTICE | 중앙부처 설립허가 공고 | MANUAL (1차 고도화 시 CRAWLER) |
| SRC_LOCAL_GOV | 지자체 허가현황/공고 | MANUAL (1차 고도화 시 CRAWLER) |
| SRC_HOMETAX | 국세청 홈택스 공익법인 공시 | MANUAL |
| SRC_NANUM_1365 | 1365 기부포털 | MANUAL |
| SRC_GWANBO | 전자관보 | MANUAL |
| SRC_GUIDESTAR | 한국가이드스타 | MANUAL |
| SRC_G2B | 나라장터 | MANUAL |
| SRC_MANUAL | 수기입력(현장/기타) | MANUAL |

## 지역 코드 (region_code) — 표준 시도 코드

| 코드 | 시도 | 코드 | 시도 |
|---|---|---|---|
| 11 | 서울 | 43 | 충북 |
| 26 | 부산 | 44 | 충남 |
| 27 | 대구 | 45 | 전북 |
| 28 | 인천 | 46 | 전남 |
| 29 | 광주 | 47 | 경북 |
| 30 | 대전 | 48 | 경남 |
| 31 | 울산 | 50 | 제주 |
| 36 | 세종 | 99 | 미상 |
| 41 | 경기 | | |
| 42 | 강원 | | |

주소 문자열 앞부분에서 시도명 매칭으로 추출 ("서울특별시/서울시/서울" 모두 11).

## 자산 규모 (leads.asset_size)

| 코드 | 기준 |
|---|---|
| ASSET_LARGE | 총자산 100억 이상 |
| ASSET_MID | 5억 ~ 100억 미만 |
| ASSET_SMALL | 5억 미만 |
| ASSET_UNKNOWN | 미상 (기본값) |

## 활동 유형 (activities.type)

CALL / VISIT / EMAIL / SMS / NOTE

## 리드 등급 (leads.grade)

| 등급 | 점수 |
|---|---|
| A | 85 이상 |
| B | 70~84 |
| C | 55~69 |
| D | 55 미만 또는 is_existing_customer=true |
