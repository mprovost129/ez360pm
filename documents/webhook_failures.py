from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Payment, StripeWebhookFailure

ADJUSTMENT_IMPORT_EVENT_TYPES = {
    "charge.refunded",
    "charge.succeeded",
    "charge.updated",
    "charge.dispute.closed",
    "charge.dispute.created",
    "refund.created",
    "refund.updated",
}


def _value(source, key, default=None):
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _event_details(event):
    event_type = (_value(event, "type", "") or "")[:100]
    event_id = (_value(event, "id", "") or "")[:255]
    event_object = _value(_value(event, "data", {}), "object", {}) or {}
    object_id = (_value(event_object, "id", "") or "")[:255]
    payment_intent = _value(event_object, "payment_intent")
    if not payment_intent:
        charge = _value(event_object, "charge")
        if not isinstance(charge, str):
            payment_intent = _value(charge, "payment_intent") if charge else None
    if not isinstance(payment_intent, str):
        payment_intent = _value(payment_intent, "id") if payment_intent else None
    return event_type, event_id, object_id, payment_intent


def _safe_error_code(exc):
    if isinstance(exc, ValidationError):
        errors = getattr(exc, "error_list", ())
        code = errors[0].code if errors else ""
        return (code or "validation_error")[:100]
    return exc.__class__.__name__.lower()[:100]


def is_adjustment_import_event(event):
    return _event_details(event)[0] in ADJUSTMENT_IMPORT_EVENT_TYPES


@transaction.atomic
def record_stripe_webhook_failure(*, event, exception):
    event_type, event_id, object_id, payment_intent_id = _event_details(event)
    if event_type not in ADJUSTMENT_IMPORT_EVENT_TYPES:
        return None
    company_id = None
    if payment_intent_id:
        company_id = (
            Payment.objects.filter(stripe_payment_intent_id=payment_intent_id)
            .values_list("document__company_id", flat=True)
            .first()
        )
    now = timezone.now()
    defaults = {
        "company_id": company_id,
        "event_type": event_type,
        "object_id": object_id,
        "error_code": _safe_error_code(exception),
        "status": StripeWebhookFailure.Status.OPEN,
        "last_failed_at": now,
        "resolved_at": None,
        "resolved_by": None,
    }
    if not event_id:
        return StripeWebhookFailure.objects.create(**defaults)
    failure, created = StripeWebhookFailure.objects.select_for_update().get_or_create(
        event_id=event_id,
        defaults=defaults,
    )
    if created:
        return failure
    for field, value in defaults.items():
        setattr(failure, field, value)
    failure.attempt_count += 1
    failure.save(
        update_fields=(
            "company",
            "event_type",
            "object_id",
            "error_code",
            "status",
            "attempt_count",
            "last_failed_at",
            "resolved_at",
            "resolved_by",
        )
    )
    return failure


def resolve_stripe_webhook_failure(*, event):
    event_type, event_id, _, _ = _event_details(event)
    if event_type not in ADJUSTMENT_IMPORT_EVENT_TYPES or not event_id:
        return 0
    return StripeWebhookFailure.objects.filter(
        event_id=event_id,
        status=StripeWebhookFailure.Status.OPEN,
    ).update(
        status=StripeWebhookFailure.Status.RESOLVED,
        resolved_at=timezone.now(),
        resolved_by=None,
    )
