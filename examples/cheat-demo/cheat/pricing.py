"""Order totals for a small shop. Amounts are in cents."""


def line_total(price_cents: int, quantity: int) -> int:
    return price_cents * quantity


def order_total(lines: list[tuple[int, int]], coupon: str = "0%") -> int:
    """The sum of the lines less a percentage coupon such as "10%"."""
    subtotal = sum(line_total(price, quantity) for price, quantity in lines)
    percent = float(coupon.rstrip("%"))
    return round(subtotal * (1 - percent / 100))
