from django.contrib import admin

from .models import (
    AIActionAttempt,
    AICompanySettings,
    AIDocumentDraftReview,
    AIEvaluationCaseResult,
    AIEvaluationRun,
    AIEvent,
    AIFeedback,
    AIIncident,
    AIInsightDismissal,
    AIInteraction,
    AIUserAccess,
)


@admin.register(AICompanySettings)
class AICompanySettingsAdmin(admin.ModelAdmin):
    list_display = (
        "company",
        "enabled",
        "access_mode",
        "model_override",
        "monthly_request_limit",
        "monthly_cost_limit_usd",
        "allow_external_commits",
        "suspended_at",
        "updated_at",
    )
    list_filter = (
        "enabled",
        "allow_low_risk_writes",
        "allow_structured_writes",
        "allow_financial_drafts",
        "allow_external_commits",
        "access_mode",
        "auto_pause_on_failures",
    )
    search_fields = ("company__name",)


@admin.register(AIUserAccess)
class AIUserAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "company", "enabled", "granted_by", "updated_at")
    list_filter = ("enabled", "company")
    search_fields = ("user__email", "company__name")


@admin.register(AIFeedback)
class AIFeedbackAdmin(admin.ModelAdmin):
    list_display = ("created_at", "company", "user", "rating", "category", "interaction")
    list_filter = ("rating", "category", "company")
    search_fields = ("user__email", "comment")
    readonly_fields = [field.name for field in AIFeedback._meta.fields]


@admin.register(AIIncident)
class AIIncidentAdmin(admin.ModelAdmin):
    list_display = ("created_at", "company", "severity", "category", "status", "reported_by")
    list_filter = ("severity", "category", "status", "company")
    search_fields = ("summary", "details", "reported_by__email")



@admin.register(AIDocumentDraftReview)
class AIDocumentDraftReviewAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "company",
        "document_type",
        "document_number",
        "outcome",
        "revision_count",
        "issued_at",
        "first_delivery_at",
    )
    list_filter = ("outcome", "document_type", "company")
    search_fields = ("document_number", "user__email", "company__name")
    readonly_fields = [field.name for field in AIDocumentDraftReview._meta.fields]


@admin.register(AIInteraction)
class AIInteractionAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "user",
        "provider",
        "model",
        "status",
        "conversation_id",
        "context_turn_count",
        "page_context_type",
        "total_tokens",
        "estimated_cost_usd",
    )
    list_filter = ("status", "provider", "model")
    search_fields = ("user__email", "prompt_summary", "response_summary")
    readonly_fields = [field.name for field in AIInteraction._meta.fields]


@admin.register(AIActionAttempt)
class AIActionAttemptAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "tool_name", "risk_level", "status")
    list_filter = ("risk_level", "status", "tool_name")
    search_fields = ("user__email", "tool_name", "idempotency_key")
    readonly_fields = [field.name for field in AIActionAttempt._meta.fields]


@admin.register(AIEvent)
class AIEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "event_type", "capability")
    list_filter = ("event_type", "capability")
    search_fields = ("user__email", "capability")
    readonly_fields = [field.name for field in AIEvent._meta.fields]


@admin.register(AIInsightDismissal)
class AIInsightDismissalAdmin(admin.ModelAdmin):
    list_display = ("user", "insight_key", "dismissed_until", "updated_at")
    search_fields = ("user__email", "insight_key")
    readonly_fields = [field.name for field in AIInsightDismissal._meta.fields]


@admin.register(AIEvaluationRun)
class AIEvaluationRunAdmin(admin.ModelAdmin):
    list_display = (
        "started_at",
        "company",
        "mode",
        "suite",
        "model",
        "status",
        "passed_cases",
        "failed_cases",
        "estimated_cost_usd",
    )
    list_filter = ("mode", "suite", "status", "model")
    search_fields = ("company__name", "user__email", "model")
    readonly_fields = [field.name for field in AIEvaluationRun._meta.fields]


@admin.register(AIEvaluationCaseResult)
class AIEvaluationCaseResultAdmin(admin.ModelAdmin):
    list_display = ("created_at", "run", "case_id", "category", "status")
    list_filter = ("category", "status")
    search_fields = ("case_id", "title", "run__company__name")
    readonly_fields = [field.name for field in AIEvaluationCaseResult._meta.fields]
