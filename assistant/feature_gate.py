from functools import wraps

from django.conf import settings
from django.http import Http404


def assistant_feature_required(view_func):
    """Hide every assistant endpoint when the platform feature flag is off.

    The gate runs before the wrapped view, so direct requests cannot create AI
    policy/audit rows or perform any assistant work while AI is globally disabled.
    A 404 keeps the optional feature out of the public surface rather than exposing
    configuration details through a permission or availability response.
    """

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not getattr(settings, "AI_ASSISTANT_ENABLED", False):
            raise Http404("AI assistant is not enabled.")
        return view_func(request, *args, **kwargs)

    return wrapped
