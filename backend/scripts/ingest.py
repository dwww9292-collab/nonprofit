"""파일 적재 CLI — 업로드 화면을 거치지 않고 터미널에서 수집한다.

업로드 화면과 똑같은 ingest_file()을 호출하므로 결과도 동일하다.
대용량 파일(행안부 전국 14,000행 등)은 브라우저보다 이쪽이 안정적이다.

    python -m scripts.ingest npo  samples/mois_npo_20260331.xls
    python -m scripts.ingest moef samples/moef_designation_2026Q1.xlsx --period 2026Q1
    python -m scripts.ingest customers samples/existing_customers.csv

    # 세 개를 올바른 순서로 한 번에 (주소가 있는 행안부 → 기재부 분기 순)
    python -m scripts.ingest auto samples/
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.enums import SourceCode
from app.ingest.base import ParseError
from app.ingest.pipeline import ingest_file, upload_existing_customers
from app.models import User

SOURCES = {
    "npo": SourceCode.DATA_GO_KR_NPO,
    "moef": SourceCode.MOEF_DESIGNATION,
}

# auto 모드에서 파일명으로 종류와 순서를 판단한다.
# 주소를 가진 행안부 파일이 먼저 들어가야 기재부 리드가 병합되며 지역이 채워진다.
AUTO_RULES: list[tuple[str, str]] = [
    (r"existing_customers.*\.(csv|xlsx?)$", "customers"),
    (r"mois|npo|비영리민간단체", "npo"),
    (r"moef|mofe|지정누계|designation", "moef"),
]


def _period_from_name(path: Path) -> str | None:
    m = re.search(r"(20\d{2})\s*Q([1-4])", path.name, re.I)
    return f"{m.group(1)}Q{m.group(2)}" if m else None


def _kind_of(path: Path) -> str | None:
    name = path.name.lower()
    for pattern, kind in AUTO_RULES:
        if re.search(pattern, name, re.I):
            return kind
    return None


def _run_one(db, admin_id: int, kind: str, path: Path, period: str | None) -> bool:
    content = path.read_bytes()
    label = f"{kind:9} {path.name}"
    t0 = time.time()

    if kind == "customers":
        res = upload_existing_customers(db, content=content, file_name=path.name)
        db.commit()
        print(
            f"[{label}] {time.time() - t0:5.0f}s  총{res.total_rows} "
            f"신규{res.inserted} 갱신{res.updated} 에러{res.error_rows} 재태깅{res.retagged_leads}"
        )
        return res.error_rows == 0

    source = SOURCES[kind]
    if source == SourceCode.MOEF_DESIGNATION and not period:
        period = _period_from_name(path)
        if not period:
            print(f"[{label}] 기재부 파일은 기간이 필요합니다. --period 2026Q2 처럼 지정하세요.")
            return False
    try:
        batch, res = ingest_file(
            db,
            source_code=source,
            content=content,
            file_name=path.name,
            uploaded_by=admin_id,
            period_label=period,
        )
    except (ParseError, ValueError) as exc:
        db.rollback()
        print(f"[{label}] 실패: {exc}")
        return False
    db.commit()

    if batch.status != "PARSED":
        print(f"[{label}] 실패: {batch.error_message}")
        return False
    print(
        f"[{label}] {time.time() - t0:5.0f}s  총{res.total_rows} 신규{res.new_leads} "
        f"병합{res.merged_leads} 중복스킵{res.dup_skipped} 기고객{res.customer_skipped} "
        f"에러{res.error_rows} 취소의심{res.revoked_marked}"
    )
    for w in res.warnings:
        print(f"           ! {w}")
    return True


def _auto_plan(folder: Path) -> list[tuple[str, Path, str | None]]:
    """기고객 → 행안부 → 기재부(기간 오름차순) 순으로 정렬한다."""
    found: list[tuple[str, Path, str | None]] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".xls", ".xlsx", ".csv"}:
            continue
        if path.name == "existing_customers_template.csv":
            continue  # 템플릿은 건너뛴다
        kind = _kind_of(path)
        if kind:
            found.append((kind, path, _period_from_name(path)))
    order = {"customers": 0, "npo": 1, "moef": 2}
    found.sort(key=lambda item: (order[item[0]], item[2] or ""))
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="공공데이터 파일 적재")
    parser.add_argument("kind", choices=["npo", "moef", "customers", "auto"])
    parser.add_argument("path", help="파일 경로, auto면 폴더 경로")
    parser.add_argument("--period", help="기재부 파일 기간 (예: 2026Q2). 생략 시 파일명에서 추출")
    args = parser.parse_args()

    target = Path(args.path)
    if not target.exists():
        sys.exit(f"경로를 찾을 수 없습니다: {target}")

    with SessionLocal() as db:
        admin = db.scalars(select(User).order_by(User.id)).first()
        if admin is None:
            sys.exit("사용자가 없습니다. 먼저 'python -m scripts.seed'를 실행하세요.")

        if args.kind == "auto":
            if not target.is_dir():
                sys.exit("auto 모드에는 폴더 경로를 주세요.")
            plan = _auto_plan(target)
            if not plan:
                sys.exit(f"{target}에서 처리할 파일을 찾지 못했습니다.")
            print("적재 순서:", " -> ".join(p.name for _k, p, _pd in plan))
            ok = all(_run_one(db, admin.id, k, p, pd) for k, p, pd in plan)
        else:
            ok = _run_one(db, admin.id, args.kind, target, args.period)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
