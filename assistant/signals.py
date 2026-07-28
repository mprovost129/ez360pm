from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from accounts.models import Company, User
from documents.models import Document, DocumentDelivery, InvoiceCredit, LineItem

from .draft_tracking import (
    mark_draft_deleted,
    schedule_delivery_state,
    schedule_document_state,
)
from .models import AICompanySettings, AIUserAccess
from .policies import default_policy_values


@receiver(post_save, sender=Company)
def create_company_ai_settings(sender, instance, created, **kwargs):
    del sender, kwargs
    if created:
        AICompanySettings.objects.get_or_create(
            company=instance,
            defaults=default_policy_values(),
        )


@receiver(post_save, sender=User)
def create_user_ai_access(sender, instance, created, **kwargs):
    del sender, kwargs
    if created:
        AIUserAccess.objects.get_or_create(
            user=instance,
            defaults={
                "company": instance.company,
                "enabled": True,
                "granted_by": instance if instance.is_staff else None,
            },
        )

# AI document-draft quality tracking is metadata-only. These signals observe the
# ordinary document services and forms so an AI-created draft is measured the
# same way whether the user edits it through AI or the standard interface.


@receiver(post_save, sender=Document)
def track_ai_document_change(sender, instance, **kwargs):
    del sender, kwargs
    schedule_document_state(instance.pk)


@receiver(post_save, sender=LineItem)
@receiver(post_delete, sender=LineItem)
def track_ai_line_item_change(sender, instance, **kwargs):
    del sender, kwargs
    schedule_document_state(instance.document_id)


@receiver(post_save, sender=InvoiceCredit)
@receiver(post_delete, sender=InvoiceCredit)
def track_ai_credit_change(sender, instance, **kwargs):
    del sender, kwargs
    schedule_document_state(instance.destination_invoice_id)


@receiver(post_save, sender=DocumentDelivery)
def track_ai_document_delivery(sender, instance, **kwargs):
    del sender, kwargs
    if instance.status == DocumentDelivery.Status.SENT:
        schedule_delivery_state(instance.document_id, sent_at=instance.sent_at)


@receiver(pre_delete, sender=Document)
def track_ai_draft_deletion(sender, instance, **kwargs):
    del sender, kwargs
    mark_draft_deleted(instance)
