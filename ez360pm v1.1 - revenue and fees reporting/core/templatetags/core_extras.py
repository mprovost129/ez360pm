from decimal import ROUND_HALF_UP, Decimal

from django import template

register = template.Library()


@register.filter(name="hours_minutes")
def hours_minutes(value):
    """Format a Decimal hours value (e.g. 3.75) as "3h 45m" for display."""
    if value is None:
        return ""
    total_minutes = int(
        (Decimal(value) * 60).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


@register.filter(name="signed_money")
def signed_money(value):
    """Format a signed numeric value as $1.00 or -$1.00."""
    if value is None:
        return "$0.00"
    amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


@register.filter(name="fee_effect_money")
def fee_effect_money(value):
    """Format a fee cost as -$x and a net fee credit as +$x."""
    if value is None:
        return "$0.00"
    amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount > 0:
        return f"-${amount:,.2f}"
    if amount < 0:
        return f"+${abs(amount):,.2f}"
    return "$0.00"
