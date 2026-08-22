# 03. 리드 스코어링 v1 (확정)

- 총점 100점 = 설립단계 30 + 유형 20 + 자산규모 20 + 지역 15 + 신선도 15, 이후 감점 적용 (최저 0점)
- 모든 배점은 `scoring_settings` 테이블에 시드로 저장하고 계산 시 DB에서 읽는다 (하드코딩 금지)
- 재계산 트리거: 리드 생성 시 / 병합 시 / 관련 필드 수정 시 / 관리자가 가중치 변경 후 "전체 재계산" 버튼 실행 시
- 신선도는 시간이 지나면 변하지만 MVP에서는 **조회 시점 실시간 계산이 아닌, 재계산 트리거 시점 기준으로 저장** (일배치 재계산은 1차 고도화)

## 1) 설립단계/타이밍 — 30점 (rule_key: STAGE.*)

| rule_key | 조건 (stage_signal) | 점수 |
|---|---|---|
| STAGE.NEW_DESIGNATION | STAGE_NEW_DESIGNATION | 30 |
| STAGE.NEW_PERMIT | STAGE_NEW_PERMIT | 30 |
| STAGE.RECENT | STAGE_RECENT | 15 |
| STAGE.MATURE | STAGE_MATURE | 5 |
| STAGE.UNKNOWN | STAGE_UNKNOWN | 10 |

## 2) 조직 유형 — 20점 (rule_key: TYPE.*)

| rule_key | org_type | 점수 |
|---|---|---|
| TYPE.FOUNDATION | ORG_FOUNDATION | 20 |
| TYPE.PUBLIC_INTEREST | ORG_PUBLIC_INTEREST | 18 |
| TYPE.ASSOCIATION | ORG_ASSOCIATION | 18 |
| TYPE.SOCIAL_WELFARE | ORG_SOCIAL_WELFARE | 16 |
| TYPE.NPO_GROUP | ORG_NPO_GROUP | 12 |
| TYPE.RELIGIOUS | ORG_RELIGIOUS | 4 |
| TYPE.ETC | ORG_ETC | 8 |

## 3) 자산 규모 — 20점 (rule_key: ASSET.*)

| rule_key | asset_size | 점수 |
|---|---|---|
| ASSET.LARGE | ASSET_LARGE | 20 |
| ASSET.MID | ASSET_MID | 15 |
| ASSET.SMALL | ASSET_SMALL | 8 |
| ASSET.UNKNOWN | ASSET_UNKNOWN | 8 |

## 4) 지역 — 15점 (rule_key: REGION.*)

| rule_key | region_code | 점수 |
|---|---|---|
| REGION.CORE | 11(서울), 41(경기), 28(인천) | 15 |
| REGION.METRO | 26,27,29,30,31,36 (광역/세종) | 10 |
| REGION.OTHER | 그 외 | 6 |
| REGION.UNKNOWN | 99 | 6 |

※ CORE 지역 목록도 scoring_settings에 별도 설정값(JSON)으로 저장해 관리자 수정 가능하게.

## 5) 신선도 — 15점 (rule_key: FRESH.*) — 기준일: collected_at

| rule_key | 경과일 | 점수 |
|---|---|---|
| FRESH.7D | ≤ 7일 | 15 |
| FRESH.30D | ≤ 30일 | 10 |
| FRESH.90D | ≤ 90일 | 5 |
| FRESH.OLD | > 90일 | 2 |

## 6) 감점 (rule_key: PENALTY.*)

| rule_key | 조건 | 점수 |
|---|---|---|
| PENALTY.HAS_HOMEPAGE | homepage_url 존재 (홈페이지 수요 낮음 신호) | -5 |
| PENALTY.EXISTING_CUSTOMER | is_existing_customer=true | 점수 무관 강제 grade D |

※ 타사 ERP 기도입/해산 등은 데이터로 자동 판정 불가 → 담당자가 LOST 처리로 대응 (감점 규칙 아님)

## 등급 산정

score 계산 후: A(≥85) / B(70~84) / C(55~69) / D(<55). 기고객은 무조건 D.

## A등급 처리 규칙

- A등급 리드 생성/전환 시 대시보드 "즉시 배정 필요" 위젯에 노출
- (알림 발송은 Non-goal — 화면 내 배지/카운트만)

## 계산 결과 투명성

리드 상세 화면에서 항목별 기여 점수를 보여줘야 하므로, 계산 시 `leads` 테이블 외에 breakdown을 jsonb 컬럼(`score_breakdown`)으로 leads에 저장:
```json
{"STAGE.NEW_PERMIT": 30, "TYPE.FOUNDATION": 20, "ASSET.UNKNOWN": 8, "REGION.CORE": 15, "FRESH.7D": 15, "PENALTY.HAS_HOMEPAGE": 0, "total": 88}
```
