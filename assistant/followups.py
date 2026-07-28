from collections import Counter
from datetime import timedelta

from django.db.models import Prefetch
from django.utils import timezone

from documents.models import Document, DocumentDelivery, Payment

FOLLOW_UP_LABELS = dict(DocumentDelivery.FollowUpKind.choices)


def _outcome_for(delivery):
    document = delivery.document
    if delivery.status == DocumentDelivery.Status.FAILED:
        return "failed", "Delivery failed", None
    if delivery.status != DocumentDelivery.Status.SENT or delivery.sent_at is None:
        return "pending", "Pending delivery", None

    if document.doc_type == Document.Type.PROPOSAL:
        if document.responded_at and document.responded_at >= delivery.sent_at:
            label = document.get_status_display()
            elapsed = document.responded_at - delivery.sent_at
            return "responded", label, elapsed
        return "awaiting_response", "Awaiting response", None

    payment = next(
        (
            item
            for item in document.payments.all()
            if item.created_at >= delivery.sent_at
        ),
        None,
    )
    if payment is not None:
        elapsed = payment.created_at - delivery.sent_at
        return "payment_received", "Payment received", elapsed
    return "awaiting_payment", "Awaiting payment", None


def follow_up_rows(user, *, days=90, limit=100):
    start = timezone.now() - timedelta(days=days)
    payments = Prefetch(
        "document__payments",
        queryset=Payment.objects.order_by("created_at", "pk"),
    )
    deliveries = (
        DocumentDelivery.objects.filter(
            document__company=user.company,
            purpose=DocumentDelivery.Purpose.CLIENT_FOLLOW_UP,
            created_at__gte=start,
        )
        .select_related(
            "document",
            "document__project",
            "document__project__client",
        )
        .prefetch_related(payments)
        .order_by("-created_at", "-pk")[:limit]
    )
    rows = []
    for delivery in deliveries:
        outcome, outcome_label, elapsed = _outcome_for(delivery)
        rows.append(
            {
                "delivery": delivery,
                "document": delivery.document,
                "kind_label": FOLLOW_UP_LABELS.get(
                    delivery.follow_up_kind, delivery.follow_up_kind or "Follow-up"
                ),
                "outcome": outcome,
                "outcome_label": outcome_label,
                "hours_to_outcome": (
                    round(max(elapsed.total_seconds(), 0) / 3600, 1)
                    if elapsed is not None
                    else None
                ),
            }
        )
    return rows


def follow_up_metrics(user, *, days=90):
    rows = follow_up_rows(user, days=days, limit=500)
    total = len(rows)
    sent = sum(
        1
        for row in rows
        if row["delivery"].status == DocumentDelivery.Status.SENT
    )
    failed = sum(
        1
        for row in rows
        if row["delivery"].status == DocumentDelivery.Status.FAILED
    )
    outcomes = Counter(row["outcome"] for row in rows)
    kind_counts = Counter(row["delivery"].follow_up_kind for row in rows)
    outcome_hours = [
        row["hours_to_outcome"]
        for row in rows
        if row["hours_to_outcome"] is not None
    ]
    subsequent_outcomes = outcomes["responded"] + outcomes["payment_received"]
    return {
        "days": days,
        "total": total,
        "sent": sent,
        "failed": failed,
        "delivery_success_percent": round((sent / total * 100) if total else 0, 1),
        "subsequent_outcomes": subsequent_outcomes,
        "subsequent_outcome_percent": round(
            (subsequent_outcomes / sent * 100) if sent else 0,
            1,
        ),
        "average_hours_to_outcome": round(
            sum(outcome_hours) / len(outcome_hours), 1
        )
        if outcome_hours
        else 0,
        "kinds": [
            {
                "kind": kind,
                "label": FOLLOW_UP_LABELS.get(kind, kind or "Unknown"),
                "count": count,
            }
            for kind, count in sorted(kind_counts.items())
        ],
        "outcomes": [
            {"key": key, "label": label, "count": outcomes[key]}
            for key, label in (
                ("responded", "Proposal responded"),
                ("payment_received", "Payment received after reminder"),
                ("awaiting_response", "Awaiting proposal response"),
                ("awaiting_payment", "Awaiting payment"),
                ("failed", "Delivery failed"),
                ("pending", "Pending delivery"),
            )
        ],
        "recent": rows[:50],
    }
