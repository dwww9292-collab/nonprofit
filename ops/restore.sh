#!/usr/bin/env bash
# 백업 복원. 현재 DB 내용을 지우고 덮어쓴다 — 되돌릴 수 없다.
#
#   ./ops/restore.sh backups/npo-20261001-031000.sql.gz
#
# 확인 절차를 건너뛰려면 CONFIRM=yes 를 준다(자동화용).
set -euo pipefail

cd "$(dirname "$0")/.."

file="${1:-}"
if [ -z "$file" ]; then
  echo "사용법: ./ops/restore.sh <백업파일.sql.gz>" >&2
  exit 1
fi
if [ ! -f "$file" ]; then
  echo "오류: 파일이 없습니다: $file" >&2
  exit 1
fi
if [ ! -f .env ]; then
  echo "오류: .env 가 없습니다." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

: "${POSTGRES_USER:?.env 에 POSTGRES_USER 가 없습니다}"
DB_NAME="${POSTGRES_DB:-npo_sales}"

current=$(docker compose exec -T db psql -U "$POSTGRES_USER" -d "$DB_NAME" -tAc \
  'SELECT count(*) FROM leads WHERE deleted_at IS NULL' 2>/dev/null || echo '?')

echo "복원 대상 : $file"
echo "대상 DB   : $DB_NAME (현재 리드 ${current}건)"
echo "이 작업은 현재 데이터를 모두 지우고 백업 시점으로 되돌립니다."

if [ "${CONFIRM:-}" != "yes" ]; then
  printf "계속하려면 DB 이름(%s)을 그대로 입력하세요: " "$DB_NAME"
  read -r answer
  if [ "$answer" != "$DB_NAME" ]; then
    echo "취소했습니다."
    exit 1
  fi
fi

gunzip -c "$file" \
  | docker compose exec -T db psql -U "$POSTGRES_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 --quiet

after=$(docker compose exec -T db psql -U "$POSTGRES_USER" -d "$DB_NAME" -tAc \
  'SELECT count(*) FROM leads WHERE deleted_at IS NULL')
echo "복원 완료: 리드 ${after}건"
