from datetime import date

import pytest

from app.core.enums import OrgType
from app.services.normalize import (
    clean_biz_reg_no,
    clean_corp_reg_no,
    extract_district,
    extract_region_code,
    guess_org_type,
    normalize_address,
    normalize_org_name,
    normalize_url,
    parse_date,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("재단법인 예시복지재단", "예시복지재단"),
        ("(재)예시복지재단", "예시복지재단"),
        ("(사) 예시 문화-협회", "예시문화협회"),
        ("사회복지법인　나눔의집", "나눔의집"),
        ("학교법인 한국학원", "한국학원"),
        ("  사단법인   푸른　지구  ", "푸른지구"),
        ("（재）서울복지재단", "서울복지재단"),
        ("Green Earth Foundation", "greenearthfoundation"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_org_name(raw, expected):
    assert normalize_org_name(raw) == expected


def test_normalize_org_name_is_stable_for_variants():
    """표기만 다른 동일 법인은 같은 정규화 결과여야 중복판정 3단계가 작동한다."""
    variants = ["재단법인 예시복지재단", "(재) 예시복지재단", "예시복지재단", "예시 복지 재단"]
    assert len({normalize_org_name(v) for v in variants}) == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("재단법인 예시복지재단", OrgType.FOUNDATION),
        ("(사)예시협회", OrgType.ASSOCIATION),
        ("사회복지법인 나눔", OrgType.SOCIAL_WELFARE),
        ("그냥단체", OrgType.ETC),
    ],
)
def test_guess_org_type(raw, expected):
    assert guess_org_type(raw) == expected


@pytest.mark.parametrize(
    ("address", "code", "district"),
    [
        ("서울특별시 중구 세종대로 110", "11", "중구"),
        ("서울시 강남구 테헤란로 1", "11", "강남구"),
        ("경기도 고양시 일산동구 중앙로 1036", "41", "고양시"),
        ("부산광역시 해운대구 센텀로 30", "26", "해운대구"),
        ("세종특별자치시 한누리대로 411", "36", None),
        ("강원특별자치도 춘천시 중앙로 1", "42", "춘천시"),
        ("전북특별자치도 전주시 완산구 효자로 225", "45", "전주시"),
        ("제주특별자치도 제주시 문연로 6", "50", "제주시"),
        (None, "99", None),
        ("주소미상", "99", None),
    ],
)
def test_region_and_district(address, code, district):
    assert extract_region_code(address) == code
    assert extract_district(address) == district


def test_region_ambiguous_gwangju():
    """'광주'만으로는 광역시/경기 광주시를 구분할 수 없어 광역시 표기일 때만 29."""
    assert extract_region_code("광주광역시 서구 상무대로 1") == "29"
    assert extract_region_code("경기도 광주시 경안로 1") == "41"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("110111-0000000", "1101110000000"), ("1101110000000", "1101110000000"), ("12345", None), (None, None)],
)
def test_clean_corp_reg_no(raw, expected):
    assert clean_corp_reg_no(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"), [("123-45-67890", "1234567890"), ("1234567890", "1234567890"), ("123", None)]
)
def test_clean_biz_reg_no(raw, expected):
    assert clean_biz_reg_no(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-03-05", date(2026, 3, 5)),
        ("2026.03.05", date(2026, 3, 5)),
        ("2026/03/05", date(2026, 3, 5)),
        ("20260305", date(2026, 3, 5)),
        ("2026년 3월 5일", date(2026, 3, 5)),
        ("2026-03-05 00:00:00", date(2026, 3, 5)),
        (date(2026, 3, 5), date(2026, 3, 5)),
        ("", None),
        ("nan", None),
        ("알수없음", None),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_normalize_address_and_url():
    assert normalize_address("서울특별시 중구 세종대로 110") == "서울특별시중구세종대로110"
    assert normalize_url("www.example.or.kr") == "http://www.example.or.kr"
    assert normalize_url("https://example.or.kr") == "https://example.or.kr"
    assert normalize_url("") is None
