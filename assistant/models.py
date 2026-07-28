import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.models import Company


class AICompanySettings(models.Model):
    class AccessMode(models.TextChoices):
        STAFF_ONLY = "staff_only", "Staff users only"
        SELECTED_USERS = "selected_users", "Selected users"
        ALL_USERS = "all_users", "All company users"

    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="ai_settings",
    )
    enabled = models.BooleanField(default=False)
    access_mode = models.CharField(
        max_length=30,
        choices=AccessMode.choices,
        default=AccessMode.ALL_USERS,
    )
    model_override = models.CharField(max_length=100, blank=True)
    allow_low_risk_writes = models.BooleanField(default=True)
    allow_structured_writes = models.BooleanField(default=True)
    allow_financial_drafts = models.BooleanField(default=True)
    allow_external_commits = models.BooleanField(default=False)
    proactive_insights_enabled = models.BooleanField(default=True)
    monthly_cost_limit_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("25.00"),
        validators=[
            MinValueValidator(Decimal("0.01")),
            MaxValueValidator(Decimal("100000.00")),
        ],
    )
    monthly_request_limit = models.PositiveIntegerField(
        default=500,
        validators=[MinValueValidator(1), MaxValueValidator(1000000)],
    )
    interaction_retention_days = models.PositiveSmallIntegerField(
        default=90,
        validators=[MinValueValidator(7), MaxValueValidator(2555)],
    )
    retain_interaction_summaries = models.BooleanField(default=True)
    auto_pause_on_failures = models.BooleanField(default=True)
    failure_threshold = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(2), MaxValueValidator(100)],
    )
    failure_window_minutes = models.PositiveSmallIntegerField(
        default=60,
        validators=[MinValueValidator(5), MaxValueValidator(1440)],
    )
    suspended_at = models.DateTimeField(blank=True, null=True)
    suspension_reason = models.CharField(max_length=255, blank=True)
    failure_count_reset_at = models.DateTimeField(blank=True, null=True)
    privacy_notice_version = models.CharField(max_length=40, blank=True)
    privacy_notice_acknowledged_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI company setting"
        verbose_name_plural = "AI company settings"

    def __str__(self):
        return f"{self.company} AI settings"

    @property
    def is_suspended(self):
        return self.suspended_at is not None


class AIUserAccess(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="ai_user_access_records",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_access",
    )
    enabled = models.BooleanField(default=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="granted_ai_access_records",
        blank=True,
        null=True,
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("user__email",)
        constraints = [
            models.UniqueConstraint(
                fields=("company", "user"),
                name="ai_user_access_user_uniq",
            )
        ]

    def clean(self):
        super().clean()
        if self.user_id and self.company_id and self.user.company_id != self.company_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("AI user access must belong to the user's company.")

    def __str__(self):
        return f"{self.user} AI access"


class AIInteraction(models.Model):
    class Status(models.TextChoices):
        STARTED = "started", "Started"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        BLOCKED = "blocked", "Blocked"

    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="ai_interactions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ai_interactions",
    )
    provider = models.CharField(max_length=50)
    model = models.CharField(max_length=100)
    prompt_summary = models.CharField(max_length=500)
    response_summary = models.CharField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.STARTED,
    )
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        default=0,
    )
    latency_ms = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=100, blank=True)
    provider_request_ids = models.JSONField(default=list, blank=True)
    provider_client_request_ids = models.JSONField(default=list, blank=True)
    conversation_id = models.UUIDField(blank=True, null=True, db_index=True)
    context_turn_count = models.PositiveSmallIntegerField(default=0)
    page_context_type = models.CharField(max_length=30, blank=True)
    page_context_object_id = models.PositiveBigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("company", "created_at"), name="ai_inter_company_created"),
            models.Index(fields=("user", "created_at"), name="ai_inter_user_created"),
            models.Index(
                fields=("company", "user", "conversation_id", "created_at"),
                name="ai_inter_conversation",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.created_at:%Y-%m-%d %H:%M}"


class AIActionAttempt(models.Model):
    class RiskLevel(models.TextChoices):
        LOW_WRITE = "low_write", "Low-risk write"
        STRUCTURED_WRITE = "structured_write", "Structured write"
        FINANCIAL_DRAFT = "financial_draft", "Financial draft"
        EXTERNAL_COMMIT = "external_commit", "External or financial commit"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending confirmation"
        CONFIRMED = "confirmed", "Confirmed"
        COMPLETED = "completed", "Completed"
        CANCELED = "canceled", "Canceled"
        EXPIRED = "expired", "Expired"
        FAILED = "failed", "Failed"

    interaction = models.ForeignKey(
        AIInteraction,
        on_delete=models.PROTECT,
        related_name="action_attempts",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="ai_action_attempts",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ai_action_attempts",
    )
    tool_name = models.CharField(max_length=100)
    risk_level = models.CharField(max_length=30, choices=RiskLevel.choices)
    normalized_arguments = models.JSONField(default=dict)
    preview = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    confirmation_token = models.UUIDField(default=uuid.uuid4, unique=True)
    confirmation_expires_at = models.DateTimeField()
    idempotency_key = models.CharField(max_length=64, unique=True)
    confirmed_at = models.DateTimeField(blank=True, null=True)
    executed_at = models.DateTimeField(blank=True, null=True)
    result = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("company", "status", "created_at"), name="ai_action_company_status"),
            models.Index(fields=("user", "status", "created_at"), name="ai_action_user_status"),
        ]

    def __str__(self):
        return f"{self.tool_name}: {self.status}"


class AIEvent(models.Model):
    class Type(models.TextChoices):
        AMBIGUITY = "ambiguity", "Ambiguity"
        CORRECTION_REQUESTED = "correction_requested", "Correction requested"
        ACTION_CANCELED = "action_canceled", "Action canceled"
        TOOL_FAILURE = "tool_failure", "Tool failure"
        SUGGESTION_USED = "suggestion_used", "Suggestion used"
        INSIGHT_DISMISSED = "insight_dismissed", "Insight dismissed"
        FEEDBACK_RECORDED = "feedback_recorded", "Feedback recorded"
        CIRCUIT_BREAKER_TRIPPED = "circuit_breaker_tripped", "Circuit breaker tripped"
        CIRCUIT_BREAKER_RESET = "circuit_breaker_reset", "Circuit breaker reset"

    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="ai_events",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ai_events",
    )
    interaction = models.ForeignKey(
        AIInteraction,
        on_delete=models.SET_NULL,
        related_name="events",
        blank=True,
        null=True,
    )
    action_attempt = models.ForeignKey(
        AIActionAttempt,
        on_delete=models.SET_NULL,
        related_name="events",
        blank=True,
        null=True,
    )
    event_type = models.CharField(max_length=40, choices=Type.choices)
    capability = models.CharField(max_length=100, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("company", "event_type", "created_at"), name="ai_event_company_type"),
            models.Index(fields=("user", "created_at"), name="ai_event_user_created"),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()}: {self.capability or 'assistant'}"


class AIFeedback(models.Model):
    class Rating(models.TextChoices):
        HELPFUL = "helpful", "Helpful"
        NOT_HELPFUL = "not_helpful", "Not helpful"

    class Category(models.TextChoices):
        ANSWER = "answer", "Answer quality"
        RECORD_MATCH = "record_match", "Wrong or ambiguous record"
        ACTION = "action", "Prepared or completed action"
        SPEED = "speed", "Speed or availability"
        OTHER = "other", "Other"

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="ai_feedback",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_feedback",
    )
    interaction = models.ForeignKey(
        AIInteraction,
        on_delete=models.CASCADE,
        related_name="feedback",
    )
    rating = models.CharField(max_length=20, choices=Rating.choices)
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.ANSWER,
    )
    comment = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("interaction", "user"),
                name="ai_feedback_user_uniq",
            )
        ]
        indexes = [
            models.Index(fields=("company", "rating", "created_at"), name="ai_feedback_company_rating")
        ]

    def clean(self):
        super().clean()
        if self.interaction_id and self.company_id:
            if self.interaction.company_id != self.company_id:
                from django.core.exceptions import ValidationError

                raise ValidationError("AI feedback must match the interaction company.")
        if self.interaction_id and self.user_id:
            if self.interaction.user_id != self.user_id:
                from django.core.exceptions import ValidationError

                raise ValidationError("AI feedback must be submitted by the interaction user.")

    def __str__(self):
        return f"{self.get_rating_display()}: {self.interaction_id}"


class AIIncident(models.Model):
    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Category(models.TextChoices):
        WRONG_ANSWER = "wrong_answer", "Wrong answer"
        WRONG_RECORD = "wrong_record", "Wrong record"
        DUPLICATE_ACTION = "duplicate_action", "Duplicate action"
        UNSAFE_ACTION = "unsafe_action", "Unsafe or unexpected action"
        PRIVACY = "privacy", "Privacy concern"
        PROVIDER = "provider", "OpenAI/provider failure"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="ai_incidents",
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reported_ai_incidents",
    )
    interaction = models.ForeignKey(
        AIInteraction,
        on_delete=models.SET_NULL,
        related_name="incidents",
        blank=True,
        null=True,
    )
    action_attempt = models.ForeignKey(
        AIActionAttempt,
        on_delete=models.SET_NULL,
        related_name="incidents",
        blank=True,
        null=True,
    )
    severity = models.CharField(max_length=20, choices=Severity.choices)
    category = models.CharField(max_length=30, choices=Category.choices)
    summary = models.CharField(max_length=500)
    details = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="resolved_ai_incidents",
        blank=True,
        null=True,
    )
    resolved_at = models.DateTimeField(blank=True, null=True)
    resolution_note = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("company", "status", "severity"), name="ai_incident_company_status")
        ]

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError

        if self.reported_by_id and self.company_id and self.reported_by.company_id != self.company_id:
            raise ValidationError("The incident reporter must belong to the company.")
        if self.interaction_id and self.interaction.company_id != self.company_id:
            raise ValidationError("The incident interaction must belong to the company.")
        if self.action_attempt_id and self.action_attempt.company_id != self.company_id:
            raise ValidationError("The incident action must belong to the company.")

    def __str__(self):
        return f"{self.get_severity_display()}: {self.summary}"


class AIInsightDismissal(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="ai_insight_dismissals",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_insight_dismissals",
    )
    insight_key = models.CharField(max_length=255)
    dismissed_until = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("company", "user", "insight_key"),
                name="ai_insight_dismissal_unique",
            )
        ]
        indexes = [
            models.Index(fields=("company", "user", "dismissed_until"), name="ai_insight_dismissed_until")
        ]

    def __str__(self):
        return f"{self.user}: {self.insight_key}"


class AIDocumentDraftReview(models.Model):
    """Metadata-only quality record for an AI-created or AI-revised draft.

    Free-text proposal, invoice, note, and line-item content is represented only by
    hashes in the snapshots. The record exists to measure revision and adoption,
    not to retain another copy of customer-facing content.
    """

    class Outcome(models.TextChoices):
        ACTIVE = "active", "Still a draft"
        USED_AS_IS = "used_as_is", "Issued without revision"
        EDITED_THEN_USED = "edited_then_used", "Revised before issue"
        ABANDONED = "abandoned", "Deleted while draft"

    action_attempt = models.OneToOneField(
        AIActionAttempt,
        on_delete=models.PROTECT,
        related_name="document_draft_review",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="ai_document_draft_reviews",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ai_document_draft_reviews",
    )
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.SET_NULL,
        related_name="ai_draft_reviews",
        blank=True,
        null=True,
    )
    document_type = models.CharField(max_length=20)
    document_number = models.CharField(max_length=30)
    initial_snapshot = models.JSONField(default=dict)
    latest_snapshot = models.JSONField(default=dict)
    initial_snapshot_hash = models.CharField(max_length=64)
    latest_snapshot_hash = models.CharField(max_length=64)
    changed_fields = models.JSONField(default=list, blank=True)
    revision_count = models.PositiveIntegerField(default=0)
    outcome = models.CharField(
        max_length=30,
        choices=Outcome.choices,
        default=Outcome.ACTIVE,
    )
    first_revised_at = models.DateTimeField(blank=True, null=True)
    last_revised_at = models.DateTimeField(blank=True, null=True)
    issued_at = models.DateTimeField(blank=True, null=True)
    first_delivery_at = models.DateTimeField(blank=True, null=True)
    deleted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(
                fields=("company", "outcome", "created_at"),
                name="ai_draft_company_outcome",
            ),
            models.Index(
                fields=("company", "document_type", "created_at"),
                name="ai_draft_company_type",
            ),
        ]

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError

        if self.action_attempt_id:
            if self.action_attempt.company_id != self.company_id:
                raise ValidationError("AI draft review must match the action company.")
            if self.action_attempt.user_id != self.user_id:
                raise ValidationError("AI draft review must match the action user.")
        if self.document_id and self.document.company_id != self.company_id:
            raise ValidationError("AI draft review document must belong to the same company.")

    def __str__(self):
        return f"{self.document_type} {self.document_number}: {self.outcome}"


class AIEvaluationRun(models.Model):
    class Mode(models.TextChoices):
        CONTRACT = "contract", "Contract"
        LIVE = "live", "Live OpenAI"

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        ERROR = "error", "Error"

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="ai_evaluation_runs",
        blank=True,
        null=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="ai_evaluation_runs",
        blank=True,
        null=True,
    )
    mode = models.CharField(max_length=20, choices=Mode.choices)
    suite = models.CharField(max_length=40)
    model = models.CharField(max_length=100, blank=True)
    configuration_fingerprint = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    total_cases = models.PositiveIntegerField(default=0)
    passed_cases = models.PositiveIntegerField(default=0)
    failed_cases = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        default=0,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-started_at", "-pk")
        indexes = [
            models.Index(
                fields=("company", "started_at"),
                name="ai_eval_company_started",
            )
        ]

    def __str__(self):
        return f"{self.get_mode_display()} {self.suite}: {self.status}"


class AIEvaluationCaseResult(models.Model):
    class Status(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        ERROR = "error", "Error"
        SKIPPED = "skipped", "Skipped"

    run = models.ForeignKey(
        AIEvaluationRun,
        on_delete=models.CASCADE,
        related_name="case_results",
    )
    case_id = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=Status.choices)
    expected_tools = models.JSONField(default=list, blank=True)
    forbidden_risk_levels = models.JSONField(default=list, blank=True)
    actual_tools = models.JSONField(default=list, blank=True)
    pending_action_count = models.PositiveIntegerField(default=0)
    response_summary = models.CharField(max_length=1000, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    total_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        default=0,
    )
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("run", "case_id")
        constraints = [
            models.UniqueConstraint(
                fields=("run", "case_id"),
                name="ai_eval_case_unique",
            )
        ]

    def __str__(self):
        return f"{self.case_id}: {self.status}"
