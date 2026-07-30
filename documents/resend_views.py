import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from svix.webhooks import Webhook, WebhookVerificationError

from .resend_services import process_resend_event

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def resend_webhook(request):
    if not settings.RESEND_WEBHOOK_SECRET:
        return HttpResponse(status=503)
    headers = {
        "svix-id": request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }
    try:
        event = Webhook(settings.RESEND_WEBHOOK_SECRET).verify(request.body, headers)
    except (WebhookVerificationError, ValueError):
        return HttpResponse(status=400)
    try:
        process_resend_event(event_id=headers["svix-id"], event=event)
    except ValueError as exc:
        logger.warning("Resend webhook rejected error=%s", exc.__class__.__name__)
        return HttpResponse(status=400)
    return JsonResponse({"received": True})
