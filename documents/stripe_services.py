import logging
from decimal import Decimal

import stripe
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .delivery_services import send_payment_notification
from .models import Document, Payment
from .services import money, record_payment

logger = logging.getLogger(__name__)


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


def _retrieve_stripe_fee(payment_intent_id):
    """Return the exact provider fee for a captured PaymentIntent, in dollars.

    Revenue must be recorded even when Stripe's fee data is momentarily
    unavailable, so any failure degrades to a zero fee rather than blocking the
    payment; the fee can be reconciled later from the Stripe dashboard.
    """
    try:
        intent = stripe.PaymentIntent.retrieve(
            payment_intent_id,
            expand=["latest_charge.balance_transaction"],
            api_key=settings.STRIPE_SECRET_KEY,
        )
    except stripe.StripeError:
        logger.warning("Stripe fee lookup failed intent=%s", payment_intent_id)
        return Decimal("0.00")
    charge = _value(intent, "latest_charge")
    balance_txn = _value(charge, "balance_transaction") if charge else None
    fee_cents = _value(balance_txn, "fee") if balance_txn else None
    if fee_cents is None:
        return Decimal("0.00")
    return money(Decimal(fee_cents) / Decimal("100"))


def _fee_from_charge(charge):
    balance_transaction = _value(charge, "balance_transaction")
    if isinstance(balance_transaction, str):
        try:
            balance_transaction = stripe.BalanceTransaction.retrieve(
                balance_transaction,
                api_key=settings.STRIPE_SECRET_KEY,
            )
        except stripe.StripeError:
            logger.warning(
                "Stripe balance transaction lookup failed transaction=%s",
                balance_transaction,
            )
            return None
    fee_cents = _value(balance_transaction, "fee") if balance_transaction else None
    if fee_cents is None:
        return None
    return money(Decimal(fee_cents) / Decimal("100"))


def _reconcile_charge_fee(charge):
    payment_intent = _value(charge, "payment_intent")
    payment_intent_id = _value(payment_intent, "id") if payment_intent else None
    if isinstance(payment_intent, str):
        payment_intent_id = payment_intent
    if not payment_intent_id:
        return None
    payment = Payment.objects.filter(
        stripe_payment_intent_id=payment_intent_id,
    ).first()
    if payment is None:
        return None
    fee_amount = _fee_from_charge(charge)
    if fee_amount is not None and payment.fee_amount != fee_amount:
        payment.fee_amount = fee_amount
        payment.save(update_fields=["fee_amount"])
    return payment


def process_stripe_event(*, event):
    event_type = _value(event, "type")
    event_object = _value(_value(event, "data", {}), "object", {})
    if event_type in {"charge.succeeded", "charge.updated"}:
        return _reconcile_charge_fee(event_object)
    if event_type not in {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    }:
        return None
    session = event_object
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
    fee_amount = _retrieve_stripe_fee(payment_intent_id)
    payment = record_payment(
        invoice=invoice,
        payment_data={
            "amount": amount,
            "fee_amount": fee_amount,
            "method": Payment.Method.STRIPE,
            "received_at": timezone.localdate(),
            "reference": f"Stripe Checkout {_value(session, 'id', '')}"[:255],
            "stripe_payment_intent_id": payment_intent_id,
        },
        # A captured Stripe payment is real money: record it even if the balance
        # dropped since Checkout was created, rather than rejecting and forcing
        # Stripe to retry a webhook that can never succeed.
        allow_overpayment=True,
    )
    send_payment_notification(payment=payment)
    return payment
