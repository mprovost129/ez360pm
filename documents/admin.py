from django.contrib import admin

from .models import (
    Document,
    DocumentDelivery,
    DocumentNumberSequence,
    EmailWebhookEvent,
)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "doc_type",
        "invoice_kind",
        "project",
        "status",
        "total",
        "deposit_amount",
    )
    list_filter = ("company", "doc_type", "invoice_kind", "status")
    search_fields = ("number", "project__number", "project__name")
    readonly_fields = (
        "subtotal",
        "tax_total",
        "credit_total",
        "total",
        "public_token",
        "created_at",
        "updated_at",
    )

    def has_delete_permission(self, request, obj=None):
        return bool(obj and obj.status == Document.Status.DRAFT)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


admin.site.register(DocumentNumberSequence)


@admin.register(DocumentDelivery)
class DocumentDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "project_form",
        "purpose",
        "recipient_email",
        "provider",
        "status",
        "created_at",
        "sent_at",
    )
    list_filter = ("provider", "purpose", "status")
    search_fields = ("document__number", "project_form__title", "recipient_email")
    readonly_fields = (
        "document",
        "project_form",
        "purpose",
        "recipient_name",
        "recipient_email",
        "status",
        "provider_message_id",
        "provider",
        "error_code",
        "created_at",
        "sent_at",
        "last_event_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EmailWebhookEvent)
class EmailWebhookEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_type",
        "provider_message_id",
        "delivery",
        "occurred_at",
        "received_at",
    )
    list_filter = ("provider", "event_type")
    search_fields = ("event_id", "provider_message_id", "delivery__recipient_email")
    readonly_fields = (
        "delivery",
        "provider",
        "event_id",
        "event_type",
        "provider_message_id",
        "occurred_at",
        "received_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
