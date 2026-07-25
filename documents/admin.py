from django.contrib import admin
from django.utils import timezone

from .models import (
    Document,
    DocumentDelivery,
    DocumentNumberSequence,
    Payment,
    PaymentAdjustment,
    PaymentFeeReconciliationAttempt,
    StripeWebhookFailure,
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


@admin.register(StripeWebhookFailure)
class StripeWebhookFailureAdmin(admin.ModelAdmin):
    list_display = (
        "event_type",
        "event_id",
        "company",
        "error_code",
        "attempt_count",
        "status",
        "last_failed_at",
        "resolved_at",
    )
    list_filter = ("status", "event_type", "company", "last_failed_at")
    search_fields = ("event_id", "object_id", "error_code")
    readonly_fields = (
        "company",
        "event_id",
        "event_type",
        "object_id",
        "error_code",
        "status",
        "attempt_count",
        "first_failed_at",
        "last_failed_at",
        "resolved_at",
        "resolved_by",
    )
    actions = ("mark_resolved", "reopen")

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("company", "resolved_by")
        if request.user.is_superuser:
            return queryset
        return queryset.filter(company=request.user.company)

    @admin.action(description="Mark selected failures as resolved", permissions=("change",))
    def mark_resolved(self, request, queryset):
        updated = queryset.filter(status=StripeWebhookFailure.Status.OPEN).update(
            status=StripeWebhookFailure.Status.RESOLVED,
            resolved_at=timezone.now(),
            resolved_by=request.user,
        )
        self.message_user(request, f"Marked {updated} Stripe webhook failure(s) resolved.")

    @admin.action(description="Reopen selected failures", permissions=("change",))
    def reopen(self, request, queryset):
        updated = queryset.filter(status=StripeWebhookFailure.Status.RESOLVED).update(
            status=StripeWebhookFailure.Status.OPEN,
            resolved_at=None,
            resolved_by=None,
        )
        self.message_user(request, f"Reopened {updated} Stripe webhook failure(s).")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
