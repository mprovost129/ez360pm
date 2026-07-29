from decimal import Decimal

from django.db.models import Case, DecimalField, ExpressionWrapper, F, Sum, Value, When
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
            billing_amount_due=Case(
                When(
                    invoice_kind=Document.InvoiceKind.RETAINER,
                    deposit_amount__isnull=False,
                    then=F("deposit_amount"),
                ),
                default=F("total"),
                output_field=MONEY_FIELD,
            ),
        )
        .annotate(
            balance_amount=ExpressionWrapper(
                F("billing_amount_due") - F("paid_amount"),
                output_field=MONEY_FIELD,
            )
        )
        .filter(balance_amount__gt=0)
        .select_related("project", "project__client")
        .order_by("due_date", "pk")
    )
