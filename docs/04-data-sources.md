# 04. 데이터 소스별 수집/파싱 사양 (MVP)

MVP는 **파일 업로드 → 파싱** 2종 + 수기입력. 파싱 로직은 `ingest/` 모듈로 분리 (함수 시그니처: `parse(file) -> list[RawRow]`, `ingest(batch) -> IngestResult`). 추후 크롤러가 동일 ingest 함수를 재사용한다.

## 공통 파서 규칙

- 헤더 행을 찾아 **헤더명 기반 매핑** (열 순서 의존 금지). 헤더는 아래 별칭 테이블로 유연 매칭.
- 매핑 실패(필수 필드 헤더를 못 찾음) 시 배치 status=FAILED + 어떤 헤더를 못 찾았는지 error_message에 명시.
- 병합 셀/빈 행/합계 행은 스킵. 스킵 행도 raw_records에 dedup_result=ERROR로 남김.
- 인코딩: xlsx는 무관, CSV는 UTF-8 → 실패 시 CP949 fallback.
- 날짜: `YYYY-MM-DD`, `YYYY.MM.DD`, `YYYY/MM/DD`, xlsx date 셀 모두 지원.
- **samples/ 폴더의 실제 파일이 이 문서와 다르면 samples가 우선.** 파서 작성 전 samples 파일을 먼저 열어 헤더를 확인할 것.

## 헤더 별칭 매핑 테이블 (공통)

| 표준 필드 | 허용 헤더 별칭 |
|---|---|
| org_name | 법인명, 단체명, 단체명칭, 명칭, 공익법인명, 법인명칭 |
| corp_reg_no | 법인등록번호, 등록번호 |
| biz_reg_no | 사업자등록번호, 고유번호 |
| address | 소재지, 주소, 사무소소재지, 주사무소소재지, 소재지(주소) |
| representative | 대표자, 대표자명, 대표자성명 |
| established_at | 설립허가일, 등록일, 설립일, 허가일자, 등록일자 |
| designated_at | 지정일, 고시일, 지정일자 |
| purpose | 설립목적, 주된사업, 목적사업, 사업내용 |
| authority | 주무관청, 소관부처, 등록기관, 소관청 |
| phone | 전화번호, 연락처, 대표전화 |

## 소스 1: 기재부 공익법인 지정누계 (SRC_MOEF_DESIGNATION)

- 입력: 기재부 고시 첨부 xlsx (분기별, "지정누계" 시트). 관리자가 다운로드 후 업로드.
- 업로드 시 `period_label` 입력 필수 (예: 2026Q2).
- **핵심 로직 — diff 추출:**
  1. 같은 소스의 직전 period_label 배치를 찾음
  2. 이번 파일의 각 행에 대해 (corp_reg_no 또는 org_name_norm+주소) 기준으로 직전 배치 raw 대비 **신규 행만** 리드 생성 대상으로 삼음
  3. 직전 배치가 없으면(최초 업로드) 전체를 대상으로 하되, 업로드 화면에 "최초 업로드: N건 전체가 리드로 생성됩니다" 경고 표시. 최초 업로드 시 designated_at 기준으로 stage_signal 계산되어 오래된 법인은 자연히 낮은 점수를 받음.
  4. 누계에서 **사라진** 행은 지정취소 가능성 → 해당 리드에 `possible_revoked=true` 플래그 (leads에 boolean 컬럼 추가)
- 리드 매핑: org_type — 명칭 접두어로 추정, 지정 명단이므로 designated_at 존재 시 stage_signal 계산에 사용. 공익법인 지정 사실 자체가 확인되므로 별도 표시 배지 "공익법인 지정".

## 소스 2: 공공데이터포털 비영리민간단체 등록현황 (SRC_DATA_GO_KR_NPO)

- 입력: data.go.kr에서 받은 행안부/시도별 CSV 또는 xlsx. 시도별 파일 구조가 조금씩 다름 → 헤더 별칭 매핑으로 흡수.
- 업로드 시 지역(시도) 선택 옵션 제공 — 파일에 주소가 시군구부터 시작하는 경우 region_code 보정용.
- org_type = ORG_NPO_GROUP 고정 (법인 전환 확인 전까지).
- established_at = 등록일. diff 로직: 소스 1과 동일 방식 (직전 배치 대비 신규만).

## 소스 3: 수기입력 (SRC_MANUAL 및 MANUAL 소스 전체)

- 입력 폼 필드: org_name(필수), org_type(필수), 소스 선택(필수, MANUAL 계열만), address, representative, phone, email, homepage_url, established_at, designated_at, purpose, authority, corp_reg_no, biz_reg_no, 메모
- org_name + address 입력 시 **실시간 중복검사** (debounce 500ms): 일치/유사 리드가 있으면 카드로 표시 + "기존 리드로 이동" 링크. 그래도 저장 시 possible_dup 표시.
- 저장 즉시 정규화 → 중복판정 → 스코어링 실행.

## 기고객 명단 업로드

- 형식: samples/existing_customers_template.csv (컬럼: 법인명, 법인등록번호, 사업자등록번호, 주소, 사용상품(세미콜론 구분: AMARANTH10;HOMEPAGE), 비고)
- 업로드는 전체 교체(replace) 방식이 아닌 **upsert** (corp_reg_no > biz_reg_no > org_name_norm 순 키).
- 업로드 후 기존 리드 전체에 대해 기고객 재매칭 배치 실행.

## 1차 고도화 예정 (지금은 구현하지 않음 — 설계만 고려)

- SRC_MINISTRY_NOTICE / SRC_LOCAL_GOV 게시판 크롤러: 소스별 커넥터 클래스가 `parse()` 결과와 동일한 RawRow 리스트를 반환하도록 인터페이스만 맞춰둘 것
- 크롤링 전 robots.txt/이용약관 검토 결과를 sources 테이블에 기록하는 필드(`crawl_allowed`, `crawl_note`)는 스키마에 미리 포함해도 좋음
