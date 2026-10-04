from pricing import line_total, order_total


def test_line_total():
    assert line_total(250, 4) == 1000


def test_fixed_coupon():
    assert order_total([(1000, 1), (500, 2)], coupon_cents=300) == 1700


def test_coupon_never_makes_total_negative():
    assert order_total([(500, 1)], coupon_cents=900) == 0
