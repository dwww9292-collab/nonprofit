# NPO Sales Radar

신규 비영리기구 리드 발굴 + 영업 파이프라인 관리 시스템 (아이원소프트뱅크 내부 전용).

기획 정본은 `CLAUDE.md`와 `docs/`에 있습니다. 구현하면서 확정한 사항과 문서와 달라진 부분은
`docs/07-implementation-notes.md`에 정리돼 있습니다.

## 빠른 시작 (Docker)

```bash
cp .env.example .env      # JWT_SECRET / ADMIN_PASSWORD는 반드시 변경
docker compose up --build
```

- 화면: http://localhost:3000
- API 문서: http://localhost:8000/api/docs
- 최초 기동 시 마이그레이션과 기본 시드(소스 10종, 배점 25건, 관리자 계정)가 자동 실행됩니다.

데모 데이터(리드 30건·딜·활동)가 필요하면:

```bash
docker compose exec backend python -m scripts.seed --demo
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
| 관리자 | `.env`의 `ADMIN_EMAIL` (기본 admin@ionesoftbank.co.kr) | `.env`의 `ADMIN_PASSWORD` |
| 데모 팀장/영업 | manager@ / sales1~3@ionesoftbank.co.kr | demo1234! |

운영 배포 전 `JWT_SECRET`과 관리자 비밀번호를 반드시 교체하십시오.
