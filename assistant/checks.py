import re

from django.conf import settings
from django.core.checks import Error, Info, Warning, register


def model_looks_snapshot_pinned(model):
    return bool(re.search(r"-\d{4}-\d{2}-\d{2}$", (model or "").strip()))


@register()
def assistant_settings_check(app_configs, **kwargs):
    del app_configs, kwargs
    messages = []

    if getattr(settings, "AI_PROACTIVE_MAX_ITEMS", 0) < 1:
        messages.append(
            Error("AI_PROACTIVE_MAX_ITEMS must be at least 1.", id="assistant.E003")
        )
    if getattr(settings, "AI_PROACTIVE_DISMISS_DAYS", 0) < 1:
        messages.append(
            Error("AI_PROACTIVE_DISMISS_DAYS must be at least 1.", id="assistant.E004")
        )
    if getattr(settings, "AI_PROACTIVE_REFRESH_SECONDS", 0) < 60:
        messages.append(
            Warning(
                "AI_PROACTIVE_REFRESH_SECONDS below 60 may create unnecessary database traffic.",
                id="assistant.W003",
            )
        )

    context_turns = getattr(settings, "AI_CONVERSATION_CONTEXT_TURNS", 0)
    if context_turns < 0 or context_turns > 12:
        messages.append(
            Error(
                "AI_CONVERSATION_CONTEXT_TURNS must be between 0 and 12.",
                id="assistant.E018",
            )
        )
    context_minutes = getattr(settings, "AI_CONVERSATION_CONTEXT_MINUTES", 0)
    if context_minutes < 1 or context_minutes > 1440:
        messages.append(
            Error(
                "AI_CONVERSATION_CONTEXT_MINUTES must be between 1 and 1440.",
                id="assistant.E019",
            )
        )

    follow_up_hours = getattr(settings, "AI_FOLLOW_UP_MIN_INTERVAL_HOURS", 0)
    if follow_up_hours < 1 or follow_up_hours > 720:
        messages.append(
            Error(
                "AI_FOLLOW_UP_MIN_INTERVAL_HOURS must be between 1 and 720.",
                id="assistant.E017",
            )
        )

    draft_stale_days = getattr(settings, "AI_DRAFT_STALE_DAYS", 0)
    if draft_stale_days < 1 or draft_stale_days > 365:
        messages.append(
            Error(
                "AI_DRAFT_STALE_DAYS must be between 1 and 365.",
                id="assistant.E016",
            )
        )

    readiness_age = getattr(settings, "AI_READINESS_MAX_EVALUATION_AGE_DAYS", 0)
    if readiness_age < 1 or readiness_age > 365:
        messages.append(
            Error(
                "AI_READINESS_MAX_EVALUATION_AGE_DAYS must be between 1 and 365.",
                id="assistant.E012",
            )
        )

    if not getattr(settings, "AI_ALLOWED_MODELS", []):
        messages.append(
            Error(
                "AI_ALLOWED_MODELS must contain at least one model.",
                id="assistant.E006",
            )
        )
    pricing = getattr(settings, "AI_MODEL_PRICING", {})
    if not isinstance(pricing, dict):
        messages.append(
            Error(
                "AI_MODEL_PRICING_JSON must decode to an object.", id="assistant.E009"
            )
        )
    else:
        for model, rates in pricing.items():
            if (
                not isinstance(rates, dict)
                or "input" not in rates
                or "output" not in rates
            ):
                messages.append(
                    Error(
                        f"AI model pricing for {model!r} must contain input and output rates.",
                        id="assistant.E010",
                    )
                )
                continue
            try:
                if float(rates["input"]) < 0 or float(rates["output"]) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                messages.append(
                    Error(
                        f"AI model pricing for {model!r} must use non-negative numbers.",
                        id="assistant.E011",
                    )
                )
    if getattr(settings, "AI_COMPANY_DEFAULT_MONTHLY_REQUEST_LIMIT", 0) < 1:
        messages.append(
            Error(
                "AI_COMPANY_DEFAULT_MONTHLY_REQUEST_LIMIT must be at least 1.",
                id="assistant.E007",
            )
        )
    access_mode = getattr(settings, "AI_COMPANY_DEFAULT_ACCESS_MODE", "")
    if access_mode not in {"all_users", "staff_only", "selected_users"}:
        messages.append(
            Error(
                "AI_COMPANY_DEFAULT_ACCESS_MODE must be all_users, staff_only, or selected_users.",
                id="assistant.E015",
            )
        )
    retention_days = getattr(settings, "AI_COMPANY_DEFAULT_RETENTION_DAYS", 0)
    if retention_days < 7 or retention_days > 2555:
        messages.append(
            Error(
                "AI_COMPANY_DEFAULT_RETENTION_DAYS must be between 7 and 2555.",
                id="assistant.E008",
            )
        )

    failure_threshold = getattr(settings, "AI_COMPANY_DEFAULT_FAILURE_THRESHOLD", 0)
    if failure_threshold < 2 or failure_threshold > 100:
        messages.append(
            Error(
                "AI_COMPANY_DEFAULT_FAILURE_THRESHOLD must be between 2 and 100.",
                id="assistant.E013",
            )
        )
    failure_window = getattr(settings, "AI_COMPANY_DEFAULT_FAILURE_WINDOW_MINUTES", 0)
    if failure_window < 5 or failure_window > 1440:
        messages.append(
            Error(
                "AI_COMPANY_DEFAULT_FAILURE_WINDOW_MINUTES must be between 5 and 1440.",
                id="assistant.E014",
            )
        )

    if not getattr(settings, "AI_ASSISTANT_ENABLED", False):
        return messages

    if getattr(settings, "AI_WARN_ON_UNPINNED_MODEL", True):
        unpinned = [
            model
            for model in getattr(settings, "AI_ALLOWED_MODELS", [])
            if not model_looks_snapshot_pinned(model)
        ]
        if unpinned:
            messages.append(
                Info(
                    "The AI model allowlist contains mutable aliases rather than dated "
                    "snapshots: " + ", ".join(unpinned) + ". Re-run live evaluations "
                    "after any provider-side model change, or pin a dated model snapshot "
                    "when stable behavior matters.",
                    id="assistant.I001",
                )
            )

    if (
        getattr(settings, "AI_COMPANY_DEFAULT_ENABLED", None) is True
        and getattr(settings, "AI_COMPANY_DEFAULT_PRIVACY_ACKNOWLEDGED", None)
        is not True
    ):
        messages.append(
            Warning(
                "New companies default to AI enabled without a default privacy acknowledgement; "
                "they will remain blocked until the notice is acknowledged in AI settings.",
                id="assistant.W005",
            )
        )

    provider = getattr(settings, "AI_PROVIDER", "openai")
    if provider == "openai" and not getattr(settings, "OPENAI_API_KEY", ""):
        messages.append(
            Error(
                "AI_ASSISTANT_ENABLED is true but OPENAI_API_KEY is blank.",
                id="assistant.E001",
            )
        )
    if getattr(settings, "AI_MAX_TOOL_ROUNDS", 0) < 1:
        messages.append(
            Error("AI_MAX_TOOL_ROUNDS must be at least 1.", id="assistant.E002")
        )
    max_tool_calls = getattr(settings, "AI_MAX_TOOL_CALLS", 0)
    if max_tool_calls < 1 or max_tool_calls > 12:
        messages.append(
            Error(
                "AI_MAX_TOOL_CALLS must be between 1 and 12.",
                id="assistant.E021",
            )
        )
    provider_timeout = getattr(settings, "AI_PROVIDER_TIMEOUT_SECONDS", 0)
    tool_rounds = getattr(settings, "AI_MAX_TOOL_ROUNDS", 0)
    worker_timeout = getattr(settings, "GUNICORN_TIMEOUT_SECONDS", 0)
    minimum_worker_timeout = provider_timeout * tool_rounds + 15
    if worker_timeout < minimum_worker_timeout:
        messages.append(
            Error(
                "GUNICORN_TIMEOUT_SECONDS must allow every configured AI tool round "
                f"plus shutdown headroom; use at least {minimum_worker_timeout} seconds.",
                id="assistant.E020",
            )
        )
    browser_timeout = getattr(settings, "AI_BROWSER_REQUEST_TIMEOUT_SECONDS", 0)
    if browser_timeout < worker_timeout + 5:
        messages.append(
            Error(
                "AI_BROWSER_REQUEST_TIMEOUT_SECONDS must exceed the Gunicorn worker "
                f"timeout; use at least {worker_timeout + 5} seconds.",
                id="assistant.E025",
            )
        )
    if getattr(settings, "AI_RATE_LIMIT_REQUESTS", 0) < 1:
        messages.append(
            Error(
                "AI_RATE_LIMIT_REQUESTS must be at least 1.",
                id="assistant.E026",
            )
        )
    if getattr(settings, "AI_LOCAL_ACTION_RATE_LIMIT_REQUESTS", 0) < 1:
        messages.append(
            Error(
                "AI_LOCAL_ACTION_RATE_LIMIT_REQUESTS must be at least 1.",
                id="assistant.E027",
            )
        )
    if getattr(settings, "AI_MAX_TOOL_OUTPUT_CHARS", 0) < 1000:
        messages.append(
            Error(
                "AI_MAX_TOOL_OUTPUT_CHARS must be at least 1000.",
                id="assistant.E005",
            )
        )
    focused_tokens = getattr(settings, "AI_FOCUSED_MAX_OUTPUT_TOKENS", 0)
    if focused_tokens < 128 or focused_tokens > getattr(settings, "AI_MAX_OUTPUT_TOKENS", 0):
        messages.append(
            Error(
                "AI_FOCUSED_MAX_OUTPUT_TOKENS must be at least 128 and no greater "
                "than AI_MAX_OUTPUT_TOKENS.",
                id="assistant.E022",
            )
        )
    focused_effort = getattr(settings, "AI_FOCUSED_REASONING_EFFORT", "")
    if focused_effort not in {"", "none", "minimal", "low", "medium", "high", "xhigh"}:
        messages.append(
            Error(
                "AI_FOCUSED_REASONING_EFFORT is not an allowed value.",
                id="assistant.E023",
            )
        )
    focused_verbosity = getattr(settings, "AI_FOCUSED_VERBOSITY", "")
    if focused_verbosity not in {"", "low", "medium", "high"}:
        messages.append(
            Error(
                "AI_FOCUSED_VERBOSITY must be low, medium, high, or blank.",
                id="assistant.E024",
            )
        )
    if not getattr(settings, "AI_REQUIRE_EXPLICIT_WRITE_INTENT", True):
        messages.append(
            Warning(
                "AI_REQUIRE_EXPLICIT_WRITE_INTENT is disabled; stored-text "
                "injection has a weaker server-side boundary.",
                id="assistant.W004",
            )
        )
    if getattr(settings, "AI_MONTHLY_COST_LIMIT_USD", 0) <= 0:
        messages.append(
            Warning(
                "AI_MONTHLY_COST_LIMIT_USD is not positive; requests will be blocked.",
                id="assistant.W001",
            )
        )
    if (
        getattr(settings, "AI_INPUT_COST_PER_MILLION_USD", 0) == 0
        and getattr(settings, "AI_OUTPUT_COST_PER_MILLION_USD", 0) == 0
        and not getattr(settings, "AI_MODEL_PRICING", {})
    ):
        messages.append(
            Warning(
                "AI token rates are zero, so the local dollar cost estimate will remain zero.",
                id="assistant.W002",
            )
        )
    missing_pricing = [
        model
        for model in getattr(settings, "AI_ALLOWED_MODELS", [])
        if model not in getattr(settings, "AI_MODEL_PRICING", {})
    ]
    if len(getattr(settings, "AI_ALLOWED_MODELS", [])) > 1 and missing_pricing:
        messages.append(
            Warning(
                "Some allowlisted models use the global fallback token rates: "
                + ", ".join(missing_pricing),
                id="assistant.W006",
            )
        )
    return messages
