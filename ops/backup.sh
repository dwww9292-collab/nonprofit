#!/usr/bin/env bash
# PostgreSQL 전체 백업. 저장소 루트 기준 어디서 실행해도 된다.
#
#   ./ops/backup.sh
#   BACKUP_DIR=/Volumes/외장디스크/npo-backups KEEP_DAYS=90 ./ops/backup.sh
#
# 백업 파일에는 대표자 성명·연락처가 들어 있다. 저장 위치는 사내 통제 범위
# 안이어야 하고, 개인 클라우드(iCloud/Dropbox 등) 동기화 폴더에 두면 안 된다.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "오류: .env 가 없습니다. 저장소 루트에서 실행하세요." >&2
  exit 1
fi

# .env 에서 DB 접속값만 읽는다
set -a
# shellcheck disable=SC1091
. ./.env
set +a

: "${POSTGRES_USER:?.env 에 POSTGRES_USER 가 없습니다}"
DB_NAME="${POSTGRES_DB:-npo_sales}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"

mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
out="$BACKUP_DIR/npo-$stamp.sql.gz"

# 먼저 .part 로 받고 성공 후 rename — 중간에 죽은 파일을 백업으로 오인하지 않게.
# pipefail 덕에 pg_dump 가 실패하면 여기서 멈춘다.
docker compose exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$DB_NAME" --clean --if-exists \
  | gzip > "$out.part"

# 빈 덤프(접속 실패 등)를 성공으로 처리하지 않는다
size=$(wc -c < "$out.part" | tr -d ' ')
if [ "$size" -lt 10240 ]; then
  rm -f "$out.part"
  echo "오류: 덤프가 비정상적으로 작습니다(${size}B). DB 접속을 확인하세요." >&2
  exit 1
fi

mv "$out.part" "$out"
echo "백업 완료: $out ($((size / 1024)) KB)"

# 보관기간 지난 백업 정리
find "$BACKUP_DIR" -maxdepth 1 -name 'npo-*.sql.gz' -type f -mtime "+$KEEP_DAYS" -print -delete \
  | sed 's/^/삭제(보관기간 초과): /'
