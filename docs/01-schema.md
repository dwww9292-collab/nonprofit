# 01. DB 스키마 (PostgreSQL 16)

공통: 모든 테이블에 `id BIGSERIAL PK`, `created_at timestamptz DEFAULT now()`, `updated_at timestamptz` 포함. 아래에는 도메인 컬럼만 기술.

## users — 사용자

| 컬럼 | 타입 | 필수 | 설명 |
|---|---|---|---|
| email | varchar(255) UNIQUE | O | 로그인 ID |
| password_hash | varchar(255) | O | bcrypt |
| name | varchar(50) | O | 이름 |
| role | varchar(20) | O | ADMIN / MANAGER / SALES |
| region_codes | varchar(10)[] |  | 담당 지역 (시도 코드 배열, 배정 제안용) |
| is_active | boolean | O | 기본 true |

## sources — 수집 소스 정의

| 컬럼 | 타입 | 필수 | 설명 |
|---|---|---|---|
| code | varchar(30) UNIQUE | O | 02-enums.md의 SOURCE_* |
| name | varchar(100) | O | 표시명 |
| collect_method | varchar(20) | O | FILE_UPLOAD / MANUAL / (추후 CRAWLER) |
| license_type | varchar(20) |  | 공공누리 KOGL_1~4 / UNKNOWN |
| is_active | boolean | O |  |

시드 데이터로 02-enums.md의 소스 전부 insert.

## ingest_batches — 업로드/수집 배치

| 컬럼 | 타입 | 필수 | 설명 |
|---|---|---|---|
| source_id | FK sources | O |  |
| file_name | varchar(255) |  | 업로드 파일명 |
| file_hash | varchar(64) |  | sha256, 동일파일 재업로드 감지 |
| period_label | varchar(20) |  | 예: "2026Q2" (기재부 분기 파일용) |
| status | varchar(20) | O | PENDING / PARSED / FAILED |
| total_rows / new_leads / dup_skipped | int |  | 처리 결과 통계 |
| error_message | text |  |  |
| uploaded_by | FK users | O |  |

## raw_records — 원본 레코드 보존

| 컬럼 | 타입 | 필수 | 설명 |
|---|---|---|---|
| batch_id | FK ingest_batches | O |  |
| row_no | int | O | 원본 행 번호 |
| payload | jsonb | O | 원본 행 전체 (헤더:값) |
| lead_id | FK leads |  | 생성/매칭된 리드 (없으면 null) |
| dedup_result | varchar(20) | O | NEW / MERGED / SKIPPED_DUP / SKIPPED_CUSTOMER / ERROR |

## leads — 리드 (핵심 테이블)

| 컬럼 | 타입 | 필수 | 설명 |
|---|---|---|---|
| org_name | varchar(200) | O | 원본 표기 법인/단체명 |
| org_name_norm | varchar(200) | O | 정규화 명칭 (아래 규칙), 인덱스 |
| org_type | varchar(30) | O | 02-enums.md ORG_TYPE_* |
| corp_reg_no | varchar(20) UNIQUE NULLS DISTINCT |  | 법인등록번호 (13자리, 하이픈 제거 저장) |
| biz_reg_no | varchar(12) UNIQUE NULLS DISTINCT |  | 사업자/고유번호 (10자리) |
| region_code | varchar(10) |  | 시도 코드 (02-enums.md) |
| district | varchar(50) |  | 시군구명 |
| address | varchar(300) |  | 전체 주소 |
| representative | varchar(50) |  | 대표자 성명 ※개인정보 — 상세조회 감사로그 대상 |
| phone | varchar(30) |  | 법인 대표번호 우선 |
| email | varchar(255) |  |  |
| homepage_url | varchar(300) |  | 있으면 홈페이지 영업 스코어에 반영 |
| established_at | date |  | 설립허가/등록일 |
| designated_at | date |  | 공익법인 지정일 |
| purpose | text |  | 설립목적/주된사업 |
| authority | varchar(100) |  | 주무관청/등록기관 |
| asset_size | varchar(20) |  | ASSET_LARGE / ASSET_MID / ASSET_SMALL / ASSET_UNKNOWN |
| stage_signal | varchar(30) | O | 설립단계 신호, 02-enums.md STAGE_* |
| score | int | O | 스코어링 결과 0~100, 기본 0 |
| grade | char(1) | O | A/B/C/D |
| status | varchar(20) | O | 02-enums.md LEAD_STATUS_*, 기본 NEW |
| lost_reason | varchar(30) |  | status=LOST 시 필수, 02-enums.md |
| assignee_id | FK users |  | 담당 영업사원 |
| assigned_at | timestamptz |  |  |
| first_contacted_at | timestamptz |  | 신선도 KPI용 |
| is_existing_customer | boolean | O | 기고객 매칭 시 true, 기본 false |
| source_id | FK sources | O | 최초 유입 소스 |
| collected_at | timestamptz | O | 수집 시각 (신선도 계산 기준) |
| deleted_at | timestamptz |  | soft delete |

인덱스: (org_name_norm, region_code), (status, assignee_id), (grade, score DESC), (collected_at)

## lead_sources — 리드-소스 다중 출처 (병합 이력)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| lead_id | FK leads | |
| source_id | FK sources | |
| batch_id | FK ingest_batches | |
| UNIQUE(lead_id, source_id, batch_id) | | |

## deals — 딜 (리드 1:N)

| 컬럼 | 타입 | 필수 | 설명 |
|---|---|---|---|
| lead_id | FK leads | O |  |
| product_code | varchar(20) | O | 02-enums.md PRODUCT_* |
| stage | varchar(20) | O | 02-enums.md DEAL_STAGE_*, 기본 CONTACT |
| amount | bigint |  | 예상금액 (원) |
| probability | smallint |  | 20/40/60/80/100 |
| expected_close | date |  |  |
| closed_at | timestamptz |  | WON/LOST 확정 시 |
| lost_reason | varchar(30) |  | stage=LOST 시 필수 |
| owner_id | FK users | O | 딜 담당 |

## activities — 활동기록

| 컬럼 | 타입 | 필수 | 설명 |
|---|---|---|---|
| lead_id | FK leads | O |  |
| deal_id | FK deals |  | 특정 딜 관련이면 |
| type | varchar(20) | O | CALL / VISIT / EMAIL / SMS / NOTE |
| summary | text | O |  |
| next_action | varchar(200) |  |  |
| next_action_at | timestamptz |  | 차기 일정 |
| actor_id | FK users | O |  |
| occurred_at | timestamptz | O |  |

## existing_customers — 기고객 명단

| 컬럼 | 타입 | 필수 | 설명 |
|---|---|---|---|
| org_name / org_name_norm | varchar(200) | O |  |
| corp_reg_no | varchar(20) |  |  |
| biz_reg_no | varchar(12) |  |  |
| region_code | varchar(10) |  |  |
| products | varchar(20)[] |  | 사용 중 상품 |
| note | varchar(300) |  |  |

업로드 엑셀 형식: samples/existing_customers_template.csv 참조.

## scoring_settings — 스코어링 가중치 (관리자 수정 가능)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| rule_key | varchar(50) UNIQUE | 예: STAGE.NEW_DESIGNATION |
| points | int | 배점 |
| description | varchar(200) | |

시드: docs/03-scoring.md v1 전체.

## audit_logs — 감사로그

| 컬럼 | 타입 | 설명 |
|---|---|---|
| user_id | FK users | |
| action | varchar(30) | VIEW_LEAD_DETAIL / UPDATE_LEAD / DELETE_LEAD / EXPORT 등 |
| target_type / target_id | varchar(20) / bigint | |
| detail | jsonb | |

---

# 정규화·중복제거 규칙 (확정)

## 명칭 정규화 (org_name_norm)

1. 앞뒤 공백 제거, 연속 공백 → 단일 공백 → 최종적으로 **모든 공백 제거**
2. 다음 접두/괄호 표기 제거: `재단법인`, `사단법인`, `(재)`, `(사)`, `사회복지법인`, `(사복)`, `학교법인`, `의료법인`, `비영리법인`
3. 전각문자 → 반각, 특수문자 `·.,-‐–—_'"“”()［］[]` 제거
4. 영문은 소문자화
5. 제거된 접두어는 org_type 추정에 사용 (재단법인→FOUNDATION 등)

## 중복 판정 (신규 레코드 유입 시 순서대로)

1. **corp_reg_no 일치** → 동일 리드 확정, 병합
2. **biz_reg_no 일치** → 동일 리드 확정, 병합
3. **org_name_norm 완전일치 AND region_code 일치** → 동일 리드로 병합
4. **org_name_norm 유사도 ≥ 0.9 (pg_trgm similarity) AND 시군구(district) 일치** → `dedup_result=NEW`로 생성하되 리드에 `possible_dup_of` 표시... → 단순화: MVP에서는 3번까지만 자동 병합, 4번 조건은 리드 목록에 "중복의심" 배지만 표시 (별도 컬럼 `possible_dup_lead_id FK leads` 추가)
5. 어느 것도 아니면 신규 생성

## 병합 규칙

- 기존 리드의 빈 필드만 신규 값으로 채움 (기존 값 덮어쓰기 금지)
- 예외: designated_at, asset_size는 더 신뢰도 높은 소스(기재부/홈택스) 값이 오면 갱신
- lead_sources에 출처 추가, 스코어 재계산

## 기고객 필터

- 중복 판정과 동일 키 순서로 existing_customers와 대조
- 일치 시 리드는 생성하되 `is_existing_customer=true`, `dedup_result=SKIPPED_CUSTOMER`, 스코어 0 / grade D, 목록 기본 필터에서 제외 (업셀 목적으로 조회는 가능)
