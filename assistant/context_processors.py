from django.conf import settings

from .local_actions import CLIENT_TEMPLATE_TEXT
from .policies import (
    assistant_available,
    default_policy_for_company,
    get_company_policy,
    risk_allowed,
)


def _disabled_context():
    return {
        "ai_assistant_enabled": False,
        "ai_client_template_enabled": False,
    }


def assistant_status(request):
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return _disabled_context()

    # AI is optional. When the platform feature flag is off, ordinary EZ360PM
    # pages must not query or create any assistant records.
    if not getattr(settings, "AI_ASSISTANT_ENABLED", False):
        return _disabled_context()

    # Rendering an ordinary page is read-only. Use an existing company policy
    # when present; otherwise evaluate the deployment defaults with an unsaved
    # policy. The real row is created by AI settings or the first AI request.
    policy = get_company_policy(user.company, create=False)
    if policy is None:
        policy = default_policy_for_company(user.company)

    enabled = assistant_available(policy, user=user)
    return {
        "ai_assistant_enabled": enabled,
        "ai_company_settings": policy,
        "ai_assistant_request_timeout_ms": max(
            int(getattr(settings, "AI_BROWSER_REQUEST_TIMEOUT_SECONDS", 195)), 1
        )
        * 1000,
        "ai_client_template_text": CLIENT_TEMPLATE_TEXT,
        "ai_client_template_enabled": bool(
            enabled and risk_allowed(policy, "structured_write")
        ),
    }
