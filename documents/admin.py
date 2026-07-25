from django.contrib import admin

from .models import (
    Document,
    DocumentDelivery,
    DocumentNumberSequence,
    Payment,
    PaymentAdjustment,
    PaymentFeeReconciliationAttempt,
)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("number", "doc_type", "invoice_kind", "project", "status", "total")
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
        "purpose",
        "recipient_email",
        "status",
        "created_at",
        "sent_at",
    )
    list_filter = ("purpose", "status")
    search_fields = ("document__number", "recipient_email")
    readonly_fields = (
        "document",
        "purpose",
        "recipient_name",
        "recipient_email",
        "status",
        "provider_message_id",
        "error_code",
        "created_at",
        "sent_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "received_at",
        "method",
        "amount",
        "fee_amount",
        "fee_current_amount",
        "fee_pending",
    )
    list_filter = ("method", "fee_pending", "received_at")
    search_fields = (
        "document__number",
        "document__project__name",
        "reference",
        "stripe_payment_intent_id",
    )
    readonly_fields = (
        "document",
        "amount",
        "fee_amount",
        "fee_current_amount",
        "fee_pending",
        "method",
        "received_at",
        "reference",
        "stripe_payment_intent_id",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentAdjustment)
class PaymentAdjustmentAdmin(admin.ModelAdmin):
    list_display = (
        "payment",
        "adjustment_type",
        "amount",
        "effective_at",
        "affects_invoice_balance",
        "affects_processing_fees",
        "provider_id",
    )
    list_filter = ("company", "adjustment_type", "effective_at")
    search_fields = (
        "payment__document__number",
        "provider_id",
        "reference",
    )
    readonly_fields = (
        "company",
        "payment",
        "adjustment_type",
        "amount",
        "effective_at",
        "affects_invoice_balance",
        "affects_processing_fees",
        "provider_id",
        "reference",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentFeeReconciliationAttempt)
class PaymentFeeReconciliationAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "payment",
        "status",
        "observed_fee",
        "error_code",
        "attempted_at",
    )
    list_filter = ("company", "status", "attempted_at")
    search_fields = (
        "payment__document__number",
        "payment__stripe_payment_intent_id",
        "error_code",
    )
    readonly_fields = (
        "company",
        "payment",
        "status",
        "observed_fee",
        "error_code",
        "error_message",
        "attempted_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
