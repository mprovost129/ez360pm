import hashlib
import hmac
import json
import time
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import stripe
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Company, User
from clients.tests.test_clients import create_client
from core.emailing import EmailDeliveryError
from documents.models import (
    Document,
    DocumentDelivery,
    Payment,
    PaymentRefund,
    StripeWebhookEvent,
)
from documents.proposal_services import apply_retainer_credit
from documents.services import (
    create_invoice,
    issue_document,
    record_payment,
    record_refund,
    save_line_item,
    void_invoice,
)
from documents.stripe_services import (
    StripeEventDependencyMissing,
    create_checkout_session,
    process_stripe_event,
)
from projects.services import create_project
from projects.tests.test_projects import project_data

from .test_billing import invoice_data


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="EZ360PM Tests <noreply@example.test>",
    STRIPE_SECRET_KEY="sk_test_payment_suite_only",
    STRIPE_WEBHOOK_SECRET="whsec_payment_suite_only",
)
class PaymentSystemSafetyTests(TestCase):
    """Payment-boundary tests that never contact Stripe or send real email."""

    def setUp(self):
        self.company = Company.objects.create(
            name="Provost Home Design",
            email="office@example.com",
        )
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        client = create_client(self.company)
        self.project = create_project(
            company=self.company,
            client=client,
            project_data=project_data(number="PAYMENT-SAFETY-1"),
        )
        self.client.force_login(self.user)
        fee_patcher = patch(
            "documents.stripe_services.stripe.PaymentIntent.retrieve",
            return_value=SimpleNamespace(
                latest_charge=SimpleNamespace(
                    balance_transaction=SimpleNamespace(fee=0)
                )
            ),
        )
        self.stripe_fee_lookup = fee_patcher.start()
        self.addCleanup(fee_patcher.stop)

    def make_invoice(
        self,
        *,
        amount="100.00",
        accept_payments=True,
        issue=True,
        invoice_kind=Document.InvoiceKind.FINAL,
        deposit_amount=None,
    ):
        data = invoice_data(
            accept_payments=accept_payments,
            invoice_kind=invoice_kind,
        )
        if deposit_amount is not None:
            data["deposit_amount"] = Decimal(deposit_amount)
        invoice = create_invoice(
            company=self.company,
            project=self.project,
            invoice_data=data,
            populate_project_lines=False,
        )
        save_line_item(
            document=invoice,
            line_data={
                "description": "Design services",
                "rate": Decimal(amount),
                "quantity": Decimal("1.00"),
                "tax_rate": Decimal("0"),
            },
        )
        if issue:
            issue_document(document=invoice)
        invoice.refresh_from_db()
        return invoice

    def stripe_event(
        self,
        invoice,
        *,
        intent="pi_payment_safety",
        amount=10000,
        event_id="evt_payment_safety",
        event_type="checkout.session.completed",
        payment_status="paid",
    ):
        return {
            "id": event_id,
            "type": event_type,
            "data": {
                "object": {
                    "id": f"cs_{event_id}",
                    "payment_status": payment_status,
                    "payment_intent": intent,
                    "amount_total": amount,
                    "currency": "usd",
                    "metadata": {
                        "document_id": str(invoice.pk),
                        "company_id": str(invoice.company_id),
                    },
                }
            },
        }

    @staticmethod
    def stripe_signature(payload, secret):
        timestamp = int(time.time())
        signed_payload = f"{timestamp}.{payload.decode()}".encode()
        digest = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={digest}"

    def test_checkout_uses_server_balance_identity_contact_and_fake_key(self):
        invoice = self.make_invoice(amount="125.00")
        record_payment(
            invoice=invoice,
            payment_data={
                "amount": Decimal("25.00"),
                "method": Payment.Method.CHECK,
                "received_at": date(2026, 7, 31),
                "reference": "partial check",
            },
        )

        with patch(
            "documents.stripe_services.stripe.checkout.Session.create",
            return_value=SimpleNamespace(url="https://checkout.stripe.test/session"),
        ) as create:
            create_checkout_session(
                invoice=invoice,
                success_url="https://app.example.test/success",
                cancel_url="https://app.example.test/cancel",
            )

        params = create.call_args.kwargs
        self.assertEqual(params["api_key"], "sk_test_payment_suite_only")
        self.assertEqual(params["line_items"][0]["price_data"]["unit_amount"], 10000)
        self.assertEqual(params["line_items"][0]["price_data"]["currency"], "usd")
        self.assertEqual(params["client_reference_id"], str(invoice.pk))
        self.assertEqual(params["metadata"]["company_id"], str(self.company.pk))
        self.assertEqual(params["payment_intent_data"]["metadata"], params["metadata"])
        self.assertEqual(params["customer_email"], "smith@example.com")

    def test_checkout_never_calls_stripe_for_ineligible_invoice_states(self):
        draft = self.make_invoice(issue=False)
        disabled = self.make_invoice(accept_payments=False)
        paid = self.make_invoice()
        record_payment(
            invoice=paid,
            payment_data={
                "amount": paid.amount_due,
                "method": Payment.Method.CHECK,
                "received_at": date(2026, 7, 31),
                "reference": "paid in office",
            },
        )
        voided = self.make_invoice()
        void_invoice(invoice=voided, reason="Issued in error")

        with patch(
            "documents.stripe_services.stripe.checkout.Session.create"
        ) as create:
            for invoice in (draft, disabled, paid, voided):
                with self.subTest(status=invoice.status, invoice=invoice.pk):
                    with self.assertRaises(ValidationError):
                        create_checkout_session(
                            invoice=invoice,
                            success_url="https://app.example.test/success",
                            cancel_url="https://app.example.test/cancel",
                        )

        create.assert_not_called()

    def test_deposit_checkout_collects_only_deposit_and_marks_it_paid(self):
        invoice = self.make_invoice(
            amount="1000.00",
            invoice_kind=Document.InvoiceKind.RETAINER,
            deposit_amount="250.00",
        )

        with patch(
            "documents.stripe_services.stripe.checkout.Session.create",
            return_value=SimpleNamespace(url="https://checkout.stripe.test/deposit"),
        ) as create:
            create_checkout_session(
                invoice=invoice,
                success_url="https://app.example.test/success",
                cancel_url="https://app.example.test/cancel",
            )
        payment = process_stripe_event(
            event=self.stripe_event(
                invoice,
                intent="pi_deposit",
                amount=25000,
                event_id="evt_deposit",
            )
        )

        self.assertEqual(
            create.call_args.kwargs["line_items"][0]["price_data"]["unit_amount"],
            25000,
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.total, Decimal("1000.00"))
        self.assertEqual(invoice.amount_due, Decimal("250.00"))
        self.assertEqual(payment.amount, Decimal("250.00"))
        self.assertEqual(invoice.status, Document.Status.PAID)
        self.assertEqual(invoice.outstanding_balance, Decimal("0.00"))

    def test_webhook_requires_post_and_complete_configuration(self):
        webhook_url = reverse("webhooks:stripe")
        self.assertEqual(self.client.get(webhook_url).status_code, 405)

        with override_settings(STRIPE_SECRET_KEY=""):
            with patch(
                "documents.stripe_views.stripe.Webhook.construct_event"
            ) as construct:
                response = self.client.post(
                    webhook_url,
                    data=b"{}",
                    content_type="application/json",
                    HTTP_STRIPE_SIGNATURE="unused",
                )

        self.assertEqual(response.status_code, 503)
        construct.assert_not_called()

    def test_real_stripe_sdk_signature_verification_and_replay_are_safe(self):
        invoice = self.make_invoice()
        event = self.stripe_event(invoice)
        payload = json.dumps(event, separators=(",", ":")).encode()
        signature = self.stripe_signature(payload, "whsec_payment_suite_only")
        webhook_url = reverse("webhooks:stripe")

        first = self.client.post(
            webhook_url,
            data=payload,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=signature,
        )
        replay = self.client.post(
            webhook_url,
            data=payload,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=signature,
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(Payment.objects.filter(document=invoice).count(), 1)
        self.assertEqual(
            DocumentDelivery.objects.filter(
                document=invoice,
                purpose=DocumentDelivery.Purpose.PAYMENT_NOTIFICATION,
            ).count(),
            1,
        )

    def test_unpaid_and_unrelated_webhooks_do_not_create_revenue(self):
        invoice = self.make_invoice()
        unpaid = self.stripe_event(
            invoice,
            intent="pi_unpaid",
            event_id="evt_unpaid",
            payment_status="unpaid",
        )
        unrelated = {
            "id": "evt_failed",
            "type": "payment_intent.payment_failed",
            "data": {"object": {"id": "pi_failed"}},
        }

        self.assertIsNone(process_stripe_event(event=unpaid))
        self.assertIsNone(process_stripe_event(event=unrelated))
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(DocumentDelivery.objects.exists())
        self.stripe_fee_lookup.assert_not_called()

    def test_malformed_signed_event_returns_400_without_revenue(self):
        invoice = self.make_invoice()
        event = self.stripe_event(invoice)
        event["data"]["object"]["metadata"].pop("document_id")

        with patch(
            "documents.stripe_views.stripe.Webhook.construct_event",
            return_value=event,
        ):
            response = self.client.post(
                reverse("webhooks:stripe"),
                data=json.dumps(event).encode(),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="verified-by-test-double",
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(DocumentDelivery.objects.exists())
        self.stripe_fee_lookup.assert_not_called()

    def test_partial_capture_and_replay_preserve_one_payment_and_balance(self):
        invoice = self.make_invoice(amount="100.00")
        event = self.stripe_event(
            invoice,
            intent="pi_partial",
            amount=4000,
            event_id="evt_partial",
        )

        first = process_stripe_event(event=event)
        replay = process_stripe_event(event=event)

        self.assertEqual(first.pk, replay.pk)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PARTIALLY_PAID)
        self.assertEqual(invoice.amount_paid, Decimal("40.00"))
        self.assertEqual(invoice.outstanding_balance, Decimal("60.00"))
        self.assertEqual(Payment.objects.filter(document=invoice).count(), 1)

    def test_payment_is_kept_when_internal_notification_delivery_fails(self):
        invoice = self.make_invoice()
        event = self.stripe_event(
            invoice,
            intent="pi_notification_failure",
            event_id="evt_notification_failure",
        )

        with patch(
            "documents.delivery_services.send_transactional_email",
            side_effect=EmailDeliveryError("provider_unavailable"),
        ):
            payment = process_stripe_event(event=event)

        invoice.refresh_from_db()
        delivery = DocumentDelivery.objects.get(
            document=invoice,
            purpose=DocumentDelivery.Purpose.PAYMENT_NOTIFICATION,
        )
        self.assertEqual(payment.amount, Decimal("100.00"))
        self.assertEqual(invoice.status, Document.Status.PAID)
        self.assertEqual(delivery.status, DocumentDelivery.Status.FAILED)
        self.assertEqual(delivery.error_code, "provider_unavailable")

    def test_stripe_payments_cannot_be_edited_or_deleted_through_manual_views(self):
        invoice = self.make_invoice()
        payment = process_stripe_event(event=self.stripe_event(invoice))

        edit = self.client.get(
            reverse("documents:payment-update", args=(invoice.pk, payment.pk))
        )
        delete = self.client.post(
            reverse("documents:payment-delete", args=(invoice.pk, payment.pk))
        )

        self.assertEqual(edit.status_code, 404)
        self.assertEqual(delete.status_code, 404)
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PAID)

    def test_checkout_provider_failure_returns_safely_without_changing_invoice(self):
        invoice = self.make_invoice()
        checkout_url = reverse(
            "public-documents:checkout", args=(invoice.public_token,)
        )

        with patch(
            "documents.stripe_views.create_checkout_session",
            side_effect=stripe.APIConnectionError("provider unavailable"),
        ):
            response = self.client.post(checkout_url)

        self.assertRedirects(
            response,
            reverse("public-documents:view", args=(invoice.public_token,)),
            fetch_redirect_response=False,
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.SENT)
        self.assertFalse(invoice.payments.exists())

    def test_checkout_attempts_are_rate_limited_before_provider_call(self):
        invoice = self.make_invoice()
        checkout_url = reverse(
            "public-documents:checkout", args=(invoice.public_token,)
        )

        with patch(
            "documents.stripe_views.create_checkout_session",
            return_value=SimpleNamespace(url="https://checkout.stripe.test/session"),
        ) as create:
            responses = [
                self.client.post(checkout_url, REMOTE_ADDR="198.51.100.42")
                for _attempt in range(11)
            ]

        self.assertEqual(responses[-1].status_code, 429)
        self.assertEqual(create.call_count, 10)

    def test_manual_refund_reduces_balance_and_reopens_invoice(self):
        invoice = self.make_invoice(amount="100.00")
        payment = record_payment(
            invoice=invoice,
            payment_data={
                "amount": Decimal("100.00"),
                "method": Payment.Method.CHECK,
                "received_at": date.today(),
                "reference": "Check #1042",
            },
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PAID)

        response = self.client.post(
            reverse("documents:payment-refund", args=(invoice.pk, payment.pk)),
            {
                "amount": "40.00",
                "effective_at": date.today().isoformat(),
                "reference": "Refunded by check",
            },
        )

        self.assertRedirects(
            response, reverse("documents:invoice-detail", args=(invoice.pk,))
        )
        payment.refresh_from_db()
        invoice.refresh_from_db()
        self.assertEqual(payment.refunded_amount, Decimal("40.00"))
        self.assertEqual(invoice.status, Document.Status.PARTIALLY_PAID)
        self.assertEqual(invoice.outstanding_balance, Decimal("40.00"))

    def test_manual_refund_rejects_amount_over_payment(self):
        invoice = self.make_invoice(amount="100.00")
        payment = record_payment(
            invoice=invoice,
            payment_data={
                "amount": Decimal("100.00"),
                "method": Payment.Method.CASH,
                "received_at": date.today(),
                "reference": "",
            },
        )

        response = self.client.post(
            reverse("documents:payment-refund", args=(invoice.pk, payment.pk)),
            {
                "amount": "150.00",
                "effective_at": date.today().isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot exceed the unrefunded payment amount")
        payment.refresh_from_db()
        self.assertEqual(payment.refunded_amount, Decimal("0.00"))

    def test_stripe_payments_cannot_be_refunded_through_manual_view(self):
        invoice = self.make_invoice()
        payment = process_stripe_event(event=self.stripe_event(invoice))

        get_response = self.client.get(
            reverse("documents:payment-refund", args=(invoice.pk, payment.pk))
        )
        post_response = self.client.post(
            reverse("documents:payment-refund", args=(invoice.pk, payment.pk)),
            {"amount": "10.00", "effective_at": date.today().isoformat()},
        )

        self.assertEqual(get_response.status_code, 404)
        self.assertEqual(post_response.status_code, 404)
        payment.refresh_from_db()
        self.assertEqual(payment.refunded_amount, Decimal("0.00"))

    def test_manual_refunds_are_incremental_append_only_history(self):
        invoice = self.make_invoice()
        payment = record_payment(
            invoice=invoice,
            payment_data={
                "amount": Decimal("100.00"),
                "method": Payment.Method.CHECK,
                "received_at": date.today(),
                "reference": "Check #2001",
            },
        )
        url = reverse("documents:payment-refund", args=(invoice.pk, payment.pk))

        for amount, reference in (("25.00", "Scope reduction"), ("10.00", "Courtesy")):
            response = self.client.post(
                url,
                {
                    "amount": amount,
                    "effective_at": date.today().isoformat(),
                    "reference": reference,
                },
            )
            self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        refunds = list(payment.refunds.order_by("created_at"))
        self.assertEqual(payment.refunded_amount, Decimal("35.00"))
        self.assertEqual([row.amount for row in refunds], [Decimal("25.00"), Decimal("10.00")])
        self.assertEqual(refunds[0].created_by, self.user)
        refunds[0].reference = "Changed history"
        with self.assertRaises(ValidationError):
            refunds[0].save()
        with self.assertRaises(ValidationError):
            payment.refunds.all().delete()

    def test_manual_refund_cannot_undercollateralize_applied_retainer(self):
        retainer = self.make_invoice(
            amount="100.00",
            invoice_kind=Document.InvoiceKind.RETAINER,
            deposit_amount="100.00",
        )
        payment = record_payment(
            invoice=retainer,
            payment_data={
                "amount": Decimal("100.00"),
                "method": Payment.Method.CHECK,
                "received_at": date.today(),
                "reference": "Deposit",
            },
        )
        final = self.make_invoice(
            amount="100.00",
            invoice_kind=Document.InvoiceKind.FINAL,
            issue=False,
        )
        apply_retainer_credit(
            source_invoice=retainer,
            destination_invoice=final,
            amount=Decimal("100.00"),
        )

        with self.assertRaisesMessage(ValidationError, "already applied"):
            record_refund(payment=payment, amount=Decimal("1.00"))
        self.assertFalse(PaymentRefund.objects.filter(payment=payment).exists())

    def test_out_of_order_stripe_refund_retries_after_payment_arrives(self):
        invoice = self.make_invoice()
        refund_event = {
            "id": "evt_refund_first",
            "type": "charge.refunded",
            "data": {
                "object": {
                    "id": "ch_refund_first",
                    "payment_intent": "pi_refund_first",
                    "amount_refunded": 2500,
                }
            },
        }

        with self.assertRaises(StripeEventDependencyMissing):
            process_stripe_event(event=refund_event)
        process_stripe_event(
            event=self.stripe_event(
                invoice,
                intent="pi_refund_first",
                event_id="evt_payment_second",
            )
        )
        payment = process_stripe_event(event=refund_event)

        payment.refresh_from_db()
        event = StripeWebhookEvent.objects.get(event_id="evt_refund_first")
        self.assertEqual(payment.refunded_amount, Decimal("25.00"))
        self.assertEqual(event.status, StripeWebhookEvent.Status.PROCESSED)
        self.assertEqual(event.attempt_count, 2)
        self.assertEqual(payment.refunds.get().provider, PaymentRefund.Provider.STRIPE)

    def test_stripe_dispute_is_retained_for_review(self):
        invoice = self.make_invoice()
        payment = process_stripe_event(
            event=self.stripe_event(
                invoice,
                intent="pi_dispute_review",
                event_id="evt_dispute_payment",
            )
        )
        event = {
            "id": "evt_dispute_review",
            "type": "charge.dispute.created",
            "data": {
                "object": {
                    "id": "dp_review",
                    "payment_intent": "pi_dispute_review",
                    "amount": 10000,
                }
            },
        }

        self.assertIsNone(process_stripe_event(event=event))
        event_row = StripeWebhookEvent.objects.get(event_id="evt_dispute_review")
        self.assertEqual(event_row.status, StripeWebhookEvent.Status.REQUIRES_REVIEW)
        self.assertEqual(event_row.payment, payment)
