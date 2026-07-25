import logging
from functools import partial

import stripe
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .delivery_services import public_document_url
from .models import Document, Payment
from .public_security import (
    PublicActionRateLimitUnavailable,
    public_action_rate_limited,
)
from .public_views import public_document
from .stripe_services import (
    create_checkout_session,
    process_stripe_event,
    stripe_configuration_status,
)
from .webhook_failures import (
    record_stripe_webhook_failure,
    resolve_stripe_webhook_failure,
)

logger = logging.getLogger(__name__)


class DeferredWorkJsonResponse(JsonResponse):
    """Run best-effort work after WSGI has finished sending the acknowledgement."""

    def __init__(self, *args, deferred_work=None, **kwargs):
        self.deferred_work = deferred_work
        super().__init__(*args, **kwargs)

    def close(self):
        super().close()
        deferred_work = self.deferred_work
        self.deferred_work = None
        if deferred_work is not None:
            deferred_work()


def _finish_stripe_webhook(event):
    try:
        process_stripe_event(event=event)
    except Exception as exc:
        logger.exception(
            "Deferred Stripe webhook work failed event_id=%s error=%s",
            getattr(event, "id", "") or (event.get("id", "") if isinstance(event, dict) else ""),
            exc.__class__.__name__,
        )


class PublicCheckoutView(View):
    def post(self, request, token):
        try:
            limited = public_action_rate_limited(
                request=request,
                token=token,
                action="checkout",
            )
        except PublicActionRateLimitUnavailable:
            return HttpResponse(
                "Online payment is temporarily unavailable. Please try again shortly.",
                status=503,
            )
        if limited:
            return HttpResponse("Too many payment attempts. Please wait and try again.", status=429)
        invoice = public_document(token)
        if invoice.doc_type != Document.Type.INVOICE:
            return redirect("public-documents:view", token=token)
        public_url = public_document_url(invoice)
        separator = "&" if "?" in public_url else "?"
        try:
            session = create_checkout_session(
                invoice=invoice,
                success_url=f"{public_url}{separator}payment=success",
                cancel_url=public_url,
            )
        except (ValidationError, stripe.StripeError) as exc:
            logger.warning(
                "Checkout creation failed document_id=%s error=%s",
                invoice.pk,
                exc.__class__.__name__,
            )
            return redirect("public-documents:view", token=token)
        return redirect(session.url)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    if not stripe_configuration_status()["configured"]:
        return HttpResponse(status=503)
    try:
        event = stripe.Webhook.construct_event(
            request.body,
            request.headers.get("Stripe-Signature", ""),
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponse(status=400)
    try:
        result = process_stripe_event(event=event, defer_slow_work=True)
    except ValidationError as exc:
        record_stripe_webhook_failure(event=event, exception=exc)
        logger.warning("Stripe reconciliation rejected error=%s", exc.__class__.__name__)
        return HttpResponse(status=400)
    except Exception as exc:  # verified provider events must remain visible for retry
        record_stripe_webhook_failure(event=event, exception=exc)
        logger.exception("Stripe reconciliation failed error=%s", exc.__class__.__name__)
        return HttpResponse(status=500)
    if result is not None:
        resolve_stripe_webhook_failure(event=event)
    deferred_work = None
    if isinstance(result, Payment):
        deferred_work = partial(_finish_stripe_webhook, event)
    return DeferredWorkJsonResponse(
        {"received": True},
        deferred_work=deferred_work,
    )
