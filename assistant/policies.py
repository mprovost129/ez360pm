from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum
from django.utils import timezone

from .models import AIActionAttempt, AICompanySettings, AIInteraction, AIUserAccess

PRIVACY_NOTICE_VERSION = "2026-07-27"


class AIPolicyError(ValidationError):
    """Raised when a company-level AI policy blocks a request or action."""


def _optional_setting(name, fallback):
    value = getattr(settings, name, None)
    return fallback if value is None else value


def default_policy_values():
    enabled = bool(
        _optional_setting(
            "AI_COMPANY_DEFAULT_ENABLED",
            getattr(settings, "AI_ASSISTANT_ENABLED", False),
        )
    )
    privacy_acknowledged = bool(
        _optional_setting(
            "AI_COMPANY_DEFAULT_PRIVACY_ACKNOWLEDGED",
            enabled,
        )
    )
    external_commits = bool(
        _optional_setting(
            "AI_COMPANY_DEFAULT_EXTERNAL_COMMITS",
            enabled,
        )
    )
    return {
        "enabled": enabled,
        "access_mode": getattr(
            settings,
            "AI_COMPANY_DEFAULT_ACCESS_MODE",
            AICompanySettings.AccessMode.ALL_USERS,
        ),
        "allow_low_risk_writes": True,
        "allow_structured_writes": True,
        "allow_financial_drafts": True,
        "allow_external_commits": external_commits,
        "proactive_insights_enabled": True,
        "monthly_cost_limit_usd": Decimal(str(settings.AI_MONTHLY_COST_LIMIT_USD)),
        "monthly_request_limit": int(
            getattr(settings, "AI_COMPANY_DEFAULT_MONTHLY_REQUEST_LIMIT", 500)
        ),
        "interaction_retention_days": int(
            getattr(settings, "AI_COMPANY_DEFAULT_RETENTION_DAYS", 90)
        ),
        "retain_interaction_summaries": True,
        "auto_pause_on_failures": True,
        "failure_threshold": int(
            getattr(settings, "AI_COMPANY_DEFAULT_FAILURE_THRESHOLD", 5)
        ),
        "failure_window_minutes": int(
            getattr(settings, "AI_COMPANY_DEFAULT_FAILURE_WINDOW_MINUTES", 60)
        ),
        "privacy_notice_version": (
            PRIVACY_NOTICE_VERSION if privacy_acknowledged else ""
        ),
        "privacy_notice_acknowledged_at": (
            timezone.now() if privacy_acknowledged else None
        ),
    }


def default_policy_for_company(company):
    """Return an unsaved policy using the deployment defaults.

    This is intended for read-only UI decisions such as whether to render the
    assistant drawer. It avoids creating an ``AICompanySettings`` row merely
    because an ordinary authenticated page was displayed.
    """

    return AICompanySettings(company=company, **default_policy_values())


def get_company_policy(company, *, create=True):
    if hasattr(company, "ai_settings"):
        try:
            return company.ai_settings
        except AICompanySettings.DoesNotExist:
            pass
    if not create:
        return None
    policy, _created = AICompanySettings.objects.get_or_create(
        company=company,
        defaults=default_policy_values(),
    )
    return policy


def allowed_models():
    configured = list(getattr(settings, "AI_ALLOWED_MODELS", []))
    default_model = str(getattr(settings, "AI_MODEL", "")).strip()
    if default_model and default_model not in configured:
        configured.insert(0, default_model)
    return [model for model in configured if model]


def effective_model(policy):
    selected = (policy.model_override or settings.AI_MODEL).strip()
    choices = allowed_models()
    if choices and selected not in choices:
        raise AIPolicyError(
            "The selected AI model is not in the platform allowlist. Update AI settings before continuing."
        )
    return selected


def user_has_ai_access(policy, user):
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if user.company_id != policy.company_id or not user.is_active:
        return False
    if policy.access_mode == AICompanySettings.AccessMode.ALL_USERS:
        return True
    if policy.access_mode == AICompanySettings.AccessMode.STAFF_ONLY:
        return bool(user.is_staff)
    if policy.access_mode == AICompanySettings.AccessMode.SELECTED_USERS:
        return AIUserAccess.objects.filter(
            company=policy.company,
            user=user,
            enabled=True,
        ).exists()
    return False


def assistant_available(policy, user=None):
    company_available = bool(
        getattr(settings, "AI_ASSISTANT_ENABLED", False)
        and policy.enabled
        and policy.privacy_notice_acknowledged_at
        and not policy.suspended_at
    )
    if user is None:
        return company_available
    return company_available and user_has_ai_access(policy, user)


def require_assistant_available(policy, user=None):
    if not getattr(settings, "AI_ASSISTANT_ENABLED", False):
        raise AIPolicyError("The AI assistant is disabled at the application level.")
    if not policy.enabled:
        raise AIPolicyError("The AI assistant is disabled for this company.")
    if policy.suspended_at:
        reason = policy.suspension_reason or "The company AI circuit breaker is active."
        raise AIPolicyError(
            f"The AI assistant is temporarily suspended for this company. {reason}"
        )
    if not policy.privacy_notice_acknowledged_at:
        raise AIPolicyError(
            "Review and acknowledge the AI data-processing notice in AI settings before using the assistant."
        )
    if user is not None and not user_has_ai_access(policy, user):
        raise AIPolicyError("Your account is not included in this company's AI pilot access.")


def risk_allowed(policy, risk_level):
    if risk_level == "read":
        return True
    return {
        "low_write": policy.allow_low_risk_writes,
        "structured_write": policy.allow_structured_writes,
        "financial_draft": policy.allow_financial_drafts,
        "external_commit": policy.allow_external_commits,
    }.get(risk_level, False)


def require_risk_allowed(policy, risk_level, user=None):
    require_assistant_available(policy, user=user)
    if not risk_allowed(policy, risk_level):
        labels = {
            "low_write": "notes and timer actions",
            "structured_write": "client and project changes",
            "financial_draft": "proposal and invoice drafts",
            "external_commit": "sending and financial lifecycle actions",
        }
        raise AIPolicyError(
            f"AI {labels.get(risk_level, 'actions')} are disabled for this company."
        )


def allowed_risk_levels(policy):
    levels = {"read"}
    for risk_level in (
        "low_write",
        "structured_write",
        "financial_draft",
        "external_commit",
    ):
        if risk_allowed(policy, risk_level):
            levels.add(risk_level)
    return levels


def current_month_usage(company):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    interactions = AIInteraction.objects.filter(
        company=company,
        created_at__date__gte=month_start,
    ).exclude(provider="local")
    totals = interactions.aggregate(
        requests=Count("id"),
        cost=Sum("estimated_cost_usd"),
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
    )
    return {
        "month_start": month_start,
        "requests": totals["requests"] or 0,
        "cost": totals["cost"] or Decimal("0"),
        "input_tokens": totals["input_tokens"] or 0,
        "output_tokens": totals["output_tokens"] or 0,
    }


def effective_cost_limit(policy):
    platform_limit = Decimal(str(settings.AI_MONTHLY_COST_LIMIT_USD))
    company_limit = Decimal(str(policy.monthly_cost_limit_usd))
    return min(platform_limit, company_limit)


def require_usage_available(policy, user=None):
    require_assistant_available(policy, user=user)
    usage = current_month_usage(policy.company)
    if usage["requests"] >= policy.monthly_request_limit:
        raise AIPolicyError(
            "The company monthly AI request allowance has been reached. Ordinary EZ360PM workflows remain available."
        )
    limit = effective_cost_limit(policy)
    if usage["cost"] >= limit:
        raise AIPolicyError(
            "The company monthly AI cost guard has been reached. Ordinary EZ360PM workflows remain available."
        )
    return usage


def suspend_company_ai(policy, *, reason):
    if policy.suspended_at:
        return False
    now = timezone.now()
    policy.suspended_at = now
    policy.suspension_reason = str(reason).strip()[:255]
    policy.save(update_fields=["suspended_at", "suspension_reason", "updated_at"])
    AIActionAttempt.objects.filter(
        company=policy.company,
        status=AIActionAttempt.Status.PENDING,
    ).update(
        status=AIActionAttempt.Status.CANCELED,
        error_code="company_ai_suspended",
        result={
            "message": "The prepared action was canceled because company AI was suspended. Prepare it again after review."
        },
    )
    return True


def resume_company_ai(policy):
    if not policy.suspended_at:
        return False
    now = timezone.now()
    policy.suspended_at = None
    policy.suspension_reason = ""
    policy.failure_count_reset_at = now
    policy.save(
        update_fields=[
            "suspended_at",
            "suspension_reason",
            "failure_count_reset_at",
            "updated_at",
        ]
    )
    return True


def evaluate_failure_circuit_breaker(policy, *, interaction=None):
    """Suspend company AI after a bounded cluster of failed interactions."""
    if not policy.auto_pause_on_failures or policy.suspended_at:
        return False
    window_start = timezone.now() - timedelta(minutes=policy.failure_window_minutes)
    if policy.failure_count_reset_at and policy.failure_count_reset_at > window_start:
        window_start = policy.failure_count_reset_at
    interaction_failures = (
        AIInteraction.objects.filter(
            company=policy.company,
            status=AIInteraction.Status.FAILED,
            created_at__gte=window_start,
        )
        # Preserve compatibility with V1.19 and earlier rows where ordinary
        # domain validation was recorded as failed instead of blocked.
        .exclude(error_code="domain_validation")
        .count()
    )
    action_failures = (
        AIActionAttempt.objects.filter(
            company=policy.company,
            status=AIActionAttempt.Status.FAILED,
            created_at__gte=window_start,
        )
        # Backward compatibility for pre-V1.24 rows where ordinary domain
        # validation was recorded as a failed action.
        .exclude(error_code="domain_validation")
        .count()
    )
    failures = interaction_failures + action_failures
    if failures < policy.failure_threshold:
        return False
    tripped = suspend_company_ai(
        policy,
        reason=(
            f"Automatic safety pause after {failures} failed AI requests or confirmed actions within "
            f"{policy.failure_window_minutes} minutes. Review AI Pilot Operations before resuming."
        ),
    )
    if tripped and interaction is not None:
        from .models import AIEvent

        AIEvent.objects.create(
            company=policy.company,
            user=interaction.user,
            interaction=interaction,
            event_type=AIEvent.Type.CIRCUIT_BREAKER_TRIPPED,
            capability="pilot_safety",
            metadata={
                "failure_count": failures,
                "interaction_failures": interaction_failures,
                "action_failures": action_failures,
                "window_minutes": policy.failure_window_minutes,
            },
        )
    return tripped
