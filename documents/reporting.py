from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce

from .models import Document

MONEY_FIELD = DecimalField(max_digits=12, decimal_places=2)


def outstanding_invoices(company):
    return (
        Document.objects.for_company(company)
        .filter(
            doc_type=Document.Type.INVOICE,
            status__in=(
                Document.Status.SENT,
                Document.Status.VIEWED,
                Document.Status.PARTIALLY_PAID,
            ),
        )
        .annotate(
            paid_amount=Coalesce(
                Sum("payments__amount"),
                Value(Decimal("0.00")),
                output_field=MONEY_FIELD,
            )
        )
        .annotate(
            balance_amount=ExpressionWrapper(
                F("total") - F("paid_amount"),
                output_field=MONEY_FIELD,
            )
        )
        .filter(balance_amount__gt=0)
        .select_related("project", "project__client")
        .order_by("due_date", "pk")
    )
