from decimal import Decimal

import stripe
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Document, Payment
from .services import money, record_payment


def stripe_configuration_status():
    secret_key = bool(settings.STRIPE_SECRET_KEY)
    webhook_secret = bool(settings.STRIPE_WEBHOOK_SECRET)
    return {
        "configured": secret_key and webhook_secret,
        "secret_key": secret_key,
        "webhook_secret": webhook_secret,
        "api_version": stripe.api_version,
    }


def _value(source, key, default=None):
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


@transaction.atomic
def create_checkout_session(*, invoice, success_url, cancel_url):
    invoice = (
        Document.objects.select_for_update()
        .select_related("company", "project", "project__client")
        .get(pk=invoice.pk)
    )
    if not stripe_configuration_status()["configured"]:
        raise ValidationError("Online payments are not configured.")
    if (
        invoice.doc_type != Document.Type.INVOICE
        or invoice.status
        not in {
            Document.Status.SENT,
            Document.Status.VIEWED,
            Document.Status.PARTIALLY_PAID,
        }
        or not invoice.accept_payments
        or invoice.outstanding_balance <= 0
    ):
        raise ValidationError("This invoice is not available for online payment.")

    amount_cents = int(money(invoice.outstanding_balance) * 100)
    metadata = {
        "document_id": str(invoice.pk),
        "company_id": str(invoice.company_id),
        "document_number": invoice.number,
    }
    params = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": str(invoice.pk),
        "metadata": metadata,
        "payment_intent_data": {
            "metadata": metadata,
            "description": f"Invoice {invoice.number}",
        },
        "line_items": [
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": amount_cents,
                    "product_data": {
                        "name": f"Invoice {invoice.number}",
                        "description": invoice.project.name,
                    },
                },
                "quantity": 1,
            }
        ],
    }
    contact = invoice.project.client.primary_contact
    if contact and contact.email:
        params["customer_email"] = contact.email
    return stripe.checkout.Session.create(
        **params,
        api_key=settings.STRIPE_SECRET_KEY,
    )


def process_stripe_event(*, event):
    event_type = _value(event, "type")
    if event_type not in {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    }:
        return None
    session = _value(_value(event, "data", {}), "object", {})
    if event_type == "checkout.session.completed" and _value(session, "payment_status") != "paid":
        return None

    metadata = _value(session, "metadata", {}) or {}
    document_id = _value(metadata, "document_id")
    company_id = _value(metadata, "company_id")
    payment_intent = _value(session, "payment_intent")
    payment_intent_id = _value(payment_intent, "id") if payment_intent else None
    if isinstance(payment_intent, str):
        payment_intent_id = payment_intent
    amount_total = _value(session, "amount_total")
    currency = (_value(session, "currency", "") or "").lower()
    if not all((document_id, company_id, payment_intent_id)) or amount_total is None:
        raise ValidationError("Stripe event is missing reconciliation metadata.")
    if currency != "usd":
        raise ValidationError("Stripe event currency does not match this account.")
    try:
        invoice = Document.objects.get(
            pk=int(document_id),
            company_id=int(company_id),
            doc_type=Document.Type.INVOICE,
        )
    except (Document.DoesNotExist, TypeError, ValueError):
        raise ValidationError("Stripe event does not match an invoice.") from None
    amount = money(Decimal(amount_total) / Decimal("100"))
    return record_payment(
        invoice=invoice,
        payment_data={
            "amount": amount,
            "method": Payment.Method.STRIPE,
            "received_at": timezone.localdate(),
            "reference": f"Stripe Checkout {_value(session, 'id', '')}"[:255],
            "stripe_payment_intent_id": payment_intent_id,
        },
    )
