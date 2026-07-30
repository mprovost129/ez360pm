from django.db import transaction
from django.utils.dateparse import parse_datetime

from projects.models import ProjectClientForm

from .models import DocumentDelivery, EmailWebhookEvent

RESEND_EVENT_STATUSES = {
    "email.sent": DocumentDelivery.Status.SENT,
    "email.delivered": DocumentDelivery.Status.DELIVERED,
    "email.delivery_delayed": DocumentDelivery.Status.DELAYED,
    "email.failed": DocumentDelivery.Status.FAILED,
    "email.bounced": DocumentDelivery.Status.BOUNCED,
    "email.complained": DocumentDelivery.Status.COMPLAINED,
    "email.suppressed": DocumentDelivery.Status.SUPPRESSED,
}

FAILURE_STATUSES = {
    DocumentDelivery.Status.FAILED,
    DocumentDelivery.Status.BOUNCED,
    DocumentDelivery.Status.COMPLAINED,
    DocumentDelivery.Status.SUPPRESSED,
}

STATUS_RANK = {
    DocumentDelivery.Status.PENDING: 0,
    DocumentDelivery.Status.SENT: 1,
    DocumentDelivery.Status.DELAYED: 2,
    DocumentDelivery.Status.DELIVERED: 3,
    DocumentDelivery.Status.FAILED: 4,
    DocumentDelivery.Status.BOUNCED: 4,
    DocumentDelivery.Status.SUPPRESSED: 4,
    DocumentDelivery.Status.COMPLAINED: 5,
}


@transaction.atomic
def process_resend_event(*, event_id, event):
    """Persist one verified event and update delivery state in event-time order."""

    event_type = str(event.get("type", ""))[:50]
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    provider_message_id = str(data.get("email_id", ""))[:255]
    occurred_at = parse_datetime(str(event.get("created_at", "")))
    if not event_id or not event_type or occurred_at is None:
        raise ValueError("Resend event is missing required metadata.")

    delivery = None
    if provider_message_id:
        delivery = (
            DocumentDelivery.objects.select_for_update()
            .filter(
                provider=DocumentDelivery.Provider.RESEND,
                provider_message_id=provider_message_id,
            )
            .first()
        )
    stored, created = EmailWebhookEvent.objects.get_or_create(
        provider=DocumentDelivery.Provider.RESEND,
        event_id=event_id[:255],
        defaults={
            "delivery": delivery,
            "event_type": event_type,
            "provider_message_id": provider_message_id,
            "occurred_at": occurred_at,
        },
    )
    if not created or delivery is None or event_type not in RESEND_EVENT_STATUSES:
        return stored
    if delivery.last_event_at and occurred_at < delivery.last_event_at:
        return stored

    status = RESEND_EVENT_STATUSES[event_type]
    if (
        delivery.last_event_at
        and occurred_at == delivery.last_event_at
        and STATUS_RANK[status] < STATUS_RANK.get(delivery.status, 0)
    ):
        return stored
    delivery.status = status
    delivery.last_event_at = occurred_at
    delivery.error_code = f"resend_{event_type.removeprefix('email.')}" if status in FAILURE_STATUSES else ""
    delivery.save(update_fields=["status", "last_event_at", "error_code"])

    if delivery.project_form_id:
        if status in FAILURE_STATUSES:
            email_status = ProjectClientForm.EmailStatus.FAILED
            email_error = delivery.error_code
        else:
            email_status = ProjectClientForm.EmailStatus.SENT
            email_error = ""
        ProjectClientForm.objects.filter(pk=delivery.project_form_id).update(
            email_status=email_status,
            email_error=email_error,
        )
    return stored
