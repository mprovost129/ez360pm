from django.utils import timezone

from .models import AIActionAttempt


def expire_pending_actions(*, user=None, company=None):
    queryset = AIActionAttempt.objects.filter(
        status=AIActionAttempt.Status.PENDING,
        confirmation_expires_at__lte=timezone.now(),
    )
    if user is not None:
        queryset = queryset.filter(user=user, company=user.company)
    elif company is not None:
        queryset = queryset.filter(company=company)
    return queryset.update(status=AIActionAttempt.Status.EXPIRED)


def serialize_action(attempt):
    return {
        "token": str(attempt.confirmation_token),
        "tool_name": attempt.tool_name,
        "preview": attempt.preview,
        "expires_at": attempt.confirmation_expires_at.isoformat(),
        "risk_level": attempt.risk_level,
        "status": attempt.status,
        "created_at": attempt.created_at.isoformat(),
    }


def pending_actions_for_user(user, *, limit=20):
    expire_pending_actions(user=user)
    attempts = AIActionAttempt.objects.filter(
        company=user.company,
        user=user,
        status=AIActionAttempt.Status.PENDING,
        confirmation_expires_at__gt=timezone.now(),
    ).order_by("confirmation_expires_at", "pk")[:limit]
    return [serialize_action(attempt) for attempt in attempts]
