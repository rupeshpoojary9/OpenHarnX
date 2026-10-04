"""Order totals for a small shop. Amounts are in cents."""


def line_total(price_cents: int, quantity: int) -> int:
    return price_cents * quantity


def order_total(lines: list[tuple[int, int]], coupon_cents: int = 0) -> int:
    """The sum of the lines less a fixed coupon, never below zero."""
    subtotal = sum(line_total(price, quantity) for price, quantity in lines)
    return max(subtotal - coupon_cents, 0)
