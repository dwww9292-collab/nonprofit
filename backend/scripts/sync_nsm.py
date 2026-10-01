"""NSM 고객 마스터를 리드에 반영.

DB의 리드를 NSM 고객 마스터와 맞춰, 그 단체가 실제로 쓰는 더존 제품과 상향 경로를
leads 열에 채운다. 영업 화면에서 'WEHAGO 보유 + 재지정 임박 + 연락처 있음' 같은
조건으로 바로 걸러낼 수 있게 하려는 것이다.

    python -m scripts.sync_nsm /data/nsm_customer.xlsx
    python -m scripts.sync_nsm /data/nsm_customer.xlsx --dry-run
    python -m scripts.sync_nsm /data/nsm_customer.xlsx --min-confidence 높음

매칭 규칙과 법인격 게이트는 scripts/match_nsm.py 와 같은 함수를 쓴다. 두 벌로 나뉘면
엑셀 산출물과 화면이 서로 다른 답을 하게 되므로 규칙은 한 곳에만 둔다.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.enums import REGION_CODES
from app.models import Lead
from scripts.match_nsm import (
    build_indexes,
    classify_phone,
    extract_sido,
    legal_kind,
    load_nsm,
    match_one,
    norm_name,
    norm_phone,
    is_valid_phone,
    pick_best,
    product_profile,
)

CONFIDENCE_ORDER = {"높음": 3, "중간": 2, "확인필요": 1}

# 지우기용 기본값. 매칭이 풀린 리드를 과거 값으로 남겨두면 영업이 틀린 제품을 보게 된다.
CLEARED = {
    "nsm_matched": False,
    "nsm_match_confidence": None,
    "nsm_match_basis": None,
    "nsm_company_name": None,
    "nsm_customer_code": None,
    "nsm_biz_reg_no": None,
    "nsm_products": None,
    "nsm_product_families": None,
    "nsm_top_product": None,
    "nsm_product_tier": 0,
    "nsm_sales_owner": None,
    "upsell_path": None,
    "upsell_priority": None,
}


def _text(value, limit: int) -> str | None:
    """엑셀에서 온 값을 열 길이에 맞춰 자른다. 결측은 None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "<na>"):
        return None
    return s[:limit]


def _lead_keys(lead: Lead) -> dict:
    """리드에서 매칭 키를 뽑는다. match_one 이 기대하는 모양으로 맞춘다.

    시도는 소재지 문자열에서 먼저 찾고, 비어 있으면 region_code 로 보완한다
    (기재부에서 온 리드는 주소가 없어 region_code 가 '99'인 경우가 많다).
    """
    sido = extract_sido(lead.address)
    if not sido:
        label = REGION_CODES.get(lead.region_code or "99", "")
        sido = "" if label in ("", "미상") else label
    return {
        "단체명_정규화": norm_name(lead.org_name),
        "법인격": legal_kind(lead.org_name),
        "전화키": norm_phone(lead.phone),
        "시도": sido,
    }


def sync(
    nsm_path: Path,
    *,
    min_confidence: str = "확인필요",
    dry_run: bool = False,
    fill_phone: bool = True,
    batch_size: int = 1000,
) -> dict:
    floor = CONFIDENCE_ORDER.get(min_confidence, 1)
    nsm = load_nsm(nsm_path)
    idx = build_indexes(nsm)

    stats: dict[str, int] = {
        "리드": 0,
        "매칭": 0,
        "신규매칭": 0,
        "갱신": 0,
        "해제": 0,
        "변화없음": 0,
        "신뢰도미달": 0,
        "연락처보완": 0,
    }
    by_confidence: dict[str, int] = {}
    by_path: dict[str, int] = {}
    now = datetime.now(UTC)

    db = SessionLocal()
    try:
        leads = db.scalars(select(Lead).where(Lead.deleted_at.is_(None))).all()
        print(f"  리드 {len(leads):,}건 대조")

        for n, lead in enumerate(leads, 1):
            stats["리드"] += 1
            keys = _lead_keys(lead)
            hits, basis, confidence = match_one(keys, idx, nsm)

            if hits and CONFIDENCE_ORDER.get(confidence, 0) < floor:
                stats["신뢰도미달"] += 1
                hits = []

            if hits:
                best = pick_best(hits, nsm, keys["법인격"])
                prof = product_profile(nsm.at[best, "구매제품군"])
                values = {
                    "nsm_matched": True,
                    "nsm_match_confidence": _text(confidence, 10),
                    "nsm_match_basis": _text(basis, 160),
                    "nsm_company_name": _text(nsm.at[best, "회사명"], 200),
                    "nsm_customer_code": _text(nsm.at[best, "거래처코드"], 30),
                    "nsm_biz_reg_no": _text(nsm.at[best, "사업자번호_정규화"], 12),
                    "nsm_products": _text(", ".join(prof["all_names"]), 300),
                    "nsm_product_families": prof["families"] or None,
                    "nsm_top_product": _text(prof["top_name"], 40),
                    "nsm_product_tier": prof["tier"],
                    "nsm_sales_owner": _text(nsm.at[best, "영업담당자"], 50),
                    "upsell_path": _text(prof["path"], 80),
                    "upsell_priority": prof["priority"],
                }
                stats["매칭"] += 1
                by_confidence[confidence] = by_confidence.get(confidence, 0) + 1
                if prof["path"]:
                    by_path[prof["path"]] = by_path.get(prof["path"], 0) + 1
                was_matched = lead.nsm_matched
            else:
                values = dict(CLEARED)
                was_matched = lead.nsm_matched

            # 공개데이터에 연락처가 없는 리드가 60%다. 같은 단체의 NSM 대표전화가
            # 있으면 비어 있을 때만 채운다(기존 값은 건드리지 않는다 — 공개데이터
            # 연락처가 담당 부서 직통일 수 있고, 적재 병합 로직이 소유하는 값이다).
            phone_filled = False
            if fill_phone and hits and not (lead.phone or "").strip():
                nsm_phone = _text(nsm.at[best, "대표전화"], 30)
                if nsm_phone and is_valid_phone(classify_phone(nsm_phone)):
                    lead.phone = nsm_phone
                    stats["연락처보완"] += 1
                    phone_filled = True

            changed = phone_filled or any(getattr(lead, k) != v for k, v in values.items())
            if changed:
                for k, v in values.items():
                    setattr(lead, k, v)
                lead.nsm_synced_at = now
                if values["nsm_matched"] and not was_matched:
                    stats["신규매칭"] += 1
                elif values["nsm_matched"]:
                    stats["갱신"] += 1
                else:
                    stats["해제"] += 1
            else:
                stats["변화없음"] += 1

            if not dry_run and n % batch_size == 0:
                db.flush()

        if dry_run:
            db.rollback()
            print("  --dry-run: 변경을 되돌렸습니다")
        else:
            db.commit()
    finally:
        db.close()

    return {"stats": stats, "by_confidence": by_confidence, "by_path": by_path}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="NSM 고객 마스터를 리드에 반영")
    ap.add_argument("nsm", type=Path, help="NSM 고객 마스터 xlsx")
    ap.add_argument(
        "--min-confidence",
        choices=["높음", "중간", "확인필요"],
        default="중간",
        help="이 신뢰도 미만은 반영하지 않는다 (기본: 중간 — 확인필요 건은 제외)",
    )
    ap.add_argument("--dry-run", action="store_true", help="집계만 보고 DB는 바꾸지 않는다")
    ap.add_argument(
        "--no-fill-phone",
        action="store_true",
        help="연락처가 빈 리드에 NSM 대표전화를 채우지 않는다 (기본은 채운다)",
    )
    args = ap.parse_args(argv)

    if not args.nsm.exists():
        print(f"파일이 없습니다: {args.nsm}", file=sys.stderr)
        return 1

    print("NSM 마스터 로드:")
    result = sync(
        args.nsm,
        min_confidence=args.min_confidence,
        dry_run=args.dry_run,
        fill_phone=not args.no_fill_phone,
    )

    print("\n결과")
    for k, v in result["stats"].items():
        print(f"  {k}: {v:,}")
    if result["by_confidence"]:
        print("\n신뢰도별")
        for k in ("높음", "중간", "확인필요"):
            if k in result["by_confidence"]:
                print(f"  {k}: {result['by_confidence'][k]:,}")
    if result["by_path"]:
        print("\n상향경로별")
        for path, cnt in sorted(result["by_path"].items(), key=lambda kv: -kv[1]):
            print(f"  {cnt:5,}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
