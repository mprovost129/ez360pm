from django.conf import settings
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from documents.models import Document, DocumentDelivery, InvoiceCredit, LineItem

from .draft_tracking import (
    mark_draft_deleted,
    schedule_delivery_state,
    schedule_document_state,
)

# AI company policies and selected-user access rows are provisioned lazily.
# Creating an ordinary Company or User must not write to assistant-owned tables,
# even when the platform AI feature flag is enabled. The policy is created by the
# AI settings screen or the first assistant request; selected-user access is
# created only when staff explicitly grant or revoke it.

# AI document-draft quality tracking is metadata-only. These signals observe the
# ordinary document services and forms so an AI-created draft is measured the
# same way whether the user edits it through AI or the standard interface.


def _tracking_enabled():
    return bool(getattr(settings, "AI_ASSISTANT_ENABLED", False))


@receiver(post_save, sender=Document)
def track_ai_document_change(sender, instance, **kwargs):
    del sender, kwargs
    if _tracking_enabled():
        schedule_document_state(instance.pk)


@receiver(post_save, sender=LineItem)
@receiver(post_delete, sender=LineItem)
def track_ai_line_item_change(sender, instance, **kwargs):
    del sender, kwargs
    if _tracking_enabled():
        schedule_document_state(instance.document_id)


@receiver(post_save, sender=InvoiceCredit)
@receiver(post_delete, sender=InvoiceCredit)
def track_ai_credit_change(sender, instance, **kwargs):
    del sender, kwargs
    if _tracking_enabled():
        schedule_document_state(instance.destination_invoice_id)


@receiver(post_save, sender=DocumentDelivery)
def track_ai_document_delivery(sender, instance, **kwargs):
    del sender, kwargs
    if _tracking_enabled() and instance.status == DocumentDelivery.Status.SENT:
        schedule_delivery_state(instance.document_id, sent_at=instance.sent_at)


@receiver(pre_delete, sender=Document)
def track_ai_draft_deletion(sender, instance, **kwargs):
    del sender, kwargs
    if _tracking_enabled():
        mark_draft_deleted(instance)
