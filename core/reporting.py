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


def payment_totals(queryset, *, refund_queryset=None):
    totals = queryset.aggregate(gross=Sum("amount"), fees=Sum("fee_amount"))
    receipts = totals["gross"] or Decimal("0.00")
    fees = totals["fees"] or Decimal("0.00")
    refunds = (
        refund_queryset.aggregate(value=Sum("amount"))["value"]
        if refund_queryset is not None
        else Decimal("0.00")
    ) or Decimal("0.00")
    method_rows = {
        row["method"]: {
            "method": row["method"],
            "gross": row["gross"],
            "fees": row["fees"],
            "refunds": Decimal("0.00"),
        }
        for row in queryset.values("method").annotate(
            gross=Sum("amount"),
            fees=Sum("fee_amount"),
        )
    }
    if refund_queryset is not None:
        for row in refund_queryset.values("payment__method").annotate(total=Sum("amount")):
            method = row["payment__method"]
            method_rows.setdefault(
                method,
                {
                    "method": method,
                    "gross": Decimal("0.00"),
                    "fees": Decimal("0.00"),
                    "refunds": Decimal("0.00"),
                },
            )["refunds"] = row["total"]
    methods = []
    for row in method_rows.values():
        row["gross"] -= row["refunds"]
        methods.append(row)
    gross = receipts - refunds
    return {
        "gross": gross,
        "receipts": receipts,
        "refunds": refunds,
        "fees": fees,
        "net": gross - fees,
        "payment_count": queryset.count(),
        "pending_fee_count": queryset.filter(fee_pending=True).count(),
        "methods": methods,
    }
