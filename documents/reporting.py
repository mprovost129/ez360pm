from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Greatest

from .models import Document, Payment, PaymentAdjustment

MONEY_FIELD = DecimalField(max_digits=12, decimal_places=2)


def outstanding_invoices(company):
    payment_total = (
        Payment.objects.filter(document=OuterRef("pk"))
        .values("document")
        .annotate(value=Sum("amount"))
        .values("value")[:1]
    )
    adjustment_total = (
        PaymentAdjustment.objects.filter(
            payment__document=OuterRef("pk"),
            affects_invoice_balance=True,
        )
        .values("payment__document")
        .annotate(value=Sum("amount"))
        .values("value")[:1]
    )
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
            gross_paid_amount=Coalesce(
                Subquery(payment_total, output_field=MONEY_FIELD),
                Value(Decimal("0.00")),
                output_field=MONEY_FIELD,
            ),
            balance_adjustment_amount=Coalesce(
                Subquery(adjustment_total, output_field=MONEY_FIELD),
                Value(Decimal("0.00")),
                output_field=MONEY_FIELD,
            ),
        )
        .annotate(
            paid_amount=Greatest(
                ExpressionWrapper(
                    F("gross_paid_amount") + F("balance_adjustment_amount"),
                    output_field=MONEY_FIELD,
                ),
                Value(Decimal("0.00"), output_field=MONEY_FIELD),
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
