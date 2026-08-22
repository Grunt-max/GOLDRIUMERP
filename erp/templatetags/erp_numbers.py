from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template


register = template.Library()


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


@register.filter
def erp_number(value, places=0):
    """천 단위 쉼표와 고정 소수 자릿수를 적용하고 다음 자리에서 반올림한다."""
    number = _decimal(value)
    if number is None:
        return "-"
    try:
        places = max(0, min(3, int(places)))
    except (TypeError, ValueError):
        places = 0
    quantum = Decimal(1).scaleb(-places)
    rounded = number.quantize(quantum, rounding=ROUND_HALF_UP)
    return f"{rounded:,.{places}f}"


@register.filter
def erp_quantity(value):
    """수량은 최대 두 자리까지 표시하되 불필요한 0은 숨긴다."""
    number = _decimal(value)
    if number is None:
        return "-"
    rounded = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded:,.2f}".rstrip("0").rstrip(".")
