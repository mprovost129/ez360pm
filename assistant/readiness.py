from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .checks import model_looks_snapshot_pinned
from .evaluations import evaluation_fingerprint
from .models import (
    AIActionAttempt,
    AIDocumentDraftReview,
    AIEvaluationRun,
    AIFeedback,
    AIIncident,
    AIInteraction,
)
from .policies import (
    current_month_usage,
    effective_cost_limit,
    effective_model,
    get_company_policy,
    user_has_ai_access,
)


@dataclass(frozen=True)
class ReadinessCheck:
    key: str
    title: str
    status: str
    detail: str
    action_url: str = ""
    action_label: str = ""

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    model: str
    generated_at: object
    checks: tuple
    requests_used: int
    request_limit: int
    cost_used: Decimal
    cost_limit: Decimal

    @property
    def failed_count(self):
        return sum(1 for item in self.checks if item.status == "fail")

    @property
    def warning_count(self):
        return sum(1 for item in self.checks if item.status == "warn")

    def as_dict(self):
        return {
            "ready": self.ready,
            "model": self.model,
            "generated_at": self.generated_at.isoformat(),
            "failed_count": self.failed_count,
            "warning_count": self.warning_count,
            "requests_used": self.requests_used,
            "request_limit": self.request_limit,
            "cost_used": str(self.cost_used),
            "cost_limit": str(self.cost_limit),
            "checks": [item.as_dict() for item in self.checks],
        }


def _freshness_status(run, *, maximum_age_days):
    if run is None:
        return "fail", "No passing result has been recorded."
    completed = run.completed_at or run.started_at
    age = timezone.now() - completed
    if run.status != AIEvaluationRun.Status.PASSED:
        return "fail", f"The latest run ended as {run.get_status_display().lower()}."
    if age > timedelta(days=maximum_age_days):
        return (
            "warn",
            f"The latest passing run is {age.days} days old; run it again before changing the model, prompt, SDK, or tools.",
        )
    local_completed = timezone.localtime(completed)
    display = local_completed.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
    return "pass", f"Passed {display}."


def _safe_date_detail(run, *, maximum_age_days, expected_fingerprint=""):
    """Windows-compatible fallback around platform-specific strftime flags."""
    status, detail = _freshness_status(run, maximum_age_days=maximum_age_days)
    if run and expected_fingerprint and run.configuration_fingerprint != expected_fingerprint:
        return "fail", "The latest result was produced by a different model/tool/provider configuration. Run it again for this release."
    if run and status == "pass":
        completed = timezone.localtime(run.completed_at or run.started_at)
        detail = f"Passed {completed.strftime('%b %d, %Y %I:%M %p').replace(' 0', ' ')}."
    return status, detail


def build_readiness_report(user):
    company = user.company
    policy = get_company_policy(company)
    checks = []
    maximum_age_days = int(getattr(settings, "AI_READINESS_MAX_EVALUATION_AGE_DAYS", 30))

    checks.append(
        ReadinessCheck(
            key="platform-feature-flag",
            title="Application AI feature flag",
            status="pass" if settings.AI_ASSISTANT_ENABLED else "fail",
            detail=(
                "AI_ASSISTANT_ENABLED is on."
                if settings.AI_ASSISTANT_ENABLED
                else "AI_ASSISTANT_ENABLED is off; ordinary EZ360PM remains available."
            ),
            action_url=reverse("assistant:settings"),
            action_label="Review AI settings",
        )
    )
    checks.append(
        ReadinessCheck(
            key="pilot-user-access",
            title="Pilot user access",
            status="pass" if user_has_ai_access(policy, user) else "fail",
            detail=(
                f"{user.email} is allowed under the {policy.get_access_mode_display().lower()} access mode."
                if user_has_ai_access(policy, user)
                else f"{user.email} is not included in the current pilot access mode."
            ),
            action_url=reverse("assistant:pilot-operations"),
            action_label="Review pilot access",
        )
    )
    checks.append(
        ReadinessCheck(
            key="circuit-breaker",
            title="AI circuit breaker",
            status="fail" if policy.suspended_at else "pass",
            detail=(
                f"AI is suspended: {policy.suspension_reason}"
                if policy.suspended_at
                else "The company AI circuit breaker is clear."
            ),
            action_url=reverse("assistant:pilot-operations"),
            action_label="Open pilot operations",
        )
    )
    checks.append(
        ReadinessCheck(
            key="openai-api-key",
            title="OpenAI API configuration",
            status="pass" if bool(settings.OPENAI_API_KEY) else "fail",
            detail=(
                "An OpenAI API key is configured in the deployment environment."
                if settings.OPENAI_API_KEY
                else "OPENAI_API_KEY is missing. Add it to the deployment environment; never store it in the database."
            ),
        )
    )

    open_incidents = AIIncident.objects.filter(
        company=company,
        status=AIIncident.Status.OPEN,
    )
    open_incident_count = open_incidents.count()
    open_high_incidents = open_incidents.filter(
        severity__in=(AIIncident.Severity.HIGH, AIIncident.Severity.CRITICAL),
    ).count()
    incident_status = (
        "fail" if open_high_incidents else ("warn" if open_incident_count else "pass")
    )
    if open_high_incidents:
        incident_detail = f"{open_high_incidents} high or critical incident(s) require review before controlled use."
    elif open_incident_count:
        incident_detail = f"{open_incident_count} lower-severity incident(s) remain open for pilot review."
    else:
        incident_detail = "No open AI incidents."
    checks.append(
        ReadinessCheck(
            key="open-ai-incidents",
            title="Open AI incidents",
            status=incident_status,
            detail=incident_detail,
            action_url=reverse("assistant:pilot-operations"),
            action_label="Review incidents",
        )
    )

    recent_feedback = AIFeedback.objects.filter(
        company=company,
        created_at__gte=timezone.now() - timedelta(days=30),
    )
    feedback_total = recent_feedback.count()
    negative_feedback = recent_feedback.filter(
        rating=AIFeedback.Rating.NOT_HELPFUL
    ).count()
    if feedback_total < 5:
        feedback_status = "warn"
        feedback_detail = (
            f"Only {feedback_total} feedback rating(s) have been collected in the last 30 days; continue the controlled pilot."
        )
    elif negative_feedback / feedback_total > 0.25:
        feedback_status = "warn"
        feedback_detail = (
            f"{negative_feedback} of {feedback_total} recent ratings were not helpful; review pilot feedback before wider rollout."
        )
    else:
        feedback_status = "pass"
        feedback_detail = (
            f"{feedback_total - negative_feedback} of {feedback_total} recent ratings were helpful."
        )
    checks.append(
        ReadinessCheck(
            key="pilot-feedback",
            title="Controlled-use feedback",
            status=feedback_status,
            detail=feedback_detail,
            action_url=reverse("assistant:pilot-operations"),
            action_label="Review feedback",
        )
    )
    checks.append(
        ReadinessCheck(
            key="company-policy",
            title="Company enablement and privacy acknowledgement",
            status=(
                "pass"
                if policy.enabled and policy.privacy_notice_acknowledged_at
                else "fail"
            ),
            detail=(
                "The company has enabled AI and acknowledged the current data-processing notice."
                if policy.enabled and policy.privacy_notice_acknowledged_at
                else "Enable AI and acknowledge the data-processing notice for this company."
            ),
            action_url=reverse("assistant:settings"),
            action_label="Open AI settings",
        )
    )

    try:
        selected_model = effective_model(policy)
        model_status = "pass"
        model_detail = f"{selected_model} is included in the deployment allowlist."
    except Exception as exc:
        selected_model = policy.model_override or settings.AI_MODEL
        model_status = "fail"
        model_detail = str(exc)
    checks.append(
        ReadinessCheck(
            key="model-allowlist",
            title="OpenAI model selection",
            status=model_status,
            detail=model_detail,
            action_url=reverse("assistant:settings"),
            action_label="Review model",
        )
    )

    model_pinned = model_looks_snapshot_pinned(selected_model)
    checks.append(
        ReadinessCheck(
            key="model-stability",
            title="OpenAI model stability",
            status=(
                "pass"
                if model_pinned or not getattr(settings, "AI_WARN_ON_UNPINNED_MODEL", True)
                else "warn"
            ),
            detail=(
                f"{selected_model} is a dated model snapshot."
                if model_pinned
                else (
                    f"{selected_model} is a mutable model alias. Keep the fingerprinted live "
                    "evaluation current, or use a dated snapshot when consistent behavior is required."
                )
            ),
            action_url=reverse("assistant:evaluations"),
            action_label="Review evaluations",
        )
    )

    usage = current_month_usage(company)
    request_limit = int(policy.monthly_request_limit)
    cost_limit = effective_cost_limit(policy)
    request_ratio = Decimal(usage["requests"]) / Decimal(max(request_limit, 1))
    cost_ratio = usage["cost"] / cost_limit if cost_limit > 0 else Decimal("1")
    if usage["requests"] >= request_limit or usage["cost"] >= cost_limit:
        usage_status = "fail"
        usage_detail = "The monthly request or estimated-cost guard has been reached."
    elif request_ratio >= Decimal("0.80") or cost_ratio >= Decimal("0.80"):
        usage_status = "warn"
        usage_detail = "At least 80% of a monthly AI allowance has been used."
    else:
        usage_status = "pass"
        usage_detail = "Monthly request and estimated-cost allowances are available."
    checks.append(
        ReadinessCheck(
            key="usage-allowance",
            title="Monthly AI allowance",
            status=usage_status,
            detail=(
                f"{usage_detail} Requests: {usage['requests']}/{request_limit}; "
                f"estimated cost: ${usage['cost']:.6f}/${cost_limit:.2f}."
            ),
            action_url=reverse("assistant:usage"),
            action_label="View usage",
        )
    )

    contract_run = (
        AIEvaluationRun.objects.filter(
            company__isnull=True,
            mode=AIEvaluationRun.Mode.CONTRACT,
        )
        .order_by("-started_at", "-pk")
        .first()
    )
    status, detail = _safe_date_detail(
        contract_run,
        maximum_age_days=maximum_age_days,
        expected_fingerprint=evaluation_fingerprint(settings.AI_MODEL),
    )
    checks.append(
        ReadinessCheck(
            key="contract-evaluation",
            title="Static AI contract evaluation",
            status=status,
            detail=detail,
            action_url=reverse("assistant:evaluations"),
            action_label="View evaluations",
        )
    )

    connection_run = (
        AIEvaluationRun.objects.filter(
            company=company,
            mode=AIEvaluationRun.Mode.LIVE,
            suite="connection",
            model=selected_model,
        )
        .order_by("-started_at", "-pk")
        .first()
    )
    status, detail = _safe_date_detail(
        connection_run,
        maximum_age_days=maximum_age_days,
        expected_fingerprint=evaluation_fingerprint(selected_model),
    )
    checks.append(
        ReadinessCheck(
            key="openai-connection",
            title="OpenAI connection test",
            status=status,
            detail=detail,
            action_url=reverse("assistant:readiness"),
            action_label="Run connection test",
        )
    )

    live_run = (
        AIEvaluationRun.objects.filter(
            company=company,
            mode=AIEvaluationRun.Mode.LIVE,
            suite="all",
            model=selected_model,
        )
        .order_by("-started_at", "-pk")
        .first()
    )
    status, detail = _safe_date_detail(
        live_run,
        maximum_age_days=maximum_age_days,
        expected_fingerprint=evaluation_fingerprint(selected_model),
    )
    checks.append(
        ReadinessCheck(
            key="live-evaluation",
            title="Read-only live OpenAI baseline",
            status=status,
            detail=detail,
            action_url=reverse("assistant:evaluations"),
            action_label="View evaluation history",
        )
    )

    recent_since = timezone.now() - timedelta(hours=24)
    recent = AIInteraction.objects.filter(company=company, created_at__gte=recent_since)
    recent_total = recent.count()
    recent_failures = recent.filter(status=AIInteraction.Status.FAILED).count()
    if recent_total == 0:
        recent_status = "warn"
        recent_detail = "No assistant request has run in the last 24 hours; use the connection test and live baseline before launch."
    elif recent_failures == 0:
        recent_status = "pass"
        recent_detail = f"All {recent_total} assistant request(s) in the last 24 hours completed without a provider or tool failure."
    elif recent_failures / recent_total >= 0.20:
        recent_status = "warn"
        recent_detail = f"{recent_failures} of {recent_total} recent request(s) failed; review Usage & Reliability before wider use."
    else:
        recent_status = "warn"
        recent_detail = f"{recent_failures} recent request(s) failed; review the recorded error codes."
    checks.append(
        ReadinessCheck(
            key="recent-reliability",
            title="Recent assistant reliability",
            status=recent_status,
            detail=recent_detail,
            action_url=reverse("assistant:usage"),
            action_label="Review reliability",
        )
    )

    finalized_drafts = AIDocumentDraftReview.objects.filter(
        company=company,
        outcome__in=(
            AIDocumentDraftReview.Outcome.USED_AS_IS,
            AIDocumentDraftReview.Outcome.EDITED_THEN_USED,
            AIDocumentDraftReview.Outcome.ABANDONED,
        ),
        created_at__gte=timezone.now() - timedelta(days=90),
    )
    finalized_count = finalized_drafts.count()
    abandoned_count = finalized_drafts.filter(
        outcome=AIDocumentDraftReview.Outcome.ABANDONED
    ).count()
    if not policy.allow_financial_drafts:
        draft_status = "pass"
        draft_detail = "AI financial drafting is disabled for this company."
    elif finalized_count < 3:
        draft_status = "warn"
        draft_detail = (
            f"Only {finalized_count} finalized AI document draft outcome(s) have been recorded; "
            "continue the controlled pilot before considering scheduled drafting."
        )
    elif abandoned_count / finalized_count > 0.25:
        draft_status = "warn"
        draft_detail = (
            f"{abandoned_count} of {finalized_count} finalized AI drafts were abandoned; "
            "review draft quality before expanding automation."
        )
    else:
        draft_status = "pass"
        draft_detail = (
            f"{finalized_count} finalized AI draft outcomes are available for review, "
            f"including {abandoned_count} abandoned draft(s)."
        )
    checks.append(
        ReadinessCheck(
            key="document-draft-evidence",
            title="AI document draft evidence",
            status=draft_status,
            detail=draft_detail,
            action_url=reverse("assistant:draft-quality"),
            action_label="Review draft quality",
        )
    )

    expired_pending = AIActionAttempt.objects.filter(
        company=company,
        status=AIActionAttempt.Status.PENDING,
        confirmation_expires_at__lte=timezone.now(),
    ).count()
    checks.append(
        ReadinessCheck(
            key="expired-confirmations",
            title="Pending confirmation hygiene",
            status="warn" if expired_pending else "pass",
            detail=(
                f"{expired_pending} expired confirmation(s) remain pending and should be cleaned up."
                if expired_pending
                else "No expired confirmations remain pending."
            ),
        )
    )

    checks_tuple = tuple(checks)
    return ReadinessReport(
        ready=not any(item.status == "fail" for item in checks_tuple),
        model=selected_model,
        generated_at=timezone.now(),
        checks=checks_tuple,
        requests_used=usage["requests"],
        request_limit=request_limit,
        cost_used=usage["cost"],
        cost_limit=cost_limit,
    )
