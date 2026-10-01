"""NSM 제품군 매칭 자료 정제.

기재부 지정기부금단체 명단 × NSM(더존 영업관리) 고객 자료를 매칭한 엑셀을 받아,
'이 단체가 실제로 어떤 더존 제품을 쓰고 있는가'를 조회·집계할 수 있는 형태로 정제한다.

    python -m scripts.refine_nsm /data/moef_2026Q2_NSM매칭.xlsx
    python -m scripts.refine_nsm 입력.xlsx -o 출력.xlsx --asof 2026-10-01

원본의 `구매제품군` 은 "[Smart A,WEHAGO,IDC-서비스]" 같은 문자열이라 필터·피벗이 안 된다.
이 스크립트는 토큰을 쪼개서 (1) 본제품/부가서비스를 분리하고 (2) 제품별 보유 플래그를
세우고 (3) 보유 제품에서 상향 경로를 산출한다.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# 제품 분류표 — NSM 자료에 실제로 나타난 14종 전부를 담았다.
#
# tier 는 '아마란스10 상향까지 남은 거리'를 재기 위한 영업용 단계값이고 더존 공식
# 등급이 아니다. 영업 정책이 바뀌면 이 표만 고치면 전체 산출물이 따라 바뀐다.
# 새 토큰이 들어오면 스크립트가 경고하고 '미분류'로 남긴다(조용히 버리지 않는다).
# ---------------------------------------------------------------------------
LINE_ERP = "ERP본제품"
LINE_ADDON = "부가서비스"

PRODUCTS: dict[str, dict] = {
    # 토큰            정규화명                 계열            구분        단계
    "Smart A": {"name": "Smart A", "family": "SMART_A", "line": LINE_ERP, "tier": 1},
    "Bizbox": {"name": "Bizbox Alpha", "family": "BIZBOX", "line": LINE_ERP, "tier": 1},
    "WEHAGO": {"name": "WEHAGO", "family": "WEHAGO", "line": LINE_ERP, "tier": 2},
    "ERP-iU": {"name": "ERP-iU", "family": "ERP_IU", "line": LINE_ERP, "tier": 2},
    "ICUBE": {"name": "iCUBE", "family": "ICUBE", "line": LINE_ERP, "tier": 3},
    "ICUBE G20": {"name": "iCUBE G20", "family": "ICUBE", "line": LINE_ERP, "tier": 3},
    "Amaranth 10": {"name": "Amaranth 10", "family": "AMARANTH10", "line": LINE_ERP, "tier": 4},
    "Amaranth 10 클라우드": {"name": "Amaranth 10 클라우드", "family": "AMARANTH10", "line": LINE_ERP, "tier": 4},
    "IDC-서비스": {"name": "IDC-서비스", "family": "IDC", "line": LINE_ADDON, "tier": 0},
    "IDC-하드웨어": {"name": "IDC-하드웨어", "family": "IDC", "line": LINE_ADDON, "tier": 0},
    "FAX": {"name": "FAX", "family": "FAX", "line": LINE_ADDON, "tier": 0},
    "전자금융상품": {"name": "전자금융상품", "family": "EBANKING", "line": LINE_ADDON, "tier": 0},
    "융합보안사업": {"name": "융합보안사업", "family": "SECURITY", "line": LINE_ADDON, "tier": 0},
    "기타-하드웨어": {"name": "기타-하드웨어", "family": "HARDWARE", "line": LINE_ADDON, "tier": 0},
}

# 피벗용 보유 플래그를 세울 계열 (ERP 본제품만)
ERP_FAMILIES = ["SMART_A", "BIZBOX", "WEHAGO", "ERP_IU", "ICUBE", "AMARANTH10"]
FAMILY_LABEL = {
    "SMART_A": "Smart A",
    "BIZBOX": "Bizbox",
    "WEHAGO": "WEHAGO",
    "ERP_IU": "ERP-iU",
    "ICUBE": "iCUBE",
    "AMARANTH10": "Amaranth 10",
}

# 상향 경로 — (계열, 경로명, 우선순위, 근거). 위에서부터 먼저 맞는 것을 쓴다.
# 우선순위 1이 가장 급한 영업 대상.
#
# 순서가 결과를 바꾸므로 근거를 남긴다.
#  - AMARANTH10 을 맨 위에 둔다: 주력 제품을 이미 보유한 곳은 상향이 아니라 추가 과제
#    발굴 대상이다. 아래에 두면 iCUBE·ERP-iU 를 함께 쓰는 곳이 '상향 대상'으로 잘못
#    분류된다(원본 NSM구분이 바로 이 실수로 A10 보유 71곳 중 59곳을 '대상아님'에 묶었다).
#  - ICUBE 를 WEHAGO 보다 위에 둔다: 둘을 함께 쓰는 곳의 회계 주 시스템은 iCUBE 이고
#    WEHAGO 는 플랫폼이라, 상향 제안의 대상은 iCUBE 쪽이다.
UPSELL_RULES: list[tuple[str, str, int, str]] = [
    ("AMARANTH10", "Amaranth 10 보유 → SI·홈페이지·추가모듈", 3, "주력 제품 이미 보유. 신규 판매보다 추가 과제 발굴"),
    ("ERP_IU", "ERP-iU 단종계열 → Amaranth 10 전환", 1, "구형 ERP만 사용 중. 전환 명분이 가장 뚜렷하다"),
    ("ICUBE", "iCUBE → Amaranth 10 상향", 2, "중소기업용 ERP. 상향 가능하나 제품 담당 파트너 확인 필요"),
    ("WEHAGO", "WEHAGO 보유 → Amaranth 10 상향", 1, "당사 주력 상향 경로. 최우선"),
    ("SMART_A", "Smart A 보유 → WEHAGO·Amaranth 10 상향", 2, "소규모 회계 제품만 보유. 상향 여지 큼"),
    ("BIZBOX", "그룹웨어만 보유 → ERP 신규 제안", 2, "ERP 미보유. 회계 요건을 명분으로 신규 제안"),
]

# A10 을 보유했는데 구형·하위 ERP 가 함께 남아 있으면 통합·정리 제안 건이다.
LEGACY_WITH_A10 = ["ERP_IU", "ICUBE"]


def classify_phone(value) -> str:
    """NSM 대표전화에 000-0000 류 더미값이 섞여 있어 유효성을 따로 표시한다.

    '유효' 로 시작하는 상태가 통화 가능한 번호다(is_valid_phone 참고).
    """
    if pd.isna(value):
        return "없음"
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return "없음"
    if len(set(digits)) == 1:
        return "무효(동일숫자)"
    if re.fullmatch(r"0\d{0,2}0{3,}\d*", digits):
        return "무효(0패턴)"
    # 전국대표번호(1588·1666·1800 등)는 8자리라 지역번호 검사에 걸리면 안 된다.
    # 교환을 거쳐야 하므로 담당자 직통과 구분해 표시한다.
    if re.fullmatch(r"1[5-9]\d{6}", digits):
        return "유효(대표번호)"
    if len(digits) < 9:
        return "지역번호누락"
    if len(digits) > 11:
        return "자릿수초과"
    if not digits.startswith("0"):
        return "형식확인필요"
    return "유효"


def is_valid_phone(status: str) -> bool:
    return str(status).startswith("유효")


def normalize_org_name(value) -> str:
    """법인격 표기를 떼어낸 매칭 키. NSM·기재부·행안부 표기가 서로 달라 필요하다."""
    s = re.sub(r"\s+", "", str(value or ""))
    s = re.sub(r"^\((?:사|재|복|의|학|특|공|조|주)\)", "", s)
    s = re.sub(
        r"^(사단법인|재단법인|사회복지법인|의료법인|학교법인|협동조합|공익법인|특수법인)",
        "",
        s,
    )
    return s


def split_products(value) -> tuple[list[str], list[str]]:
    """'[Smart A,WEHAGO]' → (알려진 토큰, 미분류 토큰)."""
    if pd.isna(value):
        return [], []
    inner = str(value).strip()
    if inner.startswith("["):
        inner = inner[1:]
    if inner.endswith("]"):
        inner = inner[:-1]
    known, unknown = [], []
    for raw in inner.split(","):
        tok = raw.strip()
        if not tok:
            continue
        (known if tok in PRODUCTS else unknown).append(tok)
    return known, unknown


def parse_period(value) -> tuple[date | None, date | None]:
    """'2026-01-01~2031-12-31' → (시작일, 만료일)."""
    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})\s*", str(value or ""))
    if not m:
        return None, None
    return (
        datetime.strptime(m.group(1), "%Y-%m-%d").date(),
        datetime.strptime(m.group(2), "%Y-%m-%d").date(),
    )


def upsell_for(families: set[str]) -> tuple[str, int, str]:
    for family, label, priority, note in UPSELL_RULES:
        if family in families:
            return label, priority, note
    return "", 0, ""


def refine(src: Path, asof: date) -> tuple[dict[str, pd.DataFrame], list[str]]:
    book = pd.read_excel(src, sheet_name=None)
    warnings: list[str] = []

    # 시트명에 건수가 붙어 있어(예: '신규지정 779곳') 키워드로 찾는다
    def find_sheet(*keywords: str) -> str | None:
        for name in book:
            if all(k in name for k in keywords):
                return name
        return None

    plan = [
        ("신규지정", find_sheet("신규지정")),
        ("만료임박", find_sheet("만료임박")),
    ]
    frames = []
    for group, sheet in plan:
        if sheet is None:
            warnings.append(f"'{group}' 시트를 찾지 못해 건너뜁니다")
            continue
        df = book[sheet].copy()
        df = df[df["대상단체명"].notna()]
        df["구분"] = group
        # 연락처·대표자 열 이름이 시트마다 다르다(연락처 / 연락처(NSM))
        for want, cands in [
            ("연락처", ["연락처", "연락처(NSM)"]),
            ("대표자", ["대표자*", "대표자(NSM)"]),
            ("소재지", ["소재지*", "소재지"]),
            ("지정구분", ["지정구분"]),
        ]:
            col = next((c for c in cands if c in df.columns), None)
            df[want] = df[col] if col else pd.NA
        frames.append(df)

    if not frames:
        raise SystemExit("처리할 시트가 없습니다. 입력 파일을 확인하세요.")

    raw = pd.concat(frames, ignore_index=True)

    records = []
    unknown_tokens: set[str] = set()
    for _, row in raw.iterrows():
        known, unknown = split_products(row.get("구매제품군"))
        unknown_tokens.update(unknown)

        metas = [PRODUCTS[t] for t in known]
        erp = [m for m in metas if m["line"] == LINE_ERP]
        addon = [m for m in metas if m["line"] == LINE_ADDON]
        families = {m["family"] for m in erp}
        top = max(erp, key=lambda m: m["tier"], default=None)
        path, priority, note = upsell_for(families)
        legacy = ""
        if "AMARANTH10" in families:
            stale = [FAMILY_LABEL[f] for f in LEGACY_WITH_A10 if f in families]
            if stale:
                legacy = ", ".join(stale)

        start, expires = parse_period(row.get("지정기간"))
        matched = str(row.get("매칭") or "").strip()

        rec = {
            "구분": row["구분"],
            "단체명": row["대상단체명"],
            "단체명_정규화": normalize_org_name(row["대상단체명"]),
            "유형": row.get("유형"),
            "관할지방청": row.get("관할지방청"),
            "지정구분": row.get("지정구분"),
            "지정일": row.get("지정일"),
            "지정시작일": start,
            "지정만료일": expires,
            "만료D-day": (expires - asof).days if expires else pd.NA,
            "NSM매칭": {"O": "매칭", "확인필요": "확인필요"}.get(matched, "미보유"),
            "NSM구분_원본": row.get("NSM구분"),
            "보유제품_전체": ", ".join(m["name"] for m in metas),
            "ERP본제품": ", ".join(m["name"] for m in erp),
            "주력제품": top["name"] if top else "",
            "제품단계": top["tier"] if top else 0,
            "부가서비스": ", ".join(m["name"] for m in addon),
            "부가서비스수": len(addon),
            "제품수": len(metas),
            "미분류제품": ", ".join(unknown),
            "상향경로": path,
            "영업우선순위": priority if priority else pd.NA,
            "상향근거": note,
            "구형ERP잔존": legacy,
            "연락처": row.get("연락처"),
            "연락처상태": classify_phone(row.get("연락처")),
            "대표자": row.get("대표자"),
            "소재지": row.get("소재지"),
        }
        for fam in ERP_FAMILIES:
            rec[f"보유_{FAMILY_LABEL[fam]}"] = "O" if fam in families else ""
        records.append(rec)

    clean = pd.DataFrame(records)

    if unknown_tokens:
        warnings.append(
            "분류표에 없는 제품 토큰: " + ", ".join(sorted(unknown_tokens))
            + " → scripts/refine_nsm.py 의 PRODUCTS 에 추가하세요"
        )

    dup = clean[clean.duplicated("단체명_정규화", keep=False)]
    if len(dup):
        warnings.append(f"단체명 정규화 후 중복 {len(dup)}행 (시트 간 교차 포함)")

    # --- 집계 시트 ---
    held = clean[clean["NSM매칭"] != "미보유"].copy()

    product_rows = []
    for fam in ERP_FAMILIES:
        col = f"보유_{FAMILY_LABEL[fam]}"
        sub = held[held[col] == "O"]
        product_rows.append(
            {
                "구분": LINE_ERP,
                "제품": FAMILY_LABEL[fam],
                "보유 단체수": len(sub),
                "신규지정": int((sub["구분"] == "신규지정").sum()),
                "만료임박": int((sub["구분"] == "만료임박").sum()),
                "연락처 유효": int(sub["연락처상태"].map(is_valid_phone).sum()),
            }
        )
    addon_counts: dict[str, int] = {}
    for value in held["부가서비스"]:
        for name in [v.strip() for v in str(value).split(",") if v.strip()]:
            addon_counts[name] = addon_counts.get(name, 0) + 1
    for name, cnt in sorted(addon_counts.items(), key=lambda kv: -kv[1]):
        product_rows.append({"구분": LINE_ADDON, "제품": name, "보유 단체수": cnt})
    products = pd.DataFrame(product_rows)

    action = (
        held[held["상향경로"] != ""]
        .groupby(["영업우선순위", "상향경로", "상향근거"], dropna=False)
        .agg(
            단체수=("단체명", "size"),
            신규지정=("구분", lambda s: int((s == "신규지정").sum())),
            만료임박=("구분", lambda s: int((s == "만료임박").sum())),
            연락처유효=("연락처상태", lambda s: int(s.map(is_valid_phone).sum())),
        )
        .reset_index()
        .sort_values(["영업우선순위", "단체수"], ascending=[True, False])
    )

    no_erp = held[held["ERP본제품"] == ""]
    summary = pd.DataFrame(
        [
            ("기준일", asof.isoformat()),
            ("원본 파일", src.name),
            ("전체 단체", len(clean)),
            ("  신규지정", int((clean["구분"] == "신규지정").sum())),
            ("  만료임박(재지정 대상)", int((clean["구분"] == "만료임박").sum())),
            ("NSM 매칭", int((clean["NSM매칭"] == "매칭").sum())),
            ("NSM 확인필요", int((clean["NSM매칭"] == "확인필요").sum())),
            ("NSM 미보유(신규 개척)", int((clean["NSM매칭"] == "미보유").sum())),
            ("", ""),
            ("매칭된 단체 중 ERP 본제품 보유", int((held["ERP본제품"] != "").sum())),
            ("매칭된 단체 중 부가서비스만 보유", len(no_erp)),
            ("Amaranth 10 보유", int((held["보유_Amaranth 10"] == "O").sum())),
            ("WEHAGO 보유", int((held["보유_WEHAGO"] == "O").sum())),
            ("iCUBE 계열 보유", int((held["보유_iCUBE"] == "O").sum())),
            ("", ""),
            ("연락처 유효", int(clean["연락처상태"].map(is_valid_phone).sum())),
            ("연락처 무효·확인필요", int((~clean["연락처상태"].map(is_valid_phone) & (clean["연락처상태"] != "없음")).sum())),
            ("연락처 없음", int((clean["연락처상태"] == "없음").sum())),
        ],
        columns=["항목", "값"],
    )

    issues = clean[
        (~clean["연락처상태"].map(is_valid_phone) & (clean["연락처상태"] != "없음"))
        | (clean["NSM매칭"] == "확인필요")
        | (clean["미분류제품"] != "")
    ][["구분", "단체명", "NSM매칭", "보유제품_전체", "미분류제품", "연락처", "연락처상태"]]

    return {
        "요약": summary,
        "정제데이터": clean,
        "제품보유현황": held.sort_values(["제품단계", "단체명"], ascending=[False, True]),
        "제품별집계": products,
        "영업액션": action,
        "품질이슈": issues,
    }, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="NSM 제품군 매칭 자료 정제")
    ap.add_argument("src", type=Path, help="입력 엑셀 (기재부 × NSM 매칭 결과)")
    ap.add_argument("-o", "--out", type=Path, default=None, help="출력 엑셀 (기본: 입력명_정제.xlsx)")
    ap.add_argument("--asof", default=None, help="기준일 YYYY-MM-DD (기본: 오늘)")
    args = ap.parse_args(argv)

    if not args.src.exists():
        print(f"입력 파일이 없습니다: {args.src}", file=sys.stderr)
        return 1
    asof = datetime.strptime(args.asof, "%Y-%m-%d").date() if args.asof else date.today()
    out = args.out or args.src.with_name(args.src.stem + "_정제.xlsx")

    sheets, warnings = refine(args.src, asof)
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)

    print(f"정제 완료: {out}")
    for name, df in sheets.items():
        print(f"  [{name}] {len(df)}행 x {len(df.columns)}열")
    for w in warnings:
        print(f"  ! {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
