# NPO Sales Radar

신규 비영리기구 리드 발굴 + 영업 파이프라인 관리 시스템 (아이원소프트뱅크 내부 전용).

기획 정본은 `CLAUDE.md`와 `docs/`에 있습니다. 구현하면서 확정한 사항과 문서와 달라진 부분은
`docs/07-implementation-notes.md`에 정리돼 있습니다.

## 빠른 시작 (Docker)

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # JWT_SECRET에 붙여넣기
# .env를 열어 JWT_SECRET / ADMIN_PASSWORD / POSTGRES_PASSWORD를 채운다
docker compose up --build
```

비밀값에는 기본값을 두지 않았다. 비워두면 compose가 기동을 거부하고 어떤 값이 빠졌는지 알려준다.
저장소에 공개된 비밀번호로 서비스가 떠버리는 사고를 막기 위한 의도적인 설계다.

- 화면: http://localhost:3000
- API 문서: http://localhost:8000/api/docs
- 최초 기동 시 마이그레이션과 기본 시드(소스 10종, 배점 25건, 관리자 계정)가 자동 실행됩니다.

데모 데이터(리드 30건·딜·활동)가 필요하면:

```bash
docker compose exec backend python -m scripts.seed --demo
```

## 실데이터 적재

공개데이터 원본 파일(행안부 비영리민간단체 등록현황, 기재부 지정기부금단체 지정누계)을
`data/` 에 넣고 한 번에 적재한다. 파일명으로 출처와 분기를 자동 판별한다.

```bash
mkdir -p data          # data/ 는 .gitignore 처리 — 원본에 개인정보가 있어 커밋되지 않는다
docker compose cp data backend:/data
docker compose exec backend python -m scripts.ingest auto /data
```

출처별 다운로드 경로와 파일 구조는 `docs/04-data-sources.md` 에 있다.

## NSM 제품군 매칭

NSM(더존 영업관리) 고객 마스터와 맞춰 '이 비영리단체가 실제로 어떤 더존 제품을 쓰는가'를
붙인다. 공개데이터에는 사업자번호가 없어 단체명·대표전화·시도·법인격을 함께 쓴다.

```bash
# 공개데이터 전체(약 23,000곳) × NSM 마스터
docker compose exec backend python -m scripts.match_nsm \
  --nsm /data/nsm_customer.xlsx \
  --npo /data/mois_npo_20260331.xls \
  --moef /data/moef_designation_2026Q2.xlsx \
  -o /data/nsm_매칭결과.xlsx

# 이미 매칭된 엑셀의 구매제품군만 조회 가능한 형태로 정제
docker compose exec backend python -m scripts.refine_nsm /data/매칭결과.xlsx
```

제품 분류표와 상향경로 규칙은 `backend/scripts/refine_nsm.py` 상단의 `PRODUCTS`,
`UPSELL_RULES` 한 곳에 있다. 영업 정책이 바뀌면 그 표만 고치면 산출물이 따라 바뀐다.

### DB에 반영 (화면에서 필터하려면 이것)

엑셀만으로는 영업사원이 쓰지 못한다. 매칭 결과를 `leads` 에 직접 넣어야 목록에서
걸러진다.

```bash
docker compose exec backend python -m scripts.sync_nsm /data/nsm_customer.xlsx --dry-run
docker compose exec backend python -m scripts.sync_nsm /data/nsm_customer.xlsx
```

> 프론트엔드는 빌드 시점에 번들이 만들어진다. 코드를 받은 뒤 `--build` 로 **backend 만**
> 다시 올리면 화면은 예전 번들 그대로라서 새 열·필터가 보이지 않는다. 둘 다 올릴 것:
>
> ```bash
> docker compose up -d --build        # 서비스 이름을 주지 않으면 전부 다시 빌드한다
> ```
>
> 그래도 안 보이면 브라우저 캐시다 — Ctrl+Shift+R(맥은 Cmd+Shift+R).

- 기본값은 신뢰도 '중간' 이상만 반영한다(`--min-confidence`). '확인필요'(동명 다수·법인격
  불일치)는 영업 목록을 더럽히므로 기본에서 빠진다.
- 연락처가 빈 리드는 NSM 대표전화로 채운다(`--no-fill-phone` 로 끌 수 있다). 기존 값은
  건드리지 않는다.
- 매칭이 풀린 리드는 과거 값을 지운다 — 틀린 제품을 보여주면 안 된다.

반영 후 리드 목록에서 **보유 더존 제품 / 상향 우선순위 / NSM·연락처** 로 거를 수 있고,
CSV 내보내기에도 제품 열이 포함된다.

## 배포

| 상황 | 방법 | 문서 |
|---|---|---|
| 사내망에서만 본다 | 사내 서버(맥·PC) + compose | `docs/08-deploy.md` |
| 사내망 + 가끔 외부 | 사내 서버 + Tailscale | `docs/08-deploy.md` 4절 |
| 외부에서 상시 접속 | AWS Lightsail + Caddy(HTTPS) | `docs/09-deploy-aws.md` |

Vercel·GitHub Pages 에는 올릴 수 없다 — PostgreSQL 과 상시 구동 API 가 필요하고,
적재 작업이 서버리스 함수 실행시간 제한을 넘는다(실측 46초).

## 사내 서버 배포

사내 맥을 서버로 쓰는 전체 절차(잠자기 해제, 자동 기동, 사내망 공개 범위, Tailscale,
자동 백업·복원, 분기 갱신, 점수 재계산)는 **`docs/08-deploy.md`** 에 정리돼 있다.

```bash
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
./ops/backup.sh        # 백업
```

## 로컬 개발

### 백엔드

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
export DATABASE_URL="postgresql+psycopg://npo:npo@localhost:5432/npo_sales"
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.seed --demo
.venv/bin/uvicorn app.main:app --reload
```

### 프론트엔드

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, /api는 :8000으로 프록시
```

### 테스트 / 린트

```bash
cd backend
createdb npo_sales_test                       # 최초 1회
.venv/bin/pytest -q                           # 141건
.venv/bin/ruff check app scripts tests

cd ../frontend
npm run typecheck && npm run build
```

테스트는 실제 PostgreSQL을 사용합니다(`pg_trgm` 유사도 판정을 검증해야 하므로 SQLite 대체 불가).
접속 대상은 `TEST_DATABASE_URL` 환경변수로 바꿀 수 있고, 연결이 안 되면 해당 테스트는 스킵됩니다.

## 구조

```
CLAUDE.md              프로젝트 규칙·MVP 범위·Non-Goals (정본)
docs/                  스키마·enum·스코어링·소스·화면·로드맵 기획 문서
samples/               실제 업로드 파일 샘플을 넣는 곳 (개인정보 주의, git 제외)
backend/
  app/core/            설정, DB, 보안(JWT/bcrypt), enum 코드값
  app/models/          SQLAlchemy 12개 테이블
  app/services/        정규화 · 중복제거 · 스코어링 · 상태전이 · 시드 · 데모데이터
  app/ingest/          파서(헤더 별칭 매핑) · 수집 파이프라인(diff/병합)
  app/api/v1/          auth · leads · deals · ingest · dashboard · performance · settings
  alembic/             마이그레이션
  tests/               단위 + 통합 테스트 141건
frontend/src/pages/    로그인 · 대시보드 · 리드목록 · 리드상세 · 칸반 · 업로드 · 실적 · 설정
```

## 계정

| 구분 | 계정 | 비밀번호 |
|---|---|---|
| 관리자 | `.env`의 `ADMIN_EMAIL` | `.env`의 `ADMIN_PASSWORD` |
| 데모 팀장/영업 | `--demo` 실행 시 생성 | 실행 결과에 출력됨 (`DEMO_PASSWORD`로 지정 가능) |

## 비밀 관리

- `DATABASE_URL`, `JWT_SECRET`, `ADMIN_PASSWORD`는 **코드에 기본값이 없다.** 미설정 시 기동 실패.
- `.env`는 `.gitignore`에 포함돼 저장소에 올라가지 않는다.
- 수집 원본 파일(`samples/*.xlsx`, `*.xls`, `*.csv`)에는 대표자 성명·연락처가 들어 있어
  역시 `.gitignore` 대상이다. 커밋하지 말 것.
- 대표자 성명 열람은 `audit_logs`에 기록된다 (`VIEW_LEAD_DETAIL`).
- DB 포트는 compose에서 호스트로 노출하지 않는다. 앱 포트도 `127.0.0.1`에만 바인딩한다.

## 파일 적재 (CLI)

업로드 화면 대신 터미널에서 적재할 수 있다. 같은 `ingest_file()`을 호출하므로 결과는 동일하고,
대용량 파일(행안부 전국 14,000행)은 브라우저보다 안정적이다.

```bash
# 폴더 안의 파일을 올바른 순서로 한 번에 (기고객 → 행안부 → 기재부 분기 오름차순)
docker compose exec backend python -m scripts.ingest auto /data

# 개별 지정
docker compose exec backend python -m scripts.ingest npo  /data/mois_npo_20260331.xls
docker compose exec backend python -m scripts.ingest moef /data/moef_designation_2026Q2.xlsx --period 2026Q2
```

기재부 파일의 기간은 파일명에서 자동 추출되며(`..._2026Q2.xlsx`), `--period`로 덮어쓸 수 있다.
**순서가 중요하다** — 주소를 가진 행안부 파일이 먼저 들어가야 기재부 리드가 병합되며 지역이 채워진다.
