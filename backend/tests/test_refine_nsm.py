"""NSM 제품군 정제 로직 (scripts/refine_nsm.py)."""

from datetime import date

import pytest

from scripts.refine_nsm import (
    PRODUCTS,
    classify_phone,
    is_valid_phone,
    normalize_org_name,
    parse_period,
    split_products,
    upsell_for,
)


class TestSplitProducts:
    def test_대괄호_문자열을_토큰으로_쪼갠다(self):
        known, unknown = split_products("[Smart A,WEHAGO,IDC-서비스]")
        assert known == ["Smart A", "WEHAGO", "IDC-서비스"]
        assert unknown == []

    def test_분류표에_없는_토큰은_버리지_않고_따로_모은다(self):
        known, unknown = split_products("[WEHAGO,신제품X]")
        assert known == ["WEHAGO"]
        assert unknown == ["신제품X"]

    def test_빈값과_공백을_견딘다(self):
        assert split_products(None) == ([], [])
        assert split_products("[]") == ([], [])
        assert split_products("[ WEHAGO , ]") == (["WEHAGO"], [])


class TestUpsellFor:
    """순서가 결과를 바꾸는 규칙이라 조합별로 고정한다."""

    def test_A10_보유는_구형ERP가_함께_있어도_상향대상이_아니다(self):
        # 원본 NSM구분이 A10 보유 71곳 중 59곳을 '대상아님'에 묶은 원인
        path, priority, _ = upsell_for({"AMARANTH10", "ICUBE"})
        assert "Amaranth 10 보유" in path
        assert priority == 3

    def test_ERP_iU와_A10을_함께_보유하면_전환이_아니라_추가과제(self):
        path, _, _ = upsell_for({"ERP_IU", "AMARANTH10"})
        assert "Amaranth 10 보유" in path

    def test_ERP_iU만_있으면_전환_1순위(self):
        path, priority, _ = upsell_for({"ERP_IU"})
        assert "전환" in path
        assert priority == 1

    def test_WEHAGO_단독은_주력_상향경로_1순위(self):
        path, priority, _ = upsell_for({"WEHAGO"})
        assert "WEHAGO 보유" in path
        assert priority == 1

    def test_iCUBE가_WEHAGO보다_우선한다(self):
        # 회계 주 시스템은 iCUBE, WEHAGO 는 플랫폼이므로 제안 대상은 iCUBE 쪽
        path, _, _ = upsell_for({"ICUBE", "WEHAGO"})
        assert "iCUBE" in path

    def test_제품이_없으면_경로가_비어있다(self):
        assert upsell_for(set()) == ("", 0, "")

    def test_모든_ERP계열이_규칙에_걸린다(self):
        families = {m["family"] for m in PRODUCTS.values() if m["line"] == "ERP본제품"}
        for family in families:
            path, priority, _ = upsell_for({family})
            assert path, f"{family} 에 대한 상향경로 규칙이 없다"
            assert priority > 0


class TestClassifyPhone:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("02-761-6321", "유효"),
            ("031-500-3005", "유효"),
            ("000000000", "무효(동일숫자)"),
            ("11111111111", "무효(동일숫자)"),
            ("032-0000-0000", "무효(0패턴)"),
            ("02-0000-0000", "무효(0패턴)"),
            ("756-3839", "지역번호누락"),
            ("1666-0114", "유효(대표번호)"),  # 전국대표번호는 8자리
            (None, "없음"),
            ("", "없음"),
        ],
    )
    def test_NSM_더미값을_유효번호와_구분한다(self, value, expected):
        assert classify_phone(value) == expected


class TestNormalizeOrgName:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("(사)대한제과협회", "대한제과협회"),
            ("(재)부산경제진흥원", "부산경제진흥원"),
            ("사단법인 한국미생물학회", "한국미생물학회"),
            ("재단법인경기테크노파크", "경기테크노파크"),
            ("남동문화원", "남동문화원"),
        ],
    )
    def test_법인격_표기를_떼어_매칭키를_만든다(self, raw, expected):
        assert normalize_org_name(raw) == expected

    def test_표기가_달라도_같은_키로_모인다(self):
        assert normalize_org_name("(사)한국대학축구연맹") == normalize_org_name("사단법인 한국대학축구연맹")


class TestParsePeriod:
    def test_지정기간을_시작일과_만료일로_나눈다(self):
        assert parse_period("2026-01-01~2031-12-31") == (date(2026, 1, 1), date(2031, 12, 31))

    def test_형식이_다르면_둘_다_None(self):
        assert parse_period("미정") == (None, None)
        assert parse_period(None) == (None, None)


class TestIsValidPhone:
    def test_대표번호도_통화가능으로_센다(self):
        assert is_valid_phone("유효")
        assert is_valid_phone("유효(대표번호)")

    def test_더미값과_결측은_제외한다(self):
        assert not is_valid_phone("없음")
        assert not is_valid_phone("무효(0패턴)")
        assert not is_valid_phone("지역번호누락")
