from django.conf import settings

from .policies import assistant_available, get_company_policy


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
    }
