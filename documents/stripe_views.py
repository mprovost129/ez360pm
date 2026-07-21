import logging

import stripe
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .delivery_services import public_document_url
from .models import Document
from .public_security import public_action_rate_limited
from .public_views import public_document
from .stripe_services import (
    create_checkout_session,
    process_stripe_event,
    stripe_configuration_status,
)

logger = logging.getLogger(__name__)


class PublicCheckoutView(View):
    def post(self, request, token):
        if public_action_rate_limited(
            request=request,
            token=token,
            action="checkout",
        ):
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
        process_stripe_event(event=event)
    except ValidationError as exc:
        logger.warning("Stripe reconciliation rejected error=%s", exc.__class__.__name__)
        return HttpResponse(status=400)
    return JsonResponse({"received": True})
