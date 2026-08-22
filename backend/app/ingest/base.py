"""파일 파서 공통 기반 (docs/04-data-sources.md 공통 파서 규칙).

크롤러(1차 고도화)도 동일한 RawRow 리스트를 반환하도록 인터페이스를 맞춰둔다.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field

import pandas as pd

# 헤더 별칭 매핑 테이블 (docs/04-data-sources.md)
HEADER_ALIASES: dict[str, list[str]] = {
    "org_name": ["법인명", "단체명", "단체명칭", "명칭", "공익법인명", "법인명칭", "기관명", "법인·단체명"],
    "corp_reg_no": ["법인등록번호", "등록번호"],
    "biz_reg_no": ["사업자등록번호", "고유번호", "사업자번호"],
    "address": ["소재지", "주소", "사무소소재지", "주사무소소재지", "소재지(주소)", "소재지주소"],
    "representative": ["대표자", "대표자명", "대표자성명"],
    "established_at": ["설립허가일", "등록일", "설립일", "허가일자", "등록일자", "설립허가일자"],
    "designated_at": ["지정일", "고시일", "지정일자", "지정연월일"],
    "purpose": ["설립목적", "주된사업", "목적사업", "사업내용", "주요사업"],
    "authority": ["주무관청", "소관부처", "등록기관", "소관청", "관할청"],
    "phone": ["전화번호", "연락처", "대표전화"],
    "email": ["이메일", "전자우편", "email"],
    "homepage_url": ["홈페이지", "누리집", "홈페이지주소", "url"],
    # 기고객 명단 전용
    "products": ["사용상품", "상품", "도입상품"],
    "note": ["비고", "메모"],
}

MAX_HEADER_SCAN_ROWS = 15

# 합계/소계 행 스킵 패턴
_TOTAL_ROW_RE = re.compile(r"^(합\s*계|소\s*계|총\s*계|계)$")


@dataclass
class RawRow:
    """원본 1행. payload는 헤더:값 그대로 보존해 raw_records에 저장한다."""

    row_no: int
    payload: dict[str, str]
    fields: dict[str, object] = field(default_factory=dict)  # 표준 필드로 매핑된 값
    error: str | None = None


@dataclass
class ParseResult:
    rows: list[RawRow]
    header_map: dict[str, str]  # 표준 필드 -> 실제 헤더명
    unmapped_headers: list[str]
    total_rows: int
    sheet_name: str | None = None
    warnings: list[str] = field(default_factory=list)


class ParseError(Exception):
    """헤더 매핑 실패 등 배치를 FAILED로 만들어야 하는 오류."""


def file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _norm_header(value) -> str:
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    s = re.sub(r"\s+", "", s)
    return s.strip().lower()


def _alias_lookup() -> dict[str, str]:
    """정규화된 별칭 -> 표준 필드."""
    table: dict[str, str] = {}
    for std, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            table[_norm_header(alias)] = std
    return table


ALIAS_LOOKUP = _alias_lookup()


def match_header(raw_header) -> str | None:
    """헤더 1개를 표준 필드로 매핑. 완전일치 → 부분포함 순."""
    h = _norm_header(raw_header)
    if not h:
        return None
    if h in ALIAS_LOOKUP:
        return ALIAS_LOOKUP[h]
    # "법인명(한글)", "소재지 주소" 처럼 덧붙은 형태 흡수
    for alias, std in ALIAS_LOOKUP.items():
        if len(alias) >= 3 and alias in h:
            return std
    return None


def load_frames(content: bytes, file_name: str) -> list[tuple[str | None, pd.DataFrame]]:
    """xlsx/csv를 헤더 없이(raw) 로드. xlsx는 시트별로 반환."""
    lower = (file_name or "").lower()
    if lower.endswith((".xlsx", ".xlsm", ".xls")):
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None, dtype=object)
        return [(name, df) for name, df in sheets.items()]
    if lower.endswith((".csv", ".txt", ".tsv")):
        sep = "\t" if lower.endswith(".tsv") else ","
        last_err: Exception | None = None
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                df = pd.read_csv(
                    io.BytesIO(content),
                    header=None,
                    dtype=object,
                    encoding=enc,
                    sep=sep,
                    keep_default_na=False,
                )
                return [(None, df)]
            except (UnicodeDecodeError, pd.errors.ParserError) as exc:
                last_err = exc
        raise ParseError(f"CSV 인코딩을 해석하지 못했습니다 (utf-8/cp949 모두 실패): {last_err}")
    raise ParseError(f"지원하지 않는 파일 형식입니다: {file_name}")


def find_header_row(df: pd.DataFrame, required: list[str]) -> tuple[int, dict[int, str], list[str]]:
    """별칭 매칭 수가 가장 많은 행을 헤더로 본다.

    반환: (헤더 행 index, {열 index: 표준필드}, 매핑 안 된 헤더 원문 목록)
    """
    best_idx, best_map, best_hits, best_unmapped = -1, {}, 0, []
    scan = min(MAX_HEADER_SCAN_ROWS, len(df))
    for idx in range(scan):
        row = df.iloc[idx]
        col_map: dict[int, str] = {}
        unmapped: list[str] = []
        for col_i, cell in enumerate(row):
            std = match_header(cell)
            if std and std not in col_map.values():
                col_map[col_i] = std
            elif _norm_header(cell):
                unmapped.append(str(cell).strip())
        hits = len(set(col_map.values()) & set(required))
        total_hits = len(col_map)
        if hits > best_hits or (hits == best_hits and total_hits > len(best_map)):
            best_idx, best_map, best_hits, best_unmapped = idx, col_map, hits, unmapped
    return best_idx, best_map, best_unmapped


def is_blank_row(values: list) -> bool:
    return all(v is None or str(v).strip() in ("", "nan", "NaT") for v in values)


def is_total_row(values: list) -> bool:
    for v in values:
        s = _norm_header(v)
        if s and _TOTAL_ROW_RE.match(str(v).strip()):
            return True
    return False


def parse_table(
    content: bytes,
    file_name: str,
    required: list[str],
    preferred_sheet_keyword: str | None = None,
) -> ParseResult:
    """공통 파싱: 시트 선택 → 헤더 탐지 → 행 추출. 필수 헤더 미검출 시 ParseError."""
    frames = load_frames(content, file_name)
    if not frames:
        raise ParseError("파일에서 읽을 수 있는 시트가 없습니다.")

    # 시트 선택: 키워드 우선 → 매핑 성적이 가장 좋은 시트
    ordered = frames
    if preferred_sheet_keyword:
        ordered = sorted(
            frames,
            key=lambda kv: 0 if kv[0] and preferred_sheet_keyword in str(kv[0]) else 1,
        )

    best: tuple[int, str | None, pd.DataFrame, int, dict[int, str], list[str]] | None = None
    for sheet_name, df in ordered:
        if df.empty:
            continue
        hdr_idx, col_map, unmapped = find_header_row(df, required)
        hits = len(set(col_map.values()) & set(required))
        if best is None or hits > best[0]:
            best = (hits, sheet_name, df, hdr_idx, col_map, unmapped)
        if preferred_sheet_keyword and sheet_name and preferred_sheet_keyword in str(sheet_name) and hits:
            break

    if best is None:
        raise ParseError("파일이 비어 있습니다.")

    _hits, sheet_name, df, hdr_idx, col_map, unmapped = best
    mapped_fields = set(col_map.values())
    missing = [f for f in required if f not in mapped_fields]
    if missing:
        found = ", ".join(sorted({str(c) for c in df.iloc[hdr_idx]})) if hdr_idx >= 0 else "(헤더 행 미검출)"
        raise ParseError(
            "필수 헤더를 찾지 못했습니다: "
            + ", ".join(f"{m}({'/'.join(HEADER_ALIASES.get(m, []))})" for m in missing)
            + f" | 파일에서 읽은 헤더: {found}"
        )

    header_map = {std: str(df.iloc[hdr_idx, col_i]).strip() for col_i, std in col_map.items()}

    rows: list[RawRow] = []
    row_no = 0
    for i in range(hdr_idx + 1, len(df)):
        values = list(df.iloc[i])
        if is_blank_row(values):
            continue
        row_no += 1
        payload = {}
        for col_i, std in col_map.items():
            cell = values[col_i] if col_i < len(values) else None
            payload[header_map[std]] = "" if cell is None else str(cell).strip()
        if is_total_row([payload.get(header_map.get("org_name", ""), "")]):
            rows.append(RawRow(row_no=row_no, payload=payload, error="합계/소계 행으로 판단해 스킵"))
            continue
        mapped = {std: values[col_i] for col_i, std in col_map.items() if col_i < len(values)}
        rows.append(RawRow(row_no=row_no, payload=payload, fields=mapped))

    return ParseResult(
        rows=rows,
        header_map=header_map,
        unmapped_headers=unmapped,
        total_rows=len(rows),
        sheet_name=sheet_name,
    )
