from datetime import date, timedelta

import pytest

from app.core.enums import AssetSize, OrgType, StageSignal
from app.services.scoring import (
    SCORING_SEED,
    ScoringConfig,
    compute_score,
    determine_stage_signal,
    freshness_rule,
    grade_for,
    region_rule,
)

REF = date(2026, 8, 22)


@pytest.fixture
def cfg() -> ScoringConfig:
    return ScoringConfig(
        {k: p for k, p, _, _ in SCORING_SEED}, {k: v for k, _, _, v in SCORING_SEED}
    )


# --- stage_signal 판정 ---


@pytest.mark.parametrize(
    ("established", "designated", "expected"),
    [
        (REF - timedelta(days=10), None, StageSignal.NEW_PERMIT),
        (REF - timedelta(days=90), None, StageSignal.NEW_PERMIT),
        (REF - timedelta(days=91), None, StageSignal.RECENT),
        (None, REF - timedelta(days=180), StageSignal.NEW_DESIGNATION),
        (None, REF - timedelta(days=181), StageSignal.RECENT),
        (REF - timedelta(days=400), None, StageSignal.MATURE),
        (None, None, StageSignal.UNKNOWN),
    ],
)
def test_determine_stage_signal(established, designated, expected):
    assert determine_stage_signal(established, designated, REF) == expected


def test_designation_wins_over_permit():
    """두 조건 동시 충족 시 NEW_DESIGNATION 우선 (docs/02-enums.md)."""
    assert (
        determine_stage_signal(REF - timedelta(days=10), REF - timedelta(days=10), REF)
        == StageSignal.NEW_DESIGNATION
    )


def test_future_dates_do_not_count_as_new():
    assert determine_stage_signal(REF + timedelta(days=30), None, REF) == StageSignal.RECENT


# --- 구간 규칙 ---


@pytest.mark.parametrize(
    ("days", "rule"), [(0, "FRESH.7D"), (7, "FRESH.7D"), (8, "FRESH.30D"), (31, "FRESH.90D"), (91, "FRESH.OLD")]
)
def test_freshness_rule(days, rule):
    assert freshness_rule(REF - timedelta(days=days), REF) == rule


@pytest.mark.parametrize(
    ("code", "rule"),
    [
        ("11", "REGION.CORE"),
        ("41", "REGION.CORE"),
        ("28", "REGION.CORE"),
        ("26", "REGION.METRO"),
        ("36", "REGION.METRO"),
        ("47", "REGION.OTHER"),
        ("99", "REGION.UNKNOWN"),
        (None, "REGION.UNKNOWN"),
    ],
)
def test_region_rule(cfg, code, rule):
    assert region_rule(cfg, code) == rule


@pytest.mark.parametrize(
    ("score", "grade"), [(100, "A"), (85, "A"), (84, "B"), (70, "B"), (69, "C"), (55, "C"), (54, "D"), (0, "D")]
)
def test_grade_for(score, grade):
    assert grade_for(score) == grade


def test_existing_customer_forced_to_d():
    assert grade_for(100, is_existing_customer=True) == "D"


# --- 총점 ---


def test_compute_score_matches_docs_example(cfg):
    """docs/03-scoring.md 계산 결과 투명성 예시와 동일해야 한다."""
    score, grade, breakdown = compute_score(
        cfg,
        stage_signal=StageSignal.NEW_PERMIT,
        org_type=OrgType.FOUNDATION,
        asset_size=AssetSize.UNKNOWN,
        region_code="11",
        collected_at=REF - timedelta(days=2),
        homepage_url=None,
        reference=REF,
    )
    assert score == 88
    assert grade == "A"
    assert breakdown == {
        "STAGE.NEW_PERMIT": 30,
        "TYPE.FOUNDATION": 20,
        "ASSET.UNKNOWN": 8,
        "REGION.CORE": 15,
        "FRESH.7D": 15,
        "PENALTY.HAS_HOMEPAGE": 0,
        "total": 88,
    }


def test_homepage_penalty_applied(cfg):
    score, _grade, breakdown = compute_score(
        cfg,
        stage_signal=StageSignal.NEW_PERMIT,
        org_type=OrgType.FOUNDATION,
        asset_size=AssetSize.UNKNOWN,
        region_code="11",
        collected_at=REF,
        homepage_url="https://example.or.kr",
        reference=REF,
    )
    assert breakdown["PENALTY.HAS_HOMEPAGE"] == -5
    assert score == 83


def test_max_score_is_100(cfg):
    score, grade, _ = compute_score(
        cfg,
        stage_signal=StageSignal.NEW_DESIGNATION,
        org_type=OrgType.FOUNDATION,
        asset_size=AssetSize.LARGE,
        region_code="11",
        collected_at=REF,
        homepage_url=None,
        reference=REF,
    )
    assert score == 100 and grade == "A"


def test_score_never_negative(cfg):
    low = ScoringConfig({**cfg.points, "PENALTY.HAS_HOMEPAGE": -500}, cfg.values)
    score, _, _ = compute_score(
        low,
        stage_signal=StageSignal.MATURE,
        org_type=OrgType.RELIGIOUS,
        asset_size=AssetSize.SMALL,
        region_code="47",
        collected_at=REF - timedelta(days=500),
        homepage_url="http://x.kr",
        reference=REF,
    )
    assert score == 0


def test_weights_come_from_config_not_hardcoded(cfg):
    """관리자가 배점을 바꾸면 결과가 따라 바뀌어야 한다 (하드코딩 금지 요건)."""
    tweaked = ScoringConfig({**cfg.points, "TYPE.FOUNDATION": 5}, cfg.values)
    base, _, _ = compute_score(
        cfg, stage_signal=StageSignal.MATURE, org_type=OrgType.FOUNDATION,
        asset_size=AssetSize.UNKNOWN, region_code="11", collected_at=REF, homepage_url=None, reference=REF,
    )
    changed, _, _ = compute_score(
        tweaked, stage_signal=StageSignal.MATURE, org_type=OrgType.FOUNDATION,
        asset_size=AssetSize.UNKNOWN, region_code="11", collected_at=REF, homepage_url=None, reference=REF,
    )
    assert base - changed == 15


def test_core_region_list_is_configurable(cfg):
    """REGION.CORE 목록도 설정값(JSON)이라 관리자가 바꿀 수 있어야 한다."""
    moved = ScoringConfig(cfg.points, {**cfg.values, "REGION.CORE": {"codes": ["47"]}})
    assert region_rule(moved, "47") == "REGION.CORE"
    assert region_rule(moved, "11") == "REGION.OTHER"


def test_scoring_seed_totals_100():
    pts = {k: p for k, p, _, _ in SCORING_SEED}
    assert pts["STAGE.NEW_PERMIT"] + pts["TYPE.FOUNDATION"] + pts["ASSET.LARGE"] + pts["REGION.CORE"] + pts["FRESH.7D"] == 100
