import logging
from decimal import Decimal

import stripe
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .delivery_services import send_payment_notification
from .models import Document, Payment, PaymentRefund, StripeWebhookEvent
from .services import money, record_payment, record_refund

logger = logging.getLogger(__name__)


class StripeEventDependencyMissing(Exception):
    """A valid event arrived before the local record it depends on."""


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
    """Return the provider fee and whether Stripe has not finalized it yet.

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
        return Decimal("0.00"), True
    charge = _value(intent, "latest_charge")
    balance_txn = _value(charge, "balance_transaction") if charge else None
    fee_cents = _value(balance_txn, "fee") if balance_txn else None
    if fee_cents is None:
        return Decimal("0.00"), True
    return money(Decimal(fee_cents) / Decimal("100")), False


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


def _payment_intent_id(source):
    payment_intent = _value(source, "payment_intent")
    if isinstance(payment_intent, str):
        return payment_intent
    return _value(payment_intent, "id") if payment_intent else None


@transaction.atomic
def _apply_charge_refund(charge, *, event_id=""):
    """Append the difference between Stripe's cumulative total and our cache."""
    payment_intent_id = _payment_intent_id(charge)
    if not payment_intent_id:
        raise ValidationError("Stripe refund is missing its Payment Intent.")
    payment = (
        Payment.objects.select_for_update()
        .filter(stripe_payment_intent_id=payment_intent_id)
        .first()
    )
    if payment is None:
        raise StripeEventDependencyMissing(
            f"Payment Intent {payment_intent_id} has not been recorded yet."
        )
    refunded_cents = _value(charge, "amount_refunded") or 0
    refunded = money(Decimal(refunded_cents) / Decimal("100"))
    if refunded > payment.amount:
        raise ValidationError("Stripe refund exceeds the recorded payment amount.")
    delta = money(refunded - payment.refunded_amount)
    if delta > 0:
        record_refund(
            payment=payment,
            amount=delta,
            provider=PaymentRefund.Provider.STRIPE,
            provider_ref=event_id,
            reference=f"Stripe cumulative refund {refunded}",
            protect_applied_credit=False,
        )
        payment.refresh_from_db()
        logger.info(
            "Stripe refund applied intent=%s refunded=%s",
            payment_intent_id,
            refunded,
        )
    return payment


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
        raise StripeEventDependencyMissing(
            f"Payment Intent {payment_intent_id} has not been recorded yet."
        )
    fee_amount = _fee_from_charge(charge)
    if fee_amount is not None and (
        payment.fee_amount != fee_amount or payment.fee_pending
    ):
        payment.fee_amount = fee_amount
        payment.fee_pending = False
        payment.save(update_fields=["fee_amount", "fee_pending"])
    return payment


def _event_details(event):
    event_object = _value(_value(event, "data", {}), "object", {}) or {}
    return {
        "event_id": (_value(event, "id", "") or "")[:255],
        "event_type": (_value(event, "type", "") or "")[:100],
        "object_id": (_value(event_object, "id", "") or "")[:255],
        "payment_intent_id": (_payment_intent_id(event_object) or "")[:255],
    }


def _safe_error_code(exc):
    if isinstance(exc, ValidationError):
        errors = getattr(exc, "error_list", ())
        return ((errors[0].code if errors else "") or "validation_error")[:100]
    return exc.__class__.__name__.lower()[:100]


def _process_stripe_event(*, event, event_id=""):
    event_type = _value(event, "type")
    event_object = _value(_value(event, "data", {}), "object", {})
    if event_type == "charge.refunded":
        return _apply_charge_refund(event_object, event_id=event_id)
    if event_type == "charge.dispute.created":
        logger.warning(
            "Stripe dispute opened charge=%s amount=%s - reconcile manually",
            _value(event_object, "charge"),
            _value(event_object, "amount"),
        )
        return None
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
    fee_amount, fee_pending = _retrieve_stripe_fee(payment_intent_id)
    payment = record_payment(
        invoice=invoice,
        payment_data={
            "amount": amount,
            "fee_amount": fee_amount,
            "fee_pending": fee_pending,
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


def process_stripe_event(*, event):
    """Process a verified event once and retain safe retry/review state."""

    details = _event_details(event)
    event_row = None
    known_payment = None
    if details["payment_intent_id"]:
        known_payment = Payment.objects.filter(
            stripe_payment_intent_id=details["payment_intent_id"]
        ).first()
    if details["event_id"]:
        event_row, created = StripeWebhookEvent.objects.get_or_create(
            event_id=details["event_id"],
            defaults={
                "event_type": details["event_type"],
                "object_id": details["object_id"],
                "payment_intent_id": details["payment_intent_id"],
                "payment": known_payment,
            },
        )
        if not created and event_row.status in {
            StripeWebhookEvent.Status.PROCESSED,
            StripeWebhookEvent.Status.IGNORED,
        }:
            return event_row.payment
        if not created and event_row.status == StripeWebhookEvent.Status.REQUIRES_REVIEW:
            if event_row.event_type == "charge.dispute.created":
                return event_row.payment
            raise ValidationError("Stripe event requires manual review.")
        if not created:
            event_row.attempt_count += 1
            event_row.status = StripeWebhookEvent.Status.PENDING
            event_row.error_code = ""
            event_row.last_attempt_at = timezone.now()
            if known_payment and event_row.payment_id is None:
                event_row.payment = known_payment
            event_row.save(
                update_fields=(
                    "attempt_count",
                    "status",
                    "error_code",
                    "last_attempt_at",
                    "payment",
                )
            )

    try:
        result = _process_stripe_event(
            event=event,
            event_id=details["event_id"],
        )
    except StripeEventDependencyMissing as exc:
        if event_row:
            event_row.status = StripeWebhookEvent.Status.FAILED
            event_row.error_code = _safe_error_code(exc)
            event_row.save(update_fields=("status", "error_code"))
        raise
    except ValidationError as exc:
        if event_row:
            event_row.status = StripeWebhookEvent.Status.REQUIRES_REVIEW
            event_row.error_code = _safe_error_code(exc)
            event_row.processed_at = timezone.now()
            event_row.save(update_fields=("status", "error_code", "processed_at"))
        raise
    except Exception as exc:
        if event_row:
            event_row.status = StripeWebhookEvent.Status.FAILED
            event_row.error_code = _safe_error_code(exc)
            event_row.save(update_fields=("status", "error_code"))
        raise

    if event_row:
        if details["event_type"] == "charge.dispute.created":
            status = StripeWebhookEvent.Status.REQUIRES_REVIEW
        elif result is None:
            status = StripeWebhookEvent.Status.IGNORED
        else:
            status = StripeWebhookEvent.Status.PROCESSED
        event_row.status = status
        event_row.error_code = ""
        event_row.processed_at = timezone.now()
        if isinstance(result, Payment):
            event_row.payment = result
        event_row.save(
            update_fields=("status", "error_code", "processed_at", "payment")
        )
    return result
