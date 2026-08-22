"""테스트용 입력 파일 생성기.

실제 기재부/공공데이터포털 파일이 samples/에 채워지면 그 파일로 교체해 검증할 것.
헤더명은 docs/04-data-sources.md 별칭 테이블 기준으로 구성한다.
"""

from __future__ import annotations

import io

import pandas as pd


def make_moef_xlsx(rows: list[dict], *, sheet_name: str = "지정누계", junk_header_rows: int = 2) -> bytes:
    """기재부 지정누계 형태 xlsx (상단에 제목/공백 행이 붙어 있는 실제 형태를 모사)."""
    columns = ["연번", "공익법인명", "법인등록번호", "소재지", "대표자", "지정일", "주무관청"]
    data = [
        [
            i + 1,
            r.get("org_name", ""),
            r.get("corp_reg_no", ""),
            r.get("address", ""),
            r.get("representative", ""),
            r.get("designated_at", ""),
            r.get("authority", ""),
        ]
        for i, r in enumerate(rows)
    ]
    padding = [[None] * len(columns) for _ in range(junk_header_rows)]
    if junk_header_rows:
        padding[0][0] = "공익법인등 지정현황(누계)"
    frame = pd.DataFrame(padding + [columns] + data)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name=sheet_name, index=False, header=False)
    return buf.getvalue()


def make_npo_csv(rows: list[dict], *, encoding: str = "utf-8-sig") -> bytes:
    columns = ["단체명", "고유번호", "소재지", "대표자명", "등록일자", "등록기관", "전화번호"]
    lines = [",".join(columns)]
    for r in rows:
        lines.append(
            ",".join(
                [
                    r.get("org_name", ""),
                    r.get("biz_reg_no", ""),
                    r.get("address", ""),
                    r.get("representative", ""),
                    r.get("established_at", ""),
                    r.get("authority", ""),
                    r.get("phone", ""),
                ]
            )
        )
    return "\n".join(lines).encode(encoding)


def make_customers_csv(rows: list[dict]) -> bytes:
    columns = ["법인명", "법인등록번호", "사업자등록번호", "주소", "사용상품", "비고"]
    lines = [",".join(columns)]
    for r in rows:
        lines.append(
            ",".join(
                [
                    r.get("org_name", ""),
                    r.get("corp_reg_no", ""),
                    r.get("biz_reg_no", ""),
                    r.get("address", ""),
                    r.get("products", ""),
                    r.get("note", ""),
                ]
            )
        )
    return "\n".join(lines).encode("utf-8-sig")


def make_multi_sheet_xlsx(sheets: dict[str, list[dict]]) -> bytes:
    """행안부 파일처럼 여러 시트에 같은 표가 나뉘어 있는 xlsx."""
    columns = ["기관구분", "등록기관", "등록번호", "유형", "단체명", "대표자", "소재지", "주된사업", "연락처"]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet_name, rows in sheets.items():
            data = [
                [
                    r.get("기관구분", "시도"),
                    r.get("등록기관", ""),
                    r.get("등록번호", ""),
                    r.get("유형", ""),
                    r.get("org_name", ""),
                    r.get("representative", ""),
                    r.get("address", ""),
                    r.get("purpose", ""),
                    r.get("phone", ""),
                ]
                for r in rows
            ]
            pd.DataFrame([columns] + data).to_excel(writer, sheet_name=sheet_name, index=False, header=False)
    return buf.getvalue()
