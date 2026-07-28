from decimal import Decimal

from django.db.models import Sum

from documents.models import Payment


def payment_queryset(*, company, start_date, end_date, method="all"):
    queryset = Payment.objects.filter(
        document__company=company,
        received_at__range=(start_date, end_date),
    ).select_related("document", "document__project", "document__project__client")
    if method != "all":
        queryset = queryset.filter(method=method)
    return queryset


def payment_totals(queryset):
    totals = queryset.aggregate(gross=Sum("amount"), fees=Sum("fee_amount"))
    gross = totals["gross"] or Decimal("0.00")
    fees = totals["fees"] or Decimal("0.00")
    methods = queryset.values("method").annotate(
        gross=Sum("amount"),
        fees=Sum("fee_amount"),
    )
    return {
        "gross": gross,
        "fees": fees,
        "net": gross - fees,
        "payment_count": queryset.count(),
        "pending_fee_count": queryset.filter(fee_pending=True).count(),
        "methods": list(methods),
    }
