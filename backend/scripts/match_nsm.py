"""비영리단체 공개데이터 × NSM 고객 마스터 매칭.

'이 비영리단체가 실제로 어떤 더존 제품을 쓰고 있는가'를 전체 모집단에 대해 붙인다.

    python -m scripts.match_nsm --nsm /data/nsm_customer.xlsx \
        --npo /data/mois_npo_20260331.xls \
        --moef /data/moef_designation_2026Q2.xlsx \
        -o /data/nsm_매칭결과.xlsx

공개데이터(행안부·기재부)에는 사업자번호가 없다. 그래서 단체명만으로 맞추면
'(주)에어텍'과 '주식회사에어텍'처럼 사업자번호가 다른 별개 법인이 같은 이름으로
정규화되어 섞인다. 대표전화와 시도를 함께 써서 단계별로 맞추고, 각 건에 어떤 근거로
맞췄는지(매칭근거)와 신뢰도를 남긴다. 신뢰도가 낮은 건은 영업에 쓰기 전에 사람이 본다.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from scripts.refine_nsm import (
    ERP_FAMILIES,
    FAMILY_LABEL,
    LEGACY_WITH_A10,
    LINE_ADDON,
    LINE_ERP,
    PRODUCTS,
    classify_phone,
    count_valid_phone,
    is_valid_phone,
    split_products,
    upsell_for,
)

# NSM 마스터에서 읽을 열. 비고는 길어서 메모리만 먹으므로 제외한다.
NSM_COLUMNS = [
    "회사명",
    "사업자번호",
    "구매제품군",
    "대표전화",
    "대표자명",
    "우편번호",
    "주소",
    "업태",
    "업종",
    "홈페이지",
    "담당영업부서",
    "영업담당자",
    "거래처코드",
    "사업자번호검증",
]

LEGAL_FORM = (
    r"(?:사단법인|재단법인|사회복지법인|의료법인|학교법인|특수법인|공익법인|협동조합"
    r"|영농조합법인|사회적협동조합|주식회사|유한회사|유한책임회사|합자회사|합명회사)"
)
LEGAL_PAREN = r"\((?:사|재|복|의|학|특|공|조|주|유|합|자|명)\)"

SIDO_CANON = {
    "충청북도": "충북",
    "충청남도": "충남",
    "전라북도": "전북",
    "전라남도": "전남",
    "경상북도": "경북",
    "경상남도": "경남",
    "서울특별시": "서울",
    "부산광역시": "부산",
    "대구광역시": "대구",
    "인천광역시": "인천",
    "광주광역시": "광주",
    "대전광역시": "대전",
    "울산광역시": "울산",
    "세종특별자치시": "세종",
    "강원특별자치도": "강원",
    "전북특별자치도": "전북",
    "제주특별자치도": "제주",
    "경기도": "경기",
    "강원도": "강원",
    "제주도": "제주",
}
SIDO_RE = re.compile(
    r"(서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|울산광역시"
    r"|세종특별자치시|경기도|강원특별자치도|강원도|충청북도|충청남도|전북특별자치도"
    r"|전라북도|전라남도|경상북도|경상남도|제주특별자치도|제주도"
    r"|서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
)


# 법인격 종류. 공개데이터 모집단은 전부 비영리이므로, NSM 쪽이 영리 법인격이면
# 정규화 후 이름이 같아도 별개 법인이다 — '(사)굿라이프' vs '주식회사 굿라이프'.
# 실측에서 이 충돌이 199건이었고, 비영리 종류끼리는 거의 섞이지 않았다
# (사단→사단 239, 재단→재단 574, 협동조합→협동조합 30).
LEGAL_KINDS: list[tuple[str, str]] = [
    ("사단", r"사단법인|\(사\)"),
    ("재단", r"재단법인|\(재\)"),
    ("사회복지", r"사회복지법인|\(복\)"),
    ("의료", r"의료법인|\(의\)"),
    ("학교", r"학교법인|\(학\)"),
    ("협동조합", r"협동조합|\(조\)"),
    ("영리", r"주식회사|\(주\)|유한회사|\(유\)|유한책임회사|합자회사|\(합\)|합명회사"),
]
LEGAL_KIND_RES = [(kind, re.compile(pat)) for kind, pat in LEGAL_KINDS]


def legal_kind(value) -> str:
    """이름 표기에서 법인격 종류를 읽는다. 표기가 없으면 빈 문자열."""
    s = str(value or "")
    for kind, rx in LEGAL_KIND_RES:
        if rx.search(s):
            return kind
    return ""


def _as_kind(value) -> str:
    """결측을 빈 문자열로 접는다.

    NaN 은 truthy 이고 pd.NA 는 비교하면 TypeError 를 낸다. 둘 중 하나라도
    그대로 들어오면 '표기 없음'이 '어떤 값이 있음'으로 둔갑해 후보가 전부 걸러진다.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    s = str(value)
    return "" if s in ("nan", "<NA>", "None") else s


def kinds_compatible(public_kind, nsm_kind) -> bool:
    """한쪽 표기가 없으면 판단을 보류하고(통과), 둘 다 있으면 같아야 한다."""
    a, b = _as_kind(public_kind), _as_kind(nsm_kind)
    if not a or not b:
        return True
    return a == b


def norm_name(value) -> str:
    """법인격·괄호·구두점을 떼어낸 매칭 키."""
    s = str(value or "")
    if not s or s.lower() == "nan":
        return ""
    s = re.sub(r"\(.*?\)", "", s)  # 괄호 안 영문명·부가설명
    s = re.sub(r"[\s.,\-_'\"·‧・/|]", "", s)
    s = re.sub(LEGAL_PAREN, "", s)
    s = re.sub(LEGAL_FORM, "", s)
    return s


def norm_phone(value) -> str:
    """숫자만 남긴 전화번호. 더미값(000-0000 등)은 매칭에 쓰지 않으므로 버린다."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 9 or len(digits) > 11:
        return ""
    if not is_valid_phone(classify_phone(value)):
        return ""
    return digits


def norm_biz_no(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if len(digits) == 10 else ""


def extract_sido(value) -> str:
    s = re.sub(r"^\(\d+\)\s*", "", str(value or "")).strip()
    m = SIDO_RE.search(s[:20])
    if not m:
        return ""
    return SIDO_CANON.get(m.group(1), m.group(1))


# ---------------------------------------------------------------------------
# 공개데이터 로드 — 저장소의 기존 파서를 그대로 쓴다(제목행·다중시트 처리가 들어있다)
# ---------------------------------------------------------------------------
def load_public(npo_path: Path | None, moef_path: Path | None) -> pd.DataFrame:
    from app.ingest.parsers import DataGoKrNpoParser, MoefDesignationParser

    frames = []
    jobs = [(npo_path, DataGoKrNpoParser(), "행안부 비영리민간단체"), (moef_path, MoefDesignationParser(), "기재부 지정공익법인")]
    for path, parser, label in jobs:
        if path is None:
            continue
        result = parser.parse(path.read_bytes(), path.name)
        records = []
        for row in result.rows:
            if row.error:
                continue
            f = row.fields
            records.append(
                {
                    "출처": label,
                    "단체명": f.get("org_name"),
                    "유형_원본": row.payload.get("유형") or row.payload.get("구분"),
                    "소재지": f.get("address"),
                    "대표자": f.get("representative"),
                    "연락처": f.get("phone"),
                    "등록기관": f.get("authority"),
                    "등록일": f.get("established_at"),
                    "지정일": f.get("designated_at"),
                    "지정기간": row.payload.get("지정기간"),
                    "주된사업": f.get("purpose"),
                }
            )
        df = pd.DataFrame(records)
        print(f"  {label}: {len(df):,}건 (원본 {result.total_rows:,}행)")
        frames.append(df)

    if not frames:
        raise SystemExit("--npo 또는 --moef 중 하나는 있어야 합니다.")

    pub = pd.concat(frames, ignore_index=True)
    pub["단체명_정규화"] = pub["단체명"].map(norm_name)
    pub["법인격"] = pub["단체명"].map(legal_kind)
    pub = pub[pub["단체명_정규화"] != ""]
    pub["전화키"] = pub["연락처"].map(norm_phone)
    pub["시도"] = pub["소재지"].map(extract_sido)
    return pub


def unify_public(pub: pd.DataFrame) -> pd.DataFrame:
    """같은 단체가 행안부·기재부 양쪽에 있으면 한 행으로 합친다.

    기재부에는 주소가 없어 시도 비교가 불가능하므로 단체명으로만 합친다
    (DB 적재 때 region '99'를 와일드카드로 본 것과 같은 규칙).
    """
    pub = pub.sort_values("출처")  # 행안부(주소·연락처 보유)를 앞에 둔다

    def pick(series):
        for v in series:
            if pd.notna(v) and str(v).strip() not in ("", "nan"):
                return v
        return pd.NA

    agg = {c: pick for c in pub.columns if c != "단체명_정규화"}
    agg["출처"] = lambda s: " + ".join(sorted(set(s)))
    unified = pub.groupby("단체명_정규화", as_index=False).agg(agg)

    # 파생 키는 통합 후에 다시 계산한다. pick() 은 빈 문자열을 '값 없음'으로 보고
    # NA 를 돌려주는데, NA 는 truthy 라서 '표기 없음'이 '어떤 값이 있음'으로 둔갑한다.
    # 그대로 두면 법인격 표기가 없는 단체의 후보가 전부 부적합 처리된다.
    unified["법인격"] = unified["단체명"].map(legal_kind)
    unified["전화키"] = unified["연락처"].map(norm_phone)
    unified["시도"] = unified["소재지"].map(extract_sido)
    return unified


# ---------------------------------------------------------------------------
# NSM 마스터
# ---------------------------------------------------------------------------
def load_nsm(path: Path) -> pd.DataFrame:
    book = pd.read_excel(path, sheet_name=None, usecols=lambda c: c in NSM_COLUMNS)
    frames = []
    for sheet, df in book.items():
        df = df.copy()
        df["NSM시트"] = sheet
        frames.append(df)
    nsm = pd.concat(frames, ignore_index=True)
    nsm["회사명_정규화"] = nsm["회사명"].map(norm_name)
    nsm["법인격"] = nsm["회사명"].map(legal_kind)
    nsm = nsm[nsm["회사명_정규화"] != ""].copy()
    nsm["전화키"] = nsm["대표전화"].map(norm_phone)
    nsm["시도"] = nsm["주소"].map(extract_sido)
    nsm["사업자번호_정규화"] = nsm["사업자번호"].map(norm_biz_no)
    print(f"  NSM 고객 마스터: {len(nsm):,}건 (전화 {int((nsm['전화키'] != '').sum()):,} / 시도 {int((nsm['시도'] != '').sum()):,})")
    return nsm


def build_indexes(nsm: pd.DataFrame) -> dict:
    by_name: dict[str, list[int]] = defaultdict(list)
    by_name_sido: dict[tuple[str, str], list[int]] = defaultdict(list)
    by_phone: dict[str, list[int]] = defaultdict(list)
    for idx, name, sido, phone in zip(
        nsm.index, nsm["회사명_정규화"], nsm["시도"], nsm["전화키"], strict=True
    ):
        by_name[name].append(idx)
        if sido:
            by_name_sido[(name, sido)].append(idx)
        if phone:
            by_phone[phone].append(idx)
    return {"name": by_name, "name_sido": by_name_sido, "phone": by_phone}


def match_one(row, idx: dict, nsm: pd.DataFrame) -> tuple[list[int], str, str]:
    """(NSM 행 인덱스들, 매칭근거, 신뢰도). 위에서부터 먼저 맞는 근거를 쓴다.

    법인격이 어긋나는 후보는 먼저 걸러낸다. 걸러낸 뒤 남는 후보가 없으면 버리지 않고
    '확인필요'로 돌려준다(사람이 보게 남긴다).
    """
    name = row["단체명_정규화"]
    phone = row["전화키"]
    sido = row["시도"]
    kind = row["법인격"]

    def ok(i: int) -> bool:
        return kinds_compatible(kind, nsm.at[i, "법인격"])

    name_hits_all = idx["name"].get(name, [])
    name_hits = [i for i in name_hits_all if ok(i)]

    # 1. 이름 + 전화 모두 일치 — 가장 확실하다
    if phone and name_hits:
        both = [i for i in name_hits if nsm.at[i, "전화키"] == phone]
        if both:
            return both, "단체명+대표전화 일치", "높음"

    # 2. 이름 + 시도 일치 (동명 법인을 지역으로 가른다)
    if sido:
        hits = [i for i in idx["name_sido"].get((name, sido), []) if ok(i)]
        if hits:
            return hits, "단체명+시도 일치", "높음"

    # 3. 전화 일치 + 이름 일부 포함 — 이름 표기가 다른 경우를 건진다.
    #    전화만 같은 건은 대표번호 공유(회관·센터 입주)일 수 있어 이름 포함을 요구한다.
    if phone:
        close = [
            i
            for i in idx["phone"].get(phone, [])
            if ok(i)
            and name
            and (name in nsm.at[i, "회사명_정규화"] or nsm.at[i, "회사명_정규화"] in name)
        ]
        if close:
            return close, "대표전화 일치 + 단체명 부분일치", "중간"

    # 4. 이름만 일치
    if name_hits:
        if len(name_hits) == 1:
            return name_hits, "단체명 일치 (NSM 내 유일)", "중간"
        return name_hits, f"단체명 일치 (NSM 내 {len(name_hits)}건 동명)", "확인필요"

    # 5. 법인격이 어긋나는 후보만 남은 경우 — 버리지 않고 사람 확인으로 넘긴다.
    #    전화까지 같으면 NSM 쪽 회사명 표기가 낡았을 수 있어 근거를 구분해 적는다.
    if name_hits_all:
        kinds = sorted({nsm.at[i, "법인격"] for i in name_hits_all if nsm.at[i, "법인격"]})
        same_phone = phone and any(nsm.at[i, "전화키"] == phone for i in name_hits_all)
        basis = "단체명 일치하나 법인격 불일치"
        if same_phone:
            basis += " (대표전화는 일치)"
        return name_hits_all, f"{basis} — 공개:{kind or '표기없음'} / NSM:{'·'.join(kinds)}", "확인필요"

    return [], "", ""


def pick_best(hits: list[int], nsm: pd.DataFrame, kind: str = "") -> int:
    """동명 여러 건에서 대표로 쓸 행.

    법인격이 맞는 후보를 먼저 세운다. 제품 보유 수만으로 고르면 동명의 영리 법인이
    제품을 더 많이 들고 있어 그쪽이 뽑히는 일이 생긴다.
    """

    def score(i: int) -> tuple[int, int, int]:
        known, _ = split_products(nsm.at[i, "구매제품군"])
        compatible = 1 if kinds_compatible(kind, nsm.at[i, "법인격"]) else 0
        return (compatible, len(known), 1 if nsm.at[i, "사업자번호_정규화"] else 0)

    return max(hits, key=score)


def product_profile(value) -> dict:
    """구매제품군 문자열 → 구조화된 결과.

    DB 반영(scripts/sync_nsm.py)과 엑셀 산출 양쪽이 이 함수를 쓴다. 분류·상향 규칙이
    두 벌로 갈리면 화면과 엑셀이 서로 다른 답을 하게 된다.
    """
    known, unknown = split_products(value)
    metas = [PRODUCTS[t] for t in known]
    erp = [m for m in metas if m["line"] == LINE_ERP]
    addon = [m for m in metas if m["line"] == LINE_ADDON]
    families = {m["family"] for m in erp}
    top = max(erp, key=lambda m: m["tier"], default=None)
    path, priority, note = upsell_for(families)
    legacy = ""
    if "AMARANTH10" in families:
        stale = [FAMILY_LABEL[f] for f in LEGACY_WITH_A10 if f in families]
        legacy = ", ".join(stale)
    return {
        "families": sorted(families),
        "priority": priority or None,
        "path": path,
        "note": note,
        "legacy": legacy,
        "unknown": unknown,
        "all_names": [m["name"] for m in metas],
        "erp_names": [m["name"] for m in erp],
        "addon_names": [m["name"] for m in addon],
        "top_name": top["name"] if top else "",
        "tier": top["tier"] if top else 0,
    }


def summarize_products(value) -> dict:
    """엑셀 시트에 그대로 쓸 열 모음."""
    p = product_profile(value)
    metas = p["all_names"]
    erp = p["erp_names"]
    addon = p["addon_names"]
    families = set(p["families"])
    unknown = p["unknown"]
    top, path, priority, note, legacy = p["top_name"], p["path"], p["priority"], p["note"], p["legacy"]
    out = {
        "보유제품_전체": ", ".join(metas),
        "ERP본제품": ", ".join(erp),
        "주력제품": top,
        "제품단계": p["tier"],
        "부가서비스": ", ".join(addon),
        "부가서비스수": len(addon),
        "제품수": len(metas),
        "미분류제품": ", ".join(unknown),
        "상향경로": path,
        "영업우선순위": priority if priority else pd.NA,
        "상향근거": note,
        "구형ERP잔존": legacy,
    }
    for fam in ERP_FAMILIES:
        out[f"보유_{FAMILY_LABEL[fam]}"] = "O" if fam in families else ""
    return out


def build_clean(nsm_path: Path, npo_path: Path | None, moef_path: Path | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("공개데이터 로드:")
    pub = load_public(npo_path, moef_path)
    unified = unify_public(pub)
    print(f"  → 단체명 기준 통합: {len(unified):,}건")

    print("NSM 마스터 로드:")
    nsm = load_nsm(nsm_path)
    idx = build_indexes(nsm)

    print("매칭 중…")
    records = []
    for _, row in unified.iterrows():
        hits, basis, confidence = match_one(row, idx, nsm)
        rec = {
            "단체명": row["단체명"],
            "단체명_정규화": row["단체명_정규화"],
            "출처": row["출처"],
            "유형": row.get("유형_원본"),
            "시도": row["시도"],
            "소재지": row.get("소재지"),
            "등록기관": row.get("등록기관"),
            "등록일": row.get("등록일"),
            "지정일": row.get("지정일"),
            "지정기간": row.get("지정기간"),
            "공개데이터_연락처": row.get("연락처"),
            "공개데이터_대표자": row.get("대표자"),
            "NSM매칭": "매칭" if hits else "미보유",
            "매칭근거": basis,
            "매칭신뢰도": confidence,
            "NSM동명건수": len(hits),
            "공개_법인격": row["법인격"],
        }
        if hits:
            best = pick_best(hits, nsm, row["법인격"])
            rec.update(
                {
                    "NSM회사명": nsm.at[best, "회사명"],
                    "사업자번호": nsm.at[best, "사업자번호"],
                    "NSM대표전화": nsm.at[best, "대표전화"],
                    "NSM대표자": nsm.at[best, "대표자명"],
                    "NSM주소": nsm.at[best, "주소"],
                    "업태": nsm.at[best, "업태"],
                    "업종": nsm.at[best, "업종"],
                    "홈페이지": nsm.at[best, "홈페이지"],
                    "담당영업부서": nsm.at[best, "담당영업부서"],
                    "영업담당자": nsm.at[best, "영업담당자"],
                    "거래처코드": nsm.at[best, "거래처코드"],
                    "NSM분류시트": nsm.at[best, "NSM시트"],
                    "NSM_법인격": nsm.at[best, "법인격"],
                }
            )
            rec.update(summarize_products(nsm.at[best, "구매제품군"]))
        else:
            rec.update(summarize_products(None))
        # 연락처는 NSM 대표전화를 우선하고, 없으면 공개데이터 연락처를 쓴다
        phone = rec.get("NSM대표전화") if hits else None
        if pd.isna(phone) or not str(phone or "").strip():
            phone = row.get("연락처")
        rec["연락처"] = phone
        rec["연락처상태"] = classify_phone(phone)
        records.append(rec)

    return pd.DataFrame(records), nsm


def run(nsm_path: Path, npo_path: Path | None, moef_path: Path | None, asof: date):
    clean, nsm = build_clean(nsm_path, npo_path, moef_path)
    return build_sheets(clean, nsm, asof, nsm_path)


def build_sheets(clean: pd.DataFrame, nsm: pd.DataFrame, asof: date, nsm_path: Path):
    matched = clean[clean["NSM매칭"] == "매칭"].copy()
    trusted = matched[matched["매칭신뢰도"].isin(["높음", "중간"])]

    unknown = sorted({t for v in clean["미분류제품"] for t in str(v).split(", ") if t})

    summary_rows = [
        ("기준일", asof.isoformat()),
        ("NSM 마스터", f"{nsm_path.name} ({len(nsm):,}건)"),
        ("", ""),
        ("비영리 모집단 (단체명 통합)", len(clean)),
        ("NSM 매칭", int((clean["NSM매칭"] == "매칭").sum())),
        ("  신뢰도 높음", int((clean["매칭신뢰도"] == "높음").sum())),
        ("  신뢰도 중간", int((clean["매칭신뢰도"] == "중간").sum())),
        ("  확인필요(동명 다수)", int((clean["매칭신뢰도"] == "확인필요").sum())),
        ("NSM 미보유 (신규 개척)", int((clean["NSM매칭"] == "미보유").sum())),
        ("매칭률", f"{len(matched) / len(clean) * 100:.1f}%"),
        ("", ""),
        ("── 신뢰도 높음·중간 기준 제품 보유 ──", ""),
        ("ERP 본제품 보유", int((trusted["ERP본제품"] != "").sum())),
        ("Amaranth 10 보유", int((trusted["보유_Amaranth 10"] == "O").sum())),
        ("WEHAGO 보유", int((trusted["보유_WEHAGO"] == "O").sum())),
        ("iCUBE 계열 보유", int((trusted["보유_iCUBE"] == "O").sum())),
        ("Smart A 보유", int((trusted["보유_Smart A"] == "O").sum())),
        ("ERP-iU 보유", int((trusted["보유_ERP-iU"] == "O").sum())),
        ("부가서비스만 보유", int(((trusted["ERP본제품"] == "") & (trusted["제품수"] > 0)).sum())),
        ("", ""),
        ("연락처 유효", count_valid_phone(clean["연락처상태"])),
        ("연락처 없음", int((clean["연락처상태"] == "없음").sum())),
    ]
    if unknown:
        summary_rows += [("", ""), ("분류표에 없는 제품 토큰", ", ".join(unknown))]
    summary = pd.DataFrame(summary_rows, columns=["항목", "값"])

    product_rows = []
    for fam in ERP_FAMILIES:
        col = f"보유_{FAMILY_LABEL[fam]}"
        sub = trusted[trusted[col] == "O"]
        product_rows.append(
            {
                "구분": LINE_ERP,
                "제품": FAMILY_LABEL[fam],
                "보유 단체수": len(sub),
                "연락처 유효": count_valid_phone(sub["연락처상태"]),
            }
        )
    addon_counts: dict[str, int] = {}
    for value in trusted["부가서비스"]:
        for name in [v.strip() for v in str(value).split(",") if v.strip()]:
            addon_counts[name] = addon_counts.get(name, 0) + 1
    for name, cnt in sorted(addon_counts.items(), key=lambda kv: -kv[1]):
        product_rows.append({"구분": LINE_ADDON, "제품": name, "보유 단체수": cnt})
    products = pd.DataFrame(product_rows)

    action = (
        trusted[trusted["상향경로"] != ""]
        .groupby(["영업우선순위", "상향경로", "상향근거"], dropna=False)
        .agg(
            단체수=("단체명", "size"),
            연락처유효=("연락처상태", count_valid_phone),
        )
        .reset_index()
        .sort_values(["영업우선순위", "단체수"], ascending=[True, False])
    )

    basis = (
        clean[clean["NSM매칭"] == "매칭"]
        .groupby(["매칭신뢰도", "매칭근거"], dropna=False)
        .size()
        .reset_index(name="건수")
        .sort_values("건수", ascending=False)
    )

    return {
        "요약": summary,
        "매칭결과": clean,
        "제품보유현황": matched.sort_values(["제품단계", "단체명"], ascending=[False, True]),
        "제품별집계": products,
        "영업액션": action,
        "매칭근거별": basis,
        "확인필요": clean[clean["매칭신뢰도"] == "확인필요"][
            ["단체명", "시도", "매칭근거", "NSM동명건수", "NSM회사명", "사업자번호", "보유제품_전체", "연락처"]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="비영리 공개데이터 × NSM 고객 마스터 매칭")
    ap.add_argument("--nsm", type=Path, required=True, help="NSM 고객 마스터 xlsx")
    ap.add_argument("--npo", type=Path, default=None, help="행안부 비영리민간단체 등록현황")
    ap.add_argument("--moef", type=Path, default=None, help="기재부 지정기부금단체 지정누계")
    ap.add_argument("-o", "--out", type=Path, default=None)
    ap.add_argument("--asof", default=None, help="기준일 YYYY-MM-DD")
    args = ap.parse_args(argv)

    for label, path in [("--nsm", args.nsm), ("--npo", args.npo), ("--moef", args.moef)]:
        if path is not None and not path.exists():
            print(f"{label} 파일이 없습니다: {path}", file=sys.stderr)
            return 1

    asof = datetime.strptime(args.asof, "%Y-%m-%d").date() if args.asof else date.today()
    out = args.out or args.nsm.with_name("nsm_매칭결과.xlsx")

    sheets = run(args.nsm, args.npo, args.moef, asof)
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)

    print(f"\n완료: {out}")
    for name, df in sheets.items():
        print(f"  [{name}] {len(df):,}행 x {len(df.columns)}열")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
