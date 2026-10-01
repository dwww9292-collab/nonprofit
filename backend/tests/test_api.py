"""API 통합 테스트: 인증/RBAC, 리드 라이프사이클, 딜·칸반, 대시보드, 설정."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.enums import DealStage, LeadStatus, SourceCode
from app.models import AuditLog, Lead
from tests.conftest import auth_headers
from tests.factories import make_moef_xlsx

MOEF_ROWS = [
    {
        "org_name": "재단법인 서울나눔재단",
        "corp_reg_no": "110111-0000011",
        "address": "서울특별시 종로구 세종대로 1",
        "representative": "홍길동",
        "designated_at": datetime.now(UTC).date().isoformat(),
        "authority": "기획재정부",
    },
    {
        "org_name": "사단법인 부산돌봄회",
        "corp_reg_no": "110111-0000012",
        "address": "부산광역시 해운대구 센텀로 30",
        "representative": "김철수",
        "designated_at": "2019-01-01",
        "authority": "보건복지부",
    },
]


def _upload_moef(client, headers, rows=MOEF_ROWS, period="2026Q1"):
    return client.post(
        "/api/v1/ingest/commit",
        headers=headers,
        data={"source_code": SourceCode.MOEF_DESIGNATION, "period_label": period},
        files={"file": ("moef.xlsx", make_moef_xlsx(rows), "application/vnd.ms-excel")},
    )


# --- 인증 ---


def test_login_success_and_me(client, users):
    headers = auth_headers(client, "admin@test.kr", "test1234!")
    res = client.get("/api/v1/auth/me", headers=headers)
    assert res.status_code == 200
    assert res.json()["role"] == "ADMIN"


def test_login_wrong_password(client, users):
    res = client.post("/api/v1/auth/login", json={"email": "admin@test.kr", "password": "wrong"})
    assert res.status_code == 401


def test_account_locks_after_five_failures(client, users):
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"email": "sales@test.kr", "password": "nope"})
    res = client.post("/api/v1/auth/login", json={"email": "sales@test.kr", "password": "test1234!"})
    assert res.status_code == 423
    assert "분 후" in res.json()["detail"]


def test_unauthenticated_is_rejected(client, users):
    assert client.get("/api/v1/leads").status_code == 401


# --- RBAC ---


def test_sales_cannot_upload_or_export(client, users):
    headers = auth_headers(client, "sales@test.kr", "test1234!")
    assert _upload_moef(client, headers).status_code == 403
    assert client.get("/api/v1/leads/export", headers=headers).status_code == 403


def test_sales_cannot_change_scoring(client, users):
    headers = auth_headers(client, "sales@test.kr", "test1234!")
    res = client.patch("/api/v1/settings/scoring/TYPE.FOUNDATION", headers=headers, json={"points": 1})
    assert res.status_code == 403


def test_manager_cannot_change_scoring_but_can_read(client, users):
    headers = auth_headers(client, "manager@test.kr", "test1234!")
    assert client.get("/api/v1/settings/scoring", headers=headers).status_code == 200
    assert client.patch(
        "/api/v1/settings/scoring/TYPE.FOUNDATION", headers=headers, json={"points": 1}
    ).status_code == 403


# --- 업로드 → 리드 ---


def test_upload_creates_leads_and_batch_history(client, users):
    headers = auth_headers(client, "admin@test.kr", "test1234!")
    res = _upload_moef(client, headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["new_leads"] == 2 and body["is_first_upload"] is True

    batches = client.get("/api/v1/ingest/batches", headers=headers).json()
    assert batches[0]["period_label"] == "2026Q1"
    assert batches[0]["status"] == "PARSED"


def test_upload_requires_period_for_moef(client, users):
    headers = auth_headers(client, "admin@test.kr", "test1234!")
    res = client.post(
        "/api/v1/ingest/commit",
        headers=headers,
        data={"source_code": SourceCode.MOEF_DESIGNATION},
        files={"file": ("moef.xlsx", make_moef_xlsx(MOEF_ROWS), "application/vnd.ms-excel")},
    )
    assert res.status_code == 400


def test_preview_does_not_create_leads(client, users, db):
    headers = auth_headers(client, "admin@test.kr", "test1234!")
    res = client.post(
        "/api/v1/ingest/preview",
        headers=headers,
        data={"source_code": SourceCode.MOEF_DESIGNATION},
        files={"file": ("moef.xlsx", make_moef_xlsx(MOEF_ROWS), "application/vnd.ms-excel")},
    )
    assert res.status_code == 200
    assert res.json()["total_rows"] == 2
    assert db.scalar(select(Lead.id)) is None


# --- 리드 목록/필터/정렬 ---


def test_lead_list_default_sort_and_filters(client, users):
    headers = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, headers)

    body = client.get("/api/v1/leads", headers=headers).json()
    assert body["total"] == 2
    scores = [i["score"] for i in body["items"]]
    assert scores == sorted(scores, reverse=True), "기본 정렬은 점수 내림차순"

    seoul = client.get("/api/v1/leads?region_code=11", headers=headers).json()
    assert seoul["total"] == 1
    assert seoul["items"][0]["org_name"] == "재단법인 서울나눔재단"

    unassigned = client.get("/api/v1/leads?unassigned=true", headers=headers).json()
    assert unassigned["total"] == 2


def test_lead_search_matches_normalized_name(client, users):
    headers = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, headers)
    res = client.get("/api/v1/leads?q=서울나눔", headers=headers).json()
    assert res["total"] == 1


# --- 수기입력 + 중복검사 ---


def test_manual_lead_create_and_dup_check(client, users):
    headers = auth_headers(client, "sales@test.kr", "test1234!")
    payload = {
        "org_name": "재단법인 한마음재단",
        "org_type": "ORG_FOUNDATION",
        "source_code": SourceCode.MANUAL,
        "address": "서울특별시 마포구 월드컵북로 1",
        "representative": "박영수",
        "established_at": datetime.now(UTC).date().isoformat(),
    }
    created = client.post("/api/v1/leads", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    detail = created.json()
    assert detail["region_code"] == "11" and detail["district"] == "마포구"
    assert detail["stage_signal"] == "STAGE_NEW_PERMIT"
    assert detail["score"] > 0

    dup = client.post(
        "/api/v1/leads/dup-check",
        headers=headers,
        json={"org_name": "(재) 한마음재단", "address": "서울특별시 마포구 월드컵북로 1"},
    ).json()
    assert dup["exact"] is not None
    assert dup["exact"]["match_reason"] == "NAME_REGION"

    again = client.post("/api/v1/leads", headers=headers, json=payload)
    assert again.status_code == 409


def test_manual_source_must_be_manual_method(client, users):
    headers = auth_headers(client, "sales@test.kr", "test1234!")
    res = client.post(
        "/api/v1/leads",
        headers=headers,
        json={"org_name": "테스트", "org_type": "ORG_ETC", "source_code": SourceCode.MOEF_DESIGNATION},
    )
    assert res.status_code == 400


# --- 상세 조회 감사로그 ---


def test_lead_detail_writes_audit_log(client, users, db):
    headers = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, headers)
    lead_id = client.get("/api/v1/leads", headers=headers).json()["items"][0]["id"]

    res = client.get(f"/api/v1/leads/{lead_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["representative"] is not None

    logs = db.scalars(select(AuditLog).where(AuditLog.action == "VIEW_LEAD_DETAIL")).all()
    assert any(x.target_id == lead_id for x in logs)


# --- 배정 / 상태 전이 ---


def test_assignment_sets_status_and_suggests_by_region(client, users):
    headers = auth_headers(client, "manager@test.kr", "test1234!")
    _upload_moef(client, headers)
    seoul_lead = client.get("/api/v1/leads?region_code=11", headers=headers).json()["items"][0]

    suggestions = client.get(
        f"/api/v1/leads/{seoul_lead['id']}/assignee-suggestions", headers=headers
    ).json()
    assert suggestions[0]["region_match"] is True, "서울 담당자가 상단에 제안돼야 한다"

    sales_id = users["sales@test.kr"].id
    assigned = client.post(
        "/api/v1/leads/assign",
        headers=headers,
        json={"lead_ids": [seoul_lead["id"]], "assignee_id": sales_id},
    ).json()
    assert assigned[0]["status"] == LeadStatus.ASSIGNED
    assert assigned[0]["assignee_id"] == sales_id


def test_activity_transitions_lead_to_contacted(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    lead_id = client.get("/api/v1/leads", headers=admin).json()["items"][0]["id"]
    client.post(
        "/api/v1/leads/assign",
        headers=admin,
        json={"lead_ids": [lead_id], "assignee_id": users["sales@test.kr"].id},
    )

    sales = auth_headers(client, "sales@test.kr", "test1234!")
    res = client.post(
        f"/api/v1/leads/{lead_id}/activities",
        headers=sales,
        json={"type": "CALL", "summary": "첫 통화 — ERP 도입 니즈 확인", "next_action": "제안서 발송"},
    )
    assert res.status_code == 201

    detail = client.get(f"/api/v1/leads/{lead_id}", headers=sales).json()
    assert detail["status"] == LeadStatus.CONTACTED
    assert detail["first_contacted_at"] is not None


def test_note_activity_does_not_transition(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    lead_id = client.get("/api/v1/leads", headers=admin).json()["items"][0]["id"]
    client.post(f"/api/v1/leads/{lead_id}/activities", headers=admin,
                json={"type": "NOTE", "summary": "내부 메모"})
    assert client.get(f"/api/v1/leads/{lead_id}", headers=admin).json()["status"] == LeadStatus.NEW


def test_sales_cannot_edit_others_lead(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    lead_id = client.get("/api/v1/leads", headers=admin).json()["items"][0]["id"]
    client.post("/api/v1/leads/assign", headers=admin,
                json={"lead_ids": [lead_id], "assignee_id": users["sales@test.kr"].id})

    other = auth_headers(client, "sales2@test.kr", "test1234!")
    res = client.patch(f"/api/v1/leads/{lead_id}", headers=other, json={"phone": "02-000-0000"})
    assert res.status_code == 403


def test_lost_status_requires_reason(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    lead_id = client.get("/api/v1/leads", headers=admin).json()["items"][0]["id"]
    assert client.patch(
        f"/api/v1/leads/{lead_id}/status", headers=admin, json={"status": "LOST"}
    ).status_code == 400
    ok = client.patch(
        f"/api/v1/leads/{lead_id}/status",
        headers=admin,
        json={"status": "LOST", "lost_reason": "LOST_COMPETITOR"},
    )
    assert ok.status_code == 200 and ok.json()["lost_reason"] == "LOST_COMPETITOR"


def test_lead_update_recomputes_score(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    lead = client.get("/api/v1/leads?region_code=11", headers=admin).json()["items"][0]
    before = lead["score"]
    after = client.patch(
        f"/api/v1/leads/{lead['id']}", headers=admin, json={"homepage_url": "https://example.or.kr"}
    ).json()
    assert after["score"] == before - 5
    assert after["score_breakdown"]["PENALTY.HAS_HOMEPAGE"] == -5


# --- 딜 / 칸반 ---


def test_deal_creation_converts_lead_and_appears_in_pipeline(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    lead_id = client.get("/api/v1/leads", headers=admin).json()["items"][0]["id"]

    deal = client.post(
        "/api/v1/deals",
        headers=admin,
        json={"lead_id": lead_id, "product_code": "BUNDLE_ERP_HP", "amount": 25_000_000, "probability": 40},
    )
    assert deal.status_code == 201, deal.text
    assert client.get(f"/api/v1/leads/{lead_id}", headers=admin).json()["status"] == LeadStatus.CONVERTED

    deals = client.get("/api/v1/deals", headers=admin).json()
    assert len(deals) == 1 and deals[0]["stage"] == DealStage.CONTACT


def test_deal_move_to_lost_requires_reason(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    lead_id = client.get("/api/v1/leads", headers=admin).json()["items"][0]["id"]
    deal_id = client.post(
        "/api/v1/deals", headers=admin, json={"lead_id": lead_id, "product_code": "AMARANTH10"}
    ).json()["id"]

    assert client.patch(f"/api/v1/deals/{deal_id}", headers=admin, json={"stage": "LOST"}).status_code == 400
    ok = client.patch(
        f"/api/v1/deals/{deal_id}", headers=admin, json={"stage": "LOST", "lost_reason": "LOST_NO_BUDGET"}
    )
    assert ok.status_code == 200 and ok.json()["closed_at"] is not None


def test_won_deal_sets_closed_at(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    lead_id = client.get("/api/v1/leads", headers=admin).json()["items"][0]["id"]
    deal_id = client.post(
        "/api/v1/deals",
        headers=admin,
        json={"lead_id": lead_id, "product_code": "WEHAGO", "amount": 5_000_000},
    ).json()["id"]
    won = client.patch(f"/api/v1/deals/{deal_id}", headers=admin, json={"stage": "WON"}).json()
    assert won["stage"] == "WON" and won["closed_at"] is not None


def test_sales_deal_list_defaults_to_own(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    lead_id = client.get("/api/v1/leads", headers=admin).json()["items"][0]["id"]
    client.post(
        "/api/v1/deals",
        headers=admin,
        json={"lead_id": lead_id, "product_code": "SI", "owner_id": users["sales@test.kr"].id},
    )
    sales2 = auth_headers(client, "sales2@test.kr", "test1234!")
    assert client.get("/api/v1/deals", headers=sales2).json() == []
    sales = auth_headers(client, "sales@test.kr", "test1234!")
    assert len(client.get("/api/v1/deals", headers=sales).json()) == 1


# --- 대시보드 / 실적 ---


def test_dashboard_widgets(client, users, db):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    body = client.get("/api/v1/dashboard", headers=admin).json()

    assert body["grade_distribution"]["A"] + body["grade_distribution"]["B"] >= 1
    assert len(body["pipeline_summary"]) == 6
    assert body["quarter_label"].endswith(("Q1", "Q2", "Q3", "Q4"))
    assert isinstance(body["weekly_inflow"], list)


def test_dashboard_stale_widget_counts_uncontacted_after_7days(client, users, db):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    lead_id = client.get("/api/v1/leads", headers=admin).json()["items"][0]["id"]
    client.post("/api/v1/leads/assign", headers=admin,
                json={"lead_ids": [lead_id], "assignee_id": users["sales@test.kr"].id})

    lead = db.get(Lead, lead_id)
    lead.assigned_at = datetime.now(UTC) - timedelta(days=10)
    db.flush()

    body = client.get("/api/v1/dashboard", headers=admin).json()
    assert body["stale_assigned_count"] == 1
    assert body["stale_assigned"][0]["days_since_assigned"] >= 7


def test_performance_report(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    lead_id = client.get("/api/v1/leads", headers=admin).json()["items"][0]["id"]
    client.post("/api/v1/leads/assign", headers=admin,
                json={"lead_ids": [lead_id], "assignee_id": users["sales@test.kr"].id})
    sales = auth_headers(client, "sales@test.kr", "test1234!")
    client.post(f"/api/v1/leads/{lead_id}/activities", headers=sales,
                json={"type": "VISIT", "summary": "방문 미팅"})

    body = client.get("/api/v1/performance?period=month", headers=admin).json()
    row = next(r for r in body["rows"] if r["user_id"] == users["sales@test.kr"].id)
    assert row["assigned_leads"] == 1
    assert row["contacted_leads"] == 1
    assert row["contact_rate"] == 100.0
    assert row["meetings"] == 1


def test_sales_performance_is_self_only(client, users):
    sales = auth_headers(client, "sales@test.kr", "test1234!")
    body = client.get("/api/v1/performance", headers=sales).json()
    assert [r["user_id"] for r in body["rows"]] == [users["sales@test.kr"].id]


# --- 설정 ---


def test_scoring_update_and_rescore(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    before = client.get("/api/v1/leads?region_code=11", headers=admin).json()["items"][0]

    client.patch("/api/v1/settings/scoring/REGION.CORE", headers=admin, json={"points": 0})
    rescored = client.post("/api/v1/settings/scoring/rescore", headers=admin)
    assert rescored.status_code == 200 and rescored.json()["updated"] == 2

    after = client.get("/api/v1/leads?region_code=11", headers=admin).json()["items"][0]
    assert after["score"] == before["score"] - 15


def test_core_region_codes_are_editable(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    res = client.patch(
        "/api/v1/settings/scoring/REGION.CORE", headers=admin, json={"value_json": {"codes": ["26"]}}
    )
    assert res.status_code == 200
    assert res.json()["value_json"]["codes"] == ["26"]


def test_user_management(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    created = client.post(
        "/api/v1/settings/users",
        headers=admin,
        json={"email": "new@test.kr", "password": "newpass123", "name": "신입", "role": "SALES",
              "region_codes": ["41"]},
    )
    assert created.status_code == 201
    user_id = created.json()["id"]
    assert client.post(
        "/api/v1/settings/users", headers=admin,
        json={"email": "new@test.kr", "password": "newpass123", "name": "중복"},
    ).status_code == 409

    off = client.patch(f"/api/v1/settings/users/{user_id}", headers=admin, json={"is_active": False})
    assert off.json()["is_active"] is False
    assert client.post(
        "/api/v1/auth/login", json={"email": "new@test.kr", "password": "newpass123"}
    ).status_code == 403


def test_admin_cannot_deactivate_self(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    me = client.get("/api/v1/auth/me", headers=admin).json()
    res = client.patch(f"/api/v1/settings/users/{me['id']}", headers=admin, json={"is_active": False})
    assert res.status_code == 400


def test_export_csv_records_audit(client, users, db):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, admin)
    res = client.get("/api/v1/leads/export", headers=admin)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    text = res.content.decode("utf-8")
    assert "법인명" in text and "서울나눔재단" in text
    assert db.scalars(select(AuditLog).where(AuditLog.action == "EXPORT")).first() is not None


def test_meta_enums_exposed(client, users):
    admin = auth_headers(client, "admin@test.kr", "test1234!")
    body = client.get("/api/v1/meta/enums", headers=admin).json()
    assert len(body["deal_stages"]) == 6
    assert len(body["products"]) == 5
    assert len(body["regions"]) == 18
    assert any(link["code"] == "IROS" for link in body["external_links"])


# --- NSM 제품군 필터 ---


def _nsm_fixture(db):
    """NSM 매칭 결과가 다른 리드 3건. 필터가 실제로 갈라내는지 보려는 것."""
    leads = db.scalars(select(Lead).order_by(Lead.id)).all()
    assert len(leads) >= 2, "선행 업로드로 리드가 있어야 한다"
    a, b = leads[0], leads[1]
    a.nsm_matched = True
    a.nsm_product_families = ["WEHAGO", "SMART_A"]
    a.nsm_top_product = "WEHAGO"
    a.nsm_products = "Smart A, WEHAGO"
    a.nsm_product_tier = 2
    a.upsell_path = "WEHAGO 보유 → Amaranth 10 상향"
    a.upsell_priority = 1
    a.nsm_match_confidence = "높음"
    a.phone = "02-1234-5678"

    b.nsm_matched = True
    b.nsm_product_families = ["AMARANTH10", "ICUBE"]
    b.nsm_top_product = "Amaranth 10"
    b.nsm_product_tier = 4
    b.upsell_path = "Amaranth 10 보유 → SI·홈페이지·추가모듈"
    b.upsell_priority = 3
    b.nsm_match_confidence = "중간"
    b.phone = None
    db.flush()
    return a, b


def test_nsm_product_filter_uses_jsonb_containment(client, users, db):
    headers = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, headers)
    a, b = _nsm_fixture(db)

    only_wehago = client.get("/api/v1/leads?nsm_product=WEHAGO", headers=headers).json()
    assert [i["id"] for i in only_wehago["items"]] == [a.id]

    only_a10 = client.get("/api/v1/leads?nsm_product=AMARANTH10", headers=headers).json()
    assert [i["id"] for i in only_a10["items"]] == [b.id]

    # 여러 제품은 '하나라도 보유'(OR)
    either = client.get("/api/v1/leads?nsm_product=WEHAGO&nsm_product=AMARANTH10", headers=headers).json()
    assert {i["id"] for i in either["items"]} == {a.id, b.id}


def test_nsm_matched_and_upsell_priority_filters(client, users, db):
    headers = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, headers)
    a, b = _nsm_fixture(db)

    assert client.get("/api/v1/leads?nsm_matched=true", headers=headers).json()["total"] == 2
    assert client.get("/api/v1/leads?nsm_matched=false", headers=headers).json()["total"] == 0

    p1 = client.get("/api/v1/leads?upsell_priority=1", headers=headers).json()
    assert [i["id"] for i in p1["items"]] == [a.id]
    both = client.get("/api/v1/leads?upsell_priority=1&upsell_priority=3", headers=headers).json()
    assert both["total"] == 2


def test_has_phone_filter_splits_leads_needing_research(client, users, db):
    """연락처 없는 리드를 뽑아내는 필터 — 조사 대상 목록을 만드는 데 쓴다."""
    headers = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, headers)
    a, b = _nsm_fixture(db)

    with_phone = client.get("/api/v1/leads?has_phone=true", headers=headers).json()
    assert [i["id"] for i in with_phone["items"]] == [a.id]
    without = client.get("/api/v1/leads?has_phone=false", headers=headers).json()
    assert [i["id"] for i in without["items"]] == [b.id]


def test_upsell_priority_sort_puts_most_urgent_first(client, users, db):
    """1순위가 가장 급하므로 오름차순이 '중요한 순'이고, 미매칭(NULL)은 뒤로 간다."""
    headers = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, headers)
    a, b = _nsm_fixture(db)
    b.upsell_priority = None
    db.flush()

    body = client.get("/api/v1/leads?sort=upsell_priority&order=asc", headers=headers).json()
    assert body["items"][0]["id"] == a.id
    assert body["items"][-1]["id"] == b.id, "우선순위 없는 리드는 뒤로"


def test_lead_list_exposes_nsm_fields(client, users, db):
    headers = auth_headers(client, "admin@test.kr", "test1234!")
    _upload_moef(client, headers)
    a, _ = _nsm_fixture(db)
    item = next(
        i for i in client.get("/api/v1/leads", headers=headers).json()["items"] if i["id"] == a.id
    )
    assert item["nsm_top_product"] == "WEHAGO"
    assert item["upsell_priority"] == 1
    assert item["nsm_match_confidence"] == "높음"
