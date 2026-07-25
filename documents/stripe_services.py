import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import stripe
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .delivery_services import queue_payment_notification, send_payment_notification
from .models import (
    Document,
    Payment,
    PaymentAdjustment,
    PaymentFeeReconciliationAttempt,
)
from .services import money, record_payment, record_payment_adjustment

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StripeFeeLookupResult:
    fee_amount: Decimal
    pending: bool
    error_code: str = ""
    error_message: str = ""


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


def create_checkout_session(*, invoice, success_url, cancel_url):
    invoice = (
        Document.objects.select_related("company", "project", "project__client")
        .get(pk=invoice.pk)
    )
    if not stripe_configuration_status()["configured"]:
        raise ValidationError("Online payments are not configured.")
    amount_paid = invoice.amount_paid
    outstanding_balance = max(invoice.total - amount_paid, Decimal("0.00"))
    if (
        invoice.doc_type != Document.Type.INVOICE
        or invoice.status
        not in {
            Document.Status.SENT,
            Document.Status.VIEWED,
            Document.Status.PARTIALLY_PAID,
        }
        or not invoice.accept_payments
        or outstanding_balance <= 0
    ):
        raise ValidationError("This invoice is not available for online payment.")

    amount_cents = int(money(outstanding_balance) * 100)
    paid_cents = int(money(amount_paid) * 100)
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
        # The same invoice balance can be submitted more than once by browser
        # retries or multiple tabs. Stripe will return the original Session for
        # this balance state instead of creating another payable Session.
        idempotency_key=(
            f"ez360pm-checkout-v1-{invoice.pk}-{amount_cents}-{paid_cents}"
        ),
    )


def _retrieve_stripe_fee(payment_intent_id):
    """Return Stripe fee data without blocking receipt creation.

    A payment remains valid even when Stripe has not finalized its fee. The
    result carries a safe error code/message so reconciliation attempts can be
    audited without storing provider secrets.
    """
    try:
        intent = stripe.PaymentIntent.retrieve(
            payment_intent_id,
            expand=["latest_charge.balance_transaction"],
            api_key=settings.STRIPE_SECRET_KEY,
        )
    except stripe.StripeError as exc:
        logger.warning("Stripe fee lookup failed intent=%s", payment_intent_id)
        return StripeFeeLookupResult(
            Decimal("0.00"),
            True,
            error_code=(getattr(exc, "code", "") or exc.__class__.__name__)[:100],
            error_message="Stripe could not return the processing fee. Retry later.",
        )
    charge = _value(intent, "latest_charge")
    balance_txn = _value(charge, "balance_transaction") if charge else None
    fee_cents = _value(balance_txn, "fee") if balance_txn else None
    if fee_cents is None:
        return StripeFeeLookupResult(
            Decimal("0.00"),
            True,
            error_code="fee_unavailable",
            error_message="Stripe has not finalized the processing fee yet.",
        )
    return StripeFeeLookupResult(
        money(Decimal(fee_cents) / Decimal("100")),
        False,
    )


def _record_fee_reconciliation_attempt(*, payment, lookup, status=None):
    if status is None:
        status = (
            PaymentFeeReconciliationAttempt.Status.ERROR
            if lookup.error_code and lookup.error_code != "fee_unavailable"
            else PaymentFeeReconciliationAttempt.Status.PENDING
        )
    attempt = PaymentFeeReconciliationAttempt(
        company=payment.document.company,
        payment=payment,
        status=status,
        observed_fee=None if lookup.pending else lookup.fee_amount,
        error_code=lookup.error_code,
        error_message=lookup.error_message,
    )
    attempt.full_clean()
    attempt.save()
    return attempt


def _apply_resolved_pending_fee(*, payment, fee_amount, provider_reference):
    """Resolve a missing Stripe fee without rewriting a closed accounting period.

    Before the receipt period is closed, the fee belongs on the original payment.
    After closing, preserve the historical receipt and post the newly learned fee as
    a dated adjustment in the current open period.
    """

    closed_through = payment.document.company.books_closed_through
    if closed_through and payment.received_at <= closed_through:
        difference = payment.fee_current_amount - fee_amount
        if difference:
            record_payment_adjustment(
                payment=payment,
                adjustment_data={
                    "adjustment_type": (
                        PaymentAdjustment.Type.FEE_REFUND
                        if difference > 0
                        else PaymentAdjustment.Type.FEE_ADJUSTMENT
                    ),
                    "amount": difference,
                    "effective_at": timezone.localdate(),
                    "affects_invoice_balance": False,
                    "affects_processing_fees": True,
                    "provider_id": (
                        f"stripe-fee-reconciliation:{provider_reference}:{fee_amount}"
                    )[:255],
                    "reference": "Stripe processing fee resolved after period close",
                },
                allow_closed_period=True,
                allow_balance_exception=True,
            )
        payment.fee_current_amount = fee_amount
        payment.fee_pending = False
        payment.save(update_fields=["fee_current_amount", "fee_pending"])
        return payment

    payment.fee_amount = fee_amount
    payment.fee_current_amount = fee_amount
    payment.fee_pending = False
    payment.save(update_fields=["fee_amount", "fee_current_amount", "fee_pending"])
    return payment


@transaction.atomic
def reconcile_pending_payment_fee(*, payment):
    payment = (
        Payment.objects.select_for_update()
        .select_related("document__company")
        .get(pk=payment.pk)
    )
    if payment.method != Payment.Method.STRIPE or not payment.fee_pending:
        return False
    if not payment.stripe_payment_intent_id:
        return False
    lookup = _retrieve_stripe_fee(payment.stripe_payment_intent_id)
    if lookup.pending:
        _record_fee_reconciliation_attempt(payment=payment, lookup=lookup)
        return False
    _apply_resolved_pending_fee(
        payment=payment,
        fee_amount=lookup.fee_amount,
        provider_reference=payment.stripe_payment_intent_id,
    )
    _record_fee_reconciliation_attempt(
        payment=payment,
        lookup=lookup,
        status=PaymentFeeReconciliationAttempt.Status.RESOLVED,
    )
    return True


def _fee_from_charge(charge, *, allow_provider_lookup=True):
    balance_transaction = _value(charge, "balance_transaction")
    if isinstance(balance_transaction, str):
        if not allow_provider_lookup:
            return None
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


def _stripe_effective_date(source):
    created = _value(source, "created")
    if created is None:
        return timezone.localdate()
    try:
        moment = datetime.fromtimestamp(int(created), tz=UTC)
    except (TypeError, ValueError, OSError):
        return timezone.localdate()
    return timezone.localtime(moment).date()


def _payment_intent_id(source):
    payment_intent = _value(source, "payment_intent")
    if isinstance(payment_intent, str):
        return payment_intent
    return _value(payment_intent, "id") if payment_intent else None


def _payment_for_stripe_object(source):
    payment_intent_id = _payment_intent_id(source)
    if not payment_intent_id:
        charge = _value(source, "charge")
        if isinstance(charge, str):
            try:
                charge = stripe.Charge.retrieve(
                    charge,
                    api_key=settings.STRIPE_SECRET_KEY,
                )
            except stripe.StripeError as exc:
                logger.warning("Stripe charge lookup failed while importing adjustment")
                raise ValidationError(
                    "Stripe could not resolve the adjustment's charge. Retry the event later.",
                    code="provider_lookup_failed",
                ) from exc
        payment_intent_id = _payment_intent_id(charge) if charge else None
    if not payment_intent_id:
        return None
    return Payment.objects.filter(
        stripe_payment_intent_id=payment_intent_id,
    ).first()


def _record_refund(refund):
    if _value(refund, "status") not in {None, "succeeded"}:
        return None
    payment = _payment_for_stripe_object(refund)
    refund_id = _value(refund, "id")
    amount_cents = _value(refund, "amount")
    if payment is None:
        raise ValidationError(
            "Stripe refund does not match a recorded payment.",
            code="payment_not_found",
        )
    if not refund_id or amount_cents is None:
        raise ValidationError(
            "Stripe refund is missing required import data.",
            code="invalid_adjustment_data",
        )
    return record_payment_adjustment(
        payment=payment,
        adjustment_data={
            "adjustment_type": PaymentAdjustment.Type.REFUND,
            "amount": -money(Decimal(amount_cents) / Decimal("100")),
            "effective_at": _stripe_effective_date(refund),
            "affects_invoice_balance": True,
            "affects_processing_fees": False,
            "provider_id": f"stripe-refund:{refund_id}",
            "reference": f"Stripe refund {refund_id}"[:255],
        },
        allow_closed_period=True,
        allow_balance_exception=True,
    )


def _record_dispute(dispute, *, reversal=False, effective_source=None):
    payment = _payment_for_stripe_object(dispute)
    dispute_id = _value(dispute, "id")
    amount_cents = _value(dispute, "amount")
    if payment is None:
        raise ValidationError(
            "Stripe dispute does not match a recorded payment.",
            code="payment_not_found",
        )
    if not dispute_id or amount_cents is None:
        raise ValidationError(
            "Stripe dispute is missing required import data.",
            code="invalid_adjustment_data",
        )
    amount = money(Decimal(amount_cents) / Decimal("100"))
    suffix = "reversal" if reversal else "created"
    return record_payment_adjustment(
        payment=payment,
        adjustment_data={
            "adjustment_type": (
                PaymentAdjustment.Type.DISPUTE_REVERSAL
                if reversal
                else PaymentAdjustment.Type.DISPUTE
            ),
            "amount": amount if reversal else -amount,
            "effective_at": _stripe_effective_date(
                effective_source if effective_source is not None else dispute
            ),
            "affects_invoice_balance": True,
            "affects_processing_fees": False,
            "provider_id": f"stripe-dispute:{dispute_id}:{suffix}",
            "reference": f"Stripe dispute {dispute_id} {suffix}"[:255],
        },
        allow_closed_period=True,
        allow_balance_exception=True,
    )


@transaction.atomic
def _reconcile_charge_fee(
    charge,
    *,
    event_id="",
    effective_source=None,
    allow_provider_lookup=True,
):
    payment_intent_id = _payment_intent_id(charge)
    if not payment_intent_id:
        return None
    payment = (
        Payment.objects.select_for_update()
        .select_related("document__company")
        .filter(stripe_payment_intent_id=payment_intent_id)
        .first()
    )
    if payment is None:
        return None
    fee_amount = _fee_from_charge(
        charge,
        allow_provider_lookup=allow_provider_lookup,
    )
    if fee_amount is None:
        if payment.fee_pending:
            _record_fee_reconciliation_attempt(
                payment=payment,
                lookup=StripeFeeLookupResult(
                    Decimal("0.00"),
                    True,
                    error_code="fee_unavailable",
                    error_message="Stripe charge did not include a finalized fee.",
                ),
            )
        return payment
    if payment.fee_pending:
        resolved = _apply_resolved_pending_fee(
            payment=payment,
            fee_amount=fee_amount,
            provider_reference=_value(charge, "id") or payment_intent_id,
        )
        _record_fee_reconciliation_attempt(
            payment=payment,
            lookup=StripeFeeLookupResult(fee_amount, False),
            status=PaymentFeeReconciliationAttempt.Status.RESOLVED,
        )
        return resolved
    if payment.fee_current_amount != fee_amount:
        difference = payment.fee_current_amount - fee_amount
        charge_id = _value(charge, "id") or payment_intent_id
        record_payment_adjustment(
            payment=payment,
            adjustment_data={
                "adjustment_type": (
                    PaymentAdjustment.Type.FEE_REFUND
                    if difference > 0
                    else PaymentAdjustment.Type.FEE_ADJUSTMENT
                ),
                "amount": difference,
                "effective_at": _stripe_effective_date(
                    effective_source if effective_source is not None else charge
                ),
                "affects_invoice_balance": False,
                "affects_processing_fees": True,
                "provider_id": (
                    f"stripe-event:{event_id}:fee"
                    if event_id
                    else f"stripe-fee-adjustment:{charge_id}:{fee_amount}"
                )[:255],
                "reference": "Stripe processing fee adjustment",
            },
            allow_closed_period=True,
        )
        payment.fee_current_amount = fee_amount
        payment.save(update_fields=["fee_current_amount"])
    return payment


def process_stripe_event(*, event, defer_slow_work=False):
    event_type = _value(event, "type")
    event_id = _value(event, "id", "") or ""
    event_object = _value(_value(event, "data", {}), "object", {})
    if event_type in {"charge.succeeded", "charge.updated"}:
        return _reconcile_charge_fee(
            event_object,
            event_id=event_id,
            effective_source=event,
            allow_provider_lookup=not defer_slow_work,
        )
    if event_type in {"refund.created", "refund.updated"}:
        return _record_refund(event_object)
    if event_type == "charge.refunded":
        refunds = _value(_value(event_object, "refunds", {}), "data", []) or []
        return [_record_refund(refund) for refund in refunds]
    if event_type == "charge.dispute.created":
        return _record_dispute(event_object, effective_source=event)
    if event_type == "charge.dispute.closed" and _value(event_object, "status") == "won":
        return _record_dispute(event_object, reversal=True, effective_source=event)
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
    fee_lookup = (
        StripeFeeLookupResult(
            Decimal("0.00"),
            True,
            error_code="fee_unavailable",
            error_message="Stripe fee reconciliation is queued after acknowledgement.",
        )
        if defer_slow_work
        else _retrieve_stripe_fee(payment_intent_id)
    )
    payment = record_payment(
        invoice=invoice,
        payment_data={
            "amount": amount,
            "fee_amount": fee_lookup.fee_amount,
            "fee_current_amount": fee_lookup.fee_amount,
            "fee_pending": fee_lookup.pending,
            "method": Payment.Method.STRIPE,
            "received_at": _stripe_effective_date(session),
            "reference": f"Stripe Checkout {_value(session, 'id', '')}"[:255],
            "stripe_payment_intent_id": payment_intent_id,
        },
        # A captured Stripe payment is real money: record it even if the balance
        # dropped since Checkout was created, rather than rejecting and forcing
        # Stripe to retry a webhook that can never succeed.
        allow_overpayment=True,
        allow_closed_period=True,
    )
    if not fee_lookup.pending and payment.fee_pending:
        _apply_resolved_pending_fee(
            payment=payment,
            fee_amount=fee_lookup.fee_amount,
            provider_reference=_value(session, "id", "") or payment_intent_id,
        )
        _record_fee_reconciliation_attempt(
            payment=payment,
            lookup=fee_lookup,
            status=PaymentFeeReconciliationAttempt.Status.RESOLVED,
        )
    elif fee_lookup.pending:
        _record_fee_reconciliation_attempt(payment=payment, lookup=fee_lookup)
    if defer_slow_work:
        queue_payment_notification(payment=payment)
    else:
        send_payment_notification(payment=payment)
    return payment
