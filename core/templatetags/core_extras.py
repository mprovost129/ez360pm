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
