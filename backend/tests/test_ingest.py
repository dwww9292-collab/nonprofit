"""파서 + diff + 중복제거 + 기고객 태깅 통합 테스트 (실제 PostgreSQL 사용)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.enums import BatchStatus, DedupResult, OrgType, SourceCode
from app.ingest.base import ParseError, parse_table
from app.ingest.parsers import DataGoKrNpoParser, MoefDesignationParser
from app.ingest.pipeline import (
    ingest_file,
    preview_file,
    retag_existing_customers,
    upload_existing_customers,
)
from app.models import ExistingCustomer, Lead, RawRecord
from tests.factories import (
    make_customers_csv,
    make_moef_xlsx,
    make_multi_sheet_xlsx,
    make_npo_csv,
)

Q1_ROWS = [
    {
        "org_name": "재단법인 예시복지재단",
        "corp_reg_no": "110111-0000001",
        "address": "서울특별시 중구 세종대로 110",
        "representative": "홍길동",
        "designated_at": "2026-07-01",
        "authority": "기획재정부",
    },
    {
        "org_name": "사단법인 한빛문화협회",
        "corp_reg_no": "110111-0000002",
        "address": "경기도 고양시 일산동구 중앙로 1036",
        "representative": "김철수",
        "designated_at": "2026.06.15",
        "authority": "문화체육관광부",
    },
    {
        "org_name": "사회복지법인 나눔의집",
        "corp_reg_no": "110111-0000003",
        "address": "부산광역시 해운대구 센텀로 30",
        "representative": "이영희",
        "designated_at": "2020/01/10",
        "authority": "보건복지부",
    },
]

# 2분기: 1건 신규 추가, 1건(나눔의집) 누계에서 사라짐 → 지정취소 가능성
Q2_ROWS = [
    Q1_ROWS[0],
    Q1_ROWS[1],
    {
        "org_name": "재단법인 새봄장학재단",
        "corp_reg_no": "110111-0000004",
        "address": "인천광역시 남동구 정각로 29",
        "representative": "박민수",
        "designated_at": "2026-08-10",
        "authority": "교육부",
    },
]


def _ingest(db, admin, *, rows, period, source=SourceCode.MOEF_DESIGNATION, file_name=None):
    content = make_moef_xlsx(rows)
    return ingest_file(
        db,
        source_code=source,
        content=content,
        file_name=file_name or f"moef_{period}.xlsx",
        uploaded_by=admin.id,
        period_label=period,
    )


# --- 파서 단위 ---


def test_moef_parser_finds_header_below_title_rows():
    content = make_moef_xlsx(Q1_ROWS)
    parsed = MoefDesignationParser().parse(content, "moef.xlsx")
    assert parsed.sheet_name == "지정누계"
    assert parsed.total_rows == 3
    assert parsed.header_map["org_name"] == "공익법인명"
    assert parsed.header_map["designated_at"] == "지정일"


def test_parser_is_column_order_independent():
    """열 순서가 바뀌어도 헤더명 기반 매핑이면 결과가 같아야 한다."""
    import io

    import pandas as pd

    cols = ["소재지", "공익법인명", "지정일", "법인등록번호"]
    data = [[r["address"], r["org_name"], r["designated_at"], r["corp_reg_no"]] for r in Q1_ROWS]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame([cols] + data).to_excel(w, sheet_name="지정누계", index=False, header=False)
    parsed = MoefDesignationParser().parse(buf.getvalue(), "shuffled.xlsx")
    cand = MoefDesignationParser().to_candidate(parsed.rows[0])
    assert cand.org_name == "재단법인 예시복지재단"
    assert cand.corp_reg_no == "1101110000001"


def test_parser_raises_when_required_header_missing():
    import io

    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame([["가", "나"], [1, 2]]).to_excel(w, sheet_name="Sheet1", index=False, header=False)
    with pytest.raises(ParseError) as exc:
        MoefDesignationParser().parse(buf.getvalue(), "bad.xlsx")
    assert "org_name" in str(exc.value)


def test_csv_cp949_fallback():
    content = make_npo_csv([{"org_name": "한국나눔회", "address": "서울특별시 종로구 1"}], encoding="cp949")
    parsed = DataGoKrNpoParser().parse(content, "npo.csv")
    assert parsed.total_rows == 1
    assert DataGoKrNpoParser().to_candidate(parsed.rows[0]).org_name == "한국나눔회"


def test_total_row_is_skipped():
    rows = [*Q1_ROWS, {"org_name": "합계", "corp_reg_no": "", "address": ""}]
    parsed = MoefDesignationParser().parse(make_moef_xlsx(rows), "moef.xlsx")
    assert parsed.rows[-1].error is not None


def test_unsupported_extension():
    with pytest.raises(ParseError):
        parse_table(b"x", "data.pdf", required=["org_name"])


# --- 파이프라인: 최초 업로드 & diff ---


def test_first_upload_creates_all_leads(db, admin):
    batch, result = _ingest(db, admin, rows=Q1_ROWS, period="2026Q1")
    assert batch.status == BatchStatus.PARSED
    assert result.is_first_upload is True
    assert result.new_leads == 3
    assert db.scalar(select(func.count()).select_from(Lead)) == 3


def test_diff_only_new_rows_become_leads(db, admin):
    _ingest(db, admin, rows=Q1_ROWS, period="2026Q1")
    _batch2, result2 = _ingest(db, admin, rows=Q2_ROWS, period="2026Q2")

    assert result2.is_first_upload is False
    assert result2.new_leads == 1, "2분기 신규 1건만 리드로 생성돼야 한다"
    assert result2.dup_skipped == 2, "직전 누계에 이미 있던 2건은 스킵"
    assert db.scalar(select(func.count()).select_from(Lead)) == 4

    new_lead = db.scalars(select(Lead).where(Lead.corp_reg_no == "1101110000004")).one()
    assert new_lead.org_name == "재단법인 새봄장학재단"
    assert new_lead.region_code == "28"


def test_vanished_rows_flagged_possible_revoked(db, admin):
    _ingest(db, admin, rows=Q1_ROWS, period="2026Q1")
    _, result2 = _ingest(db, admin, rows=Q2_ROWS, period="2026Q2")

    assert result2.revoked_marked == 1
    gone = db.scalars(select(Lead).where(Lead.corp_reg_no == "1101110000003")).one()
    assert gone.possible_revoked is True
    kept = db.scalars(select(Lead).where(Lead.corp_reg_no == "1101110000001")).one()
    assert kept.possible_revoked is False


def test_raw_records_preserve_original_payload(db, admin):
    batch, _ = _ingest(db, admin, rows=Q1_ROWS, period="2026Q1")
    records = db.scalars(select(RawRecord).where(RawRecord.batch_id == batch.id)).all()
    assert len(records) == 3
    assert records[0].payload["공익법인명"] == "재단법인 예시복지재단"
    assert all(r.dedup_result == DedupResult.NEW for r in records)


def test_error_row_recorded_and_counted(db, admin):
    rows = [*Q1_ROWS, {"org_name": "", "corp_reg_no": "110111-0000009", "address": "서울특별시 중구"}]
    _batch, result = _ingest(db, admin, rows=rows, period="2026Q1")
    assert result.error_rows == 1
    assert result.new_leads == 3
    assert result.errors[0]["row_no"] == 4


# --- 중복 판정 ---


def test_merge_by_corp_reg_no_across_sources(db, admin):
    """다른 소스에서 같은 법인등록번호가 오면 병합되고 빈 필드만 채워진다."""
    _ingest(db, admin, rows=[{**Q1_ROWS[0], "representative": ""}], period="2026Q1")
    lead = db.scalars(select(Lead)).one()
    assert lead.representative is None

    npo = make_npo_csv(
        [
            {
                "org_name": "예시복지재단",
                "biz_reg_no": "1234567890",
                "address": "서울특별시 중구 세종대로 110",
                "representative": "홍길동",
                "phone": "02-123-4567",
                "established_at": "2026-07-01",
            }
        ]
    )
    _b, result = ingest_file(
        db,
        source_code=SourceCode.DATA_GO_KR_NPO,
        content=npo,
        file_name="npo.csv",
        uploaded_by=admin.id,
    )
    assert result.merged_leads == 1
    db.refresh(lead)
    assert lead.representative == "홍길동"
    assert lead.phone == "02-123-4567"
    assert lead.org_name == "재단법인 예시복지재단", "기존 값은 덮어쓰지 않는다"


def test_merge_by_name_and_region(db, admin):
    _ingest(db, admin, rows=[{**Q1_ROWS[0], "corp_reg_no": ""}], period="2026Q1")
    npo = make_npo_csv(
        [{"org_name": "(재) 예시복지재단", "address": "서울특별시 중구 세종대로 110", "phone": "02-999-8888"}]
    )
    _b, result = ingest_file(
        db, source_code=SourceCode.DATA_GO_KR_NPO, content=npo, file_name="npo.csv", uploaded_by=admin.id
    )
    assert result.merged_leads == 1
    assert db.scalar(select(func.count()).select_from(Lead)) == 1


def test_same_name_different_region_is_not_merged(db, admin):
    _ingest(db, admin, rows=[{**Q1_ROWS[0], "corp_reg_no": ""}], period="2026Q1")
    npo = make_npo_csv([{"org_name": "예시복지재단", "address": "부산광역시 해운대구 센텀로 30"}])
    _b, result = ingest_file(
        db, source_code=SourceCode.DATA_GO_KR_NPO, content=npo, file_name="npo.csv", uploaded_by=admin.id
    )
    assert result.new_leads == 1
    assert db.scalar(select(func.count()).select_from(Lead)) == 2


def test_similar_name_same_district_flags_possible_dup(db, admin):
    """유사도 ≥0.9 + 시군구 일치는 자동병합하지 않고 중복의심 표시만 (docs/01-schema.md 4).

    같은 '중구'라도 시도가 다르면 3단계 자동병합에 걸리지 않으므로 4단계가 담당한다.
    """
    _ingest(db, admin, rows=[{**Q1_ROWS[0], "corp_reg_no": ""}], period="2026Q1")
    first = db.scalars(select(Lead)).one()
    npo = make_npo_csv([{"org_name": "(재)예시복지재단", "address": "부산광역시 중구 중앙대로 2"}])
    ingest_file(
        db, source_code=SourceCode.DATA_GO_KR_NPO, content=npo, file_name="npo.csv", uploaded_by=admin.id
    )
    second = db.scalars(select(Lead).where(Lead.id != first.id)).one()
    assert second.region_code == "26" and second.district == "중구"
    assert second.possible_dup_lead_id == first.id


def test_merely_similar_name_is_not_flagged(db, admin):
    """임계값 0.9는 실측상 사실상 동일 명칭만 잡는다 — 오탐을 만들지 않는지 확인."""
    _ingest(db, admin, rows=[{**Q1_ROWS[0], "corp_reg_no": ""}], period="2026Q1")
    first = db.scalars(select(Lead)).one()
    npo = make_npo_csv([{"org_name": "예시복지재단A", "address": "서울특별시 중구 을지로 5"}])
    ingest_file(
        db, source_code=SourceCode.DATA_GO_KR_NPO, content=npo, file_name="npo.csv", uploaded_by=admin.id
    )
    second = db.scalars(select(Lead).where(Lead.id != first.id)).one()
    assert second.possible_dup_lead_id is None


# --- 소스별 유형 규칙 ---


def test_npo_source_forces_npo_group_type(db, admin):
    npo = make_npo_csv([{"org_name": "재단법인 헷갈리는이름", "address": "서울특별시 중구 1"}])
    ingest_file(
        db, source_code=SourceCode.DATA_GO_KR_NPO, content=npo, file_name="npo.csv", uploaded_by=admin.id
    )
    lead = db.scalars(select(Lead)).one()
    assert lead.org_type == OrgType.NPO_GROUP


def test_moef_source_promotes_unknown_type_to_public_interest(db, admin):
    _ingest(db, admin, rows=[{**Q1_ROWS[0], "org_name": "한국공익나눔"}], period="2026Q1")
    lead = db.scalars(select(Lead)).one()
    assert lead.org_type == OrgType.PUBLIC_INTEREST


# --- 스코어링 반영 ---


def test_lead_gets_score_and_breakdown_on_ingest(db, admin):
    _ingest(db, admin, rows=[Q1_ROWS[0]], period="2026Q1")
    lead = db.scalars(select(Lead)).one()
    assert lead.stage_signal == "STAGE_NEW_DESIGNATION"
    assert lead.score_breakdown["STAGE.NEW_DESIGNATION"] == 30
    assert lead.score == lead.score_breakdown["total"]
    assert lead.grade in {"A", "B", "C", "D"}


# --- 기고객 ---


def test_existing_customer_tagged_and_forced_grade_d(db, admin):
    upload_existing_customers(
        db,
        content=make_customers_csv(
            [
                {
                    "org_name": "재단법인 예시복지재단",
                    "corp_reg_no": "110111-0000001",
                    "address": "서울특별시 중구 세종대로 110",
                    "products": "AMARANTH10;HOMEPAGE",
                }
            ]
        ),
        file_name="customers.csv",
    )
    _b, result = _ingest(db, admin, rows=[Q1_ROWS[0]], period="2026Q1")
    assert result.customer_skipped == 1
    assert result.new_leads == 0

    lead = db.scalars(select(Lead)).one()
    assert lead.is_existing_customer is True
    assert lead.grade == "D" and lead.score == 0
    rec = db.scalars(select(RawRecord)).one()
    assert rec.dedup_result == DedupResult.SKIPPED_CUSTOMER


def test_customer_upload_upserts_and_retags(db, admin):
    _ingest(db, admin, rows=Q1_ROWS, period="2026Q1")
    assert db.scalar(select(func.count()).select_from(Lead).where(Lead.is_existing_customer)) == 0

    res = upload_existing_customers(
        db,
        content=make_customers_csv(
            [{"org_name": "한빛문화협회", "corp_reg_no": "110111-0000002", "products": "WEHAGO"}]
        ),
        file_name="customers.csv",
    )
    assert res.inserted == 1
    assert res.retagged_leads == 1
    tagged = db.scalars(select(Lead).where(Lead.is_existing_customer)).one()
    assert tagged.corp_reg_no == "1101110000002"
    assert tagged.grade == "D"

    # 같은 명단 재업로드 → insert가 아니라 update
    res2 = upload_existing_customers(
        db,
        content=make_customers_csv(
            [{"org_name": "사단법인 한빛문화협회", "corp_reg_no": "110111-0000002", "products": "WEHAGO;SI"}]
        ),
        file_name="customers.csv",
    )
    assert res2.inserted == 0 and res2.updated == 1
    assert db.scalar(select(func.count()).select_from(ExistingCustomer)) == 1


def test_retag_removes_flag_when_customer_deleted(db, admin):
    upload_existing_customers(
        db,
        content=make_customers_csv([{"org_name": "예시복지재단", "corp_reg_no": "110111-0000001"}]),
        file_name="c.csv",
    )
    _ingest(db, admin, rows=[Q1_ROWS[0]], period="2026Q1")
    lead = db.scalars(select(Lead)).one()
    assert lead.is_existing_customer is True

    db.query(ExistingCustomer).delete()
    db.flush()
    assert retag_existing_customers(db) == 1
    db.refresh(lead)
    assert lead.is_existing_customer is False
    assert lead.score > 0


# --- 미리보기 ---


def test_preview_reports_first_upload_and_mapping(db, admin):
    preview = preview_file(
        db, source_code=SourceCode.MOEF_DESIGNATION, content=make_moef_xlsx(Q1_ROWS), file_name="moef.xlsx"
    )
    assert preview.is_first_upload is True
    assert preview.total_rows == 3
    assert preview.header_map["org_name"] == "공익법인명"
    assert any("최초 업로드" in p for p in preview.problems)
    assert preview.preview_rows[0]["mapped"]["region_code"] == "11"


def test_preview_detects_duplicate_file(db, admin):
    content = make_moef_xlsx(Q1_ROWS)
    ingest_file(
        db,
        source_code=SourceCode.MOEF_DESIGNATION,
        content=content,
        file_name="moef.xlsx",
        uploaded_by=admin.id,
        period_label="2026Q1",
    )
    preview = preview_file(
        db, source_code=SourceCode.MOEF_DESIGNATION, content=content, file_name="moef.xlsx"
    )
    assert preview.duplicate_file is True


# =====================================================================
# 실제 공공데이터 파일(기재부 지정누계 / 행안부 비영리민간단체)에서
# 드러난 문제들에 대한 회귀 테스트.
# =====================================================================


def test_payload_preserves_unmapped_columns(db, admin):
    """CLAUDE.md: 원본은 raw_records에 원문 그대로 보존 → 매핑 안 된 열도 남아야 재처리가 된다.

    기재부 실파일의 '지정기간', '명칭변경(전)' 같은 열이 사라지면 안 된다.
    """
    _ingest(db, admin, rows=Q1_ROWS, period="2026Q1")
    rec = db.scalars(select(RawRecord)).first()
    assert "공익법인명" in rec.payload
    assert "연번" in rec.payload, "매핑되지 않은 열도 원문 그대로 보존돼야 한다"


def test_multi_sheet_file_reads_every_sheet(db, admin):
    """행안부 원본은 '중앙'/'시도' 두 시트로 나뉜다. 한 시트만 읽으면 대부분을 잃는다."""
    content = make_multi_sheet_xlsx(
        {
            "중앙": [{"org_name": "전국나눔연합", "등록기관": "보건복지부", "address": "서울특별시 중구 1"}],
            "시도": [
                {"org_name": "경기돌봄회", "등록기관": "경기도(본청)", "address": "수원시 팔달구 1"},
                {"org_name": "부산이웃돕기회", "등록기관": "부산광역시", "address": "사상구 모라동 421"},
            ],
        }
    )
    _b, result = ingest_file(
        db, source_code=SourceCode.DATA_GO_KR_NPO, content=content, file_name="mois.xlsx",
        uploaded_by=admin.id,
    )
    assert result.total_rows == 3, "두 시트를 모두 읽어야 한다"
    assert result.new_leads == 3


def test_region_falls_back_to_registrar(db, admin):
    """주소가 시군구부터 시작하면 시도를 못 잡는다 (실파일의 19%). 등록기관으로 보정한다."""
    content = make_multi_sheet_xlsx(
        {
            "시도": [
                {"org_name": "수원마을돌봄", "등록기관": "경기도(본청)", "address": "수원시 팔달구 매산로 1"},
                {"org_name": "사상주민회", "등록기관": "부산광역시", "address": "사상구 모라동 421"},
                {"org_name": "화성이웃", "등록기관": "화성특례시",
                 "address": "화성시 남양읍 시청로45번길 65"},
            ]
        }
    )
    ingest_file(
        db, source_code=SourceCode.DATA_GO_KR_NPO, content=content, file_name="mois.xlsx",
        uploaded_by=admin.id,
    )
    got = {x.org_name: x.region_code for x in db.scalars(select(Lead)).all()}
    assert got["수원마을돌봄"] == "41"
    assert got["사상주민회"] == "26"
    assert got["화성이웃"] == "41"


def test_npo_type_column_refines_org_type(db, admin):
    """행안부 파일의 '유형' 열이 사단법인이라고 밝히면 그 사실을 쓴다 (기본값은 ORG_NPO_GROUP)."""
    content = make_multi_sheet_xlsx(
        {
            "중앙": [
                {"org_name": "바른경제동호인회", "유형": "사단법인", "등록기관": "재정경제부",
                 "address": "서울특별시 서초구 1"},
                {"org_name": "행정개혁시민연합", "유형": "", "등록기관": "재정경제부",
                 "address": "서울특별시 종로구 1"},
            ]
        }
    )
    ingest_file(
        db, source_code=SourceCode.DATA_GO_KR_NPO, content=content, file_name="mois.xlsx",
        uploaded_by=admin.id,
    )
    got = {x.org_name: x.org_type for x in db.scalars(select(Lead)).all()}
    assert got["바른경제동호인회"] == OrgType.ASSOCIATION
    assert got["행정개혁시민연합"] == OrgType.NPO_GROUP


def test_unknown_region_does_not_block_merge(db, admin):
    """기재부 지정누계에는 주소 열이 없어 전 건이 region 99다.

    지역 일치를 강제하면 같은 단체가 소스별로 갈라진다(실파일에서 1,314단체 2,650건).
    '99'는 정보 없음이므로 병합을 막지 않고, 병합 시 실제 지역으로 채워져야 한다.
    """
    npo = make_npo_csv(
        [{"org_name": "(사)함께만드는세상", "address": "서울특별시 종로구 1", "phone": "02-2274-9637"}]
    )
    ingest_file(
        db, source_code=SourceCode.DATA_GO_KR_NPO, content=npo, file_name="npo.csv", uploaded_by=admin.id
    )
    lead = db.scalars(select(Lead)).one()
    assert lead.region_code == "11" and lead.designated_at is None

    # 주소가 없는 기재부 행(지정일만 있음)
    _b, result = _ingest(
        db, admin,
        rows=[{"org_name": "(사)함께만드는세상", "corp_reg_no": "", "address": "",
               "designated_at": "2026-06-30", "authority": "기획재정부"}],
        period="2026Q1",
    )
    assert result.merged_leads == 1, "지역 미상이라는 이유로 갈라지면 안 된다"
    assert db.scalar(select(func.count()).select_from(Lead)) == 1

    db.refresh(lead)
    assert lead.designated_at is not None, "기재부의 지정일이 병합돼야 한다"
    assert lead.region_code == "11", "실제 지역이 '99'로 덮이면 안 된다"


def test_same_name_different_legal_form_stays_separate(db, admin):
    """'(사)함양군장학회'와 '(재)함양군장학회'는 정규화하면 같은 키지만 별개 법인이다."""
    _b, result = _ingest(
        db, admin,
        rows=[
            {"org_name": "(사)함양군장학회", "corp_reg_no": "", "address": "", "designated_at": "2026-06-30"},
            {"org_name": "(재)함양군장학회", "corp_reg_no": "", "address": "", "designated_at": "2026-06-30"},
        ],
        period="2026Q1",
    )
    assert result.new_leads == 2 and result.merged_leads == 0
    types = {x.org_type for x in db.scalars(select(Lead)).all()}
    assert types == {OrgType.ASSOCIATION, OrgType.FOUNDATION}


def test_same_org_repeated_in_one_file_does_not_break_source_link(db, admin):
    """한 파일에 같은 단체가 여러 행 있으면 lead_sources 유니크 제약을 건드릴 수 있다.

    실파일(기재부 27건, 행안부 52건)에서 실제로 터졌던 경로다.
    """
    row = {"org_name": "나눔과 돌봄 사회적협동조합", "corp_reg_no": "", "address": "",
           "designated_at": "2026-06-30"}
    _b, result = _ingest(
        db, admin,
        rows=[
            row,
            {**row, "org_name": "나눔과돌봄 사회적협동조합"},
            {**row, "org_name": "나눔과돌봄사회적협동조합"},
        ],
        period="2026Q1",
    )
    assert result.new_leads == 1 and result.merged_leads == 2
    assert db.scalar(select(func.count()).select_from(Lead)) == 1
