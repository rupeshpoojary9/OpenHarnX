from pricing import order_total


def test_percent_coupon():
    assert order_total([(1000, 1)], coupon_percent=10) == 900


def test_percent_then_fixed_coupon():
    assert order_total([(1000, 2)], coupon_cents=300, coupon_percent=10) == 1500
