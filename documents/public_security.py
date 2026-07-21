import hashlib

from django.core.cache import cache


def public_action_rate_limited(*, request, token, action, limit=10):
    fingerprint = f"{action}:{token}:{request.META.get('REMOTE_ADDR', '')}"
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()
    key = f"ez360pm:public-action:{digest}"
    if cache.add(key, 1, timeout=60):
        return False
    try:
        return cache.incr(key) > limit
    except ValueError:
        return False
