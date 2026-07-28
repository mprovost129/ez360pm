from django.conf import settings

from .local_actions import CLIENT_TEMPLATE_TEXT
from .policies import assistant_available, get_company_policy, risk_allowed


def assistant_status(request):
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return {"ai_assistant_enabled": False}
    policy = get_company_policy(user.company)
    enabled = bool(
        getattr(settings, "AI_ASSISTANT_ENABLED", False)
        and assistant_available(policy, user=user)
    )
    return {
        "ai_assistant_enabled": enabled,
        "ai_company_settings": policy,
        "ai_assistant_request_timeout_ms": max(
            int(getattr(settings, "AI_BROWSER_REQUEST_TIMEOUT_SECONDS", 195)), 1
        )
        * 1000,
        "ai_client_template_text": CLIENT_TEMPLATE_TEXT,
        "ai_client_template_enabled": risk_allowed(policy, "structured_write"),
    }
