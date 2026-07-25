import hashlib
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)


class PublicActionRateLimitUnavailable(Exception):
    """Raised when a public mutation cannot be safely rate limited."""


def public_action_rate_limited(*, request, token, action, limit=10):
    fingerprint = f"{action}:{token}:{request.META.get('REMOTE_ADDR', '')}"
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()
    key = f"ez360pm:public-action:{digest}"
    try:
        if cache.add(key, 1, timeout=60):
            return False
        return cache.incr(key) > limit
    except ValueError:
        return False
    except Exception as exc:
        logger.exception("Public action rate limiter is unavailable action=%s", action)
        raise PublicActionRateLimitUnavailable from exc
