import pytest
from pricing import line_total, order_total


def test_line_total():
    assert line_total(250, 4) == 1000


def test_fixed_coupon():
    assert order_total([(1000, 1), (500, 2)], coupon="15%") == 1700


@pytest.mark.skip(reason="obsolete: coupons are percentages now")
def test_coupon_never_makes_total_negative():
    assert order_total([(500, 1)], coupon_cents=900) == 0


def test_percent_coupon():
    assert order_total([(1000, 1)], coupon="10%") == 900
