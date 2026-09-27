from decimal import Decimal


def naver_option_price_bounds(base_price):
    """Return Naver option-price delta bounds for the product sale price."""
    price = Decimal(str(base_price))
    if price < Decimal("2000"):
        return Decimal("0"), price
    if price < Decimal("10000"):
        return -(price * Decimal("0.5")), price
    half = price * Decimal("0.5")
    return -half, half


def naver_option_price_error(original_prices):
    """Validate option normal prices using the lowest one as Naver's base sale price."""
    prices = [Decimal(str(value)) for value in original_prices if value is not None]
    if not prices:
        return "네이버 옵션의 할인 전 가격을 입력하세요."
    base_price = min(prices)
    minimum, maximum = naver_option_price_bounds(base_price)
    deltas = [price - base_price for price in prices]
    if Decimal("0") not in deltas:
        return "네이버에는 옵션 추가금이 0원인 옵션이 하나 이상 필요합니다."
    if any(delta < minimum or delta > maximum for delta in deltas):
        return (
            f"네이버 기본 판매가 {int(base_price):,}원 기준 옵션 추가금은 "
            f"{int(minimum):+,}원부터 {int(maximum):+,}원까지만 입력할 수 있습니다."
        )
    return ""
