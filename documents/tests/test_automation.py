import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import stripe
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Company, User
from clients.tests.test_clients import create_client
from documents.delivery_services import send_document_email
from documents.models import Document, DocumentDelivery, Payment
from documents.proposal_services import create_proposal
from documents.services import (
    create_invoice,
    issue_document,
    record_payment,
    save_line_item,
)
from documents.stripe_services import create_checkout_session, process_stripe_event
from projects.services import create_project
from projects.tests.test_projects import project_data

from .test_billing import invoice_data


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="Provost Home Design <noreply@example.com>",
    STRIPE_SECRET_KEY="sk_test_configured",
    STRIPE_WEBHOOK_SECRET="whsec_test_configured",
)
class DeliveryAndStripeTests(TestCase):
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
        self.project = create_project(
            company=self.company,
            client=create_client(self.company),
            project_data=project_data(number="AUTOMATION-1"),
        )
        self.client.force_login(self.user)
        # Fee lookups call the Stripe API; stub them so webhook tests stay offline.
        fee_patcher = patch(
            "documents.stripe_services.stripe.PaymentIntent.retrieve",
            return_value=SimpleNamespace(
                latest_charge=SimpleNamespace(balance_transaction=SimpleNamespace(fee=0))
            ),
        )
        self.mock_stripe_fee = fee_patcher.start()
        self.addCleanup(fee_patcher.stop)

    def set_stripe_fee(self, fee_cents):
        self.mock_stripe_fee.return_value = SimpleNamespace(
            latest_charge=SimpleNamespace(
                balance_transaction=SimpleNamespace(fee=fee_cents)
            )
        )

    def make_invoice(self, *, accept_payments=True, amount="100.00"):
        invoice = create_invoice(
            company=self.company,
            project=self.project,
            invoice_data=invoice_data(accept_payments=accept_payments),
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
        issue_document(document=invoice)
        invoice.refresh_from_db()
        return invoice

    def make_proposal(self):
        proposal = create_proposal(
            company=self.company,
            project=self.project,
            proposal_data={
                "number": "",
                "issue_date": date(2026, 7, 21),
                "terms": "<p>Valid for 30 days.</p>",
                "notes": "Internal",
            },
        )
        save_line_item(
            document=proposal,
            line_data={
                "description": "Design services",
                "rate": Decimal("1000.00"),
                "quantity": Decimal("1.00"),
                "tax_rate": Decimal("0"),
            },
        )
        issue_document(document=proposal)
        proposal.refresh_from_db()
        return proposal

    def stripe_event(self, invoice, *, intent="pi_phase5", amount=10000):
        return {
            "id": "evt_phase5",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_phase5",
                    "payment_status": "paid",
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

    def test_document_email_records_sent_attempt_and_public_link(self):
        invoice = self.make_invoice()

        delivery = send_document_email(
            document=invoice,
            recipient_name="Alex Smith",
            recipient_email="ALEX@example.com",
            document_url="https://app.example.com/d/invoice-token/",
        )

        self.assertEqual(delivery.status, DocumentDelivery.Status.SENT)
        self.assertIsNotNone(delivery.sent_at)
        self.assertEqual(delivery.recipient_email, "alex@example.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("https://app.example.com/d/invoice-token/", mail.outbox[0].body)

    def test_provider_failure_is_preserved_without_sensitive_error_text(self):
        invoice = self.make_invoice()
        with patch(
            "documents.delivery_services.EmailMultiAlternatives.send",
            side_effect=RuntimeError("credential contents must not be stored"),
        ):
            delivery = send_document_email(
                document=invoice,
                recipient_name="Alex Smith",
                recipient_email="alex@example.com",
                document_url="https://app.example.com/d/token/",
            )

        self.assertEqual(delivery.status, DocumentDelivery.Status.FAILED)
        self.assertEqual(delivery.error_code, "runtimeerror")
        self.assertNotIn("credential", delivery.error_code)

    def test_send_view_prefills_contact_and_shows_delivery_history(self):
        proposal = self.make_proposal()

        get_response = self.client.get(reverse("proposals:send", args=(proposal.pk,)))
        post_response = self.client.post(
            reverse("proposals:send", args=(proposal.pk,)),
            {"recipient_name": "Alex Smith", "recipient_email": "alex@example.com"},
        )
        detail = self.client.get(reverse("proposals:detail", args=(proposal.pk,)))

        self.assertContains(get_response, "smith@example.com")
        self.assertRedirects(post_response, reverse("proposals:detail", args=(proposal.pk,)))
        self.assertContains(detail, "alex@example.com")
        self.assertContains(detail, "Sent")

    def test_send_view_cannot_retrieve_another_company_document(self):
        other_company = Company.objects.create(name="Other Studio")
        other_project = create_project(
            company=other_company,
            client=create_client(other_company, company_name="Other Client"),
            project_data=project_data(number="OTHER-AUTOMATION"),
        )
        other_invoice = create_invoice(
            company=other_company,
            project=other_project,
            invoice_data=invoice_data(accept_payments=True),
        )
        save_line_item(
            document=other_invoice,
            line_data={
                "description": "Other services",
                "rate": Decimal("100.00"),
                "quantity": Decimal("1"),
                "tax_rate": Decimal("0"),
            },
        )
        issue_document(document=other_invoice)

        response = self.client.get(
            reverse("documents:invoice-send", args=(other_invoice.pk,))
        )

        self.assertEqual(response.status_code, 404)

    def test_public_acceptance_sends_one_internal_notification(self):
        proposal = self.make_proposal()
        accept_url = reverse("public-documents:accept", args=(proposal.public_token,))
        data = {"signer_name": "Alex Smith", "signer_email": "alex@example.com"}

        first = self.client.post(accept_url, data, REMOTE_ADDR="203.0.113.8")
        second = self.client.post(accept_url, data, REMOTE_ADDR="203.0.113.8")

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        notifications = DocumentDelivery.objects.filter(
            document=proposal,
            purpose=DocumentDelivery.Purpose.ACCEPTANCE_NOTIFICATION,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.get().status, DocumentDelivery.Status.SENT)
        self.assertIn("Proposal", mail.outbox[0].subject)

    def test_public_response_attempts_are_rate_limited(self):
        proposal = self.make_proposal()
        accept_url = reverse("public-documents:accept", args=(proposal.public_token,))
        data = {"signer_name": "Alex Smith", "signer_email": "alex@example.com"}

        responses = [
            self.client.post(accept_url, data, REMOTE_ADDR="198.51.100.9")
            for _attempt in range(11)
        ]

        self.assertEqual(responses[-1].status_code, 429)
        self.assertEqual(
            DocumentDelivery.objects.filter(
                document=proposal,
                purpose=DocumentDelivery.Purpose.ACCEPTANCE_NOTIFICATION,
            ).count(),
            1,
        )

    def test_checkout_amount_comes_from_current_server_balance(self):
        invoice = self.make_invoice()
        record_payment(
            invoice=invoice,
            payment_data={
                "amount": Decimal("25.00"),
                "method": Payment.Method.CHECK,
                "received_at": date(2026, 7, 22),
                "reference": "partial",
            },
        )
        invoice.refresh_from_db()

        with patch(
            "documents.stripe_services.stripe.checkout.Session.create",
            return_value=SimpleNamespace(url="https://checkout.stripe.test/session"),
        ) as create:
            session = create_checkout_session(
                invoice=invoice,
                success_url="https://app.example.com/success",
                cancel_url="https://app.example.com/cancel",
            )

        self.assertEqual(session.url, "https://checkout.stripe.test/session")
        params = create.call_args.kwargs
        self.assertEqual(params["line_items"][0]["price_data"]["unit_amount"], 7500)
        self.assertEqual(params["metadata"]["document_id"], str(invoice.pk))
        self.assertEqual(
            params["payment_intent_data"]["metadata"]["company_id"],
            str(self.company.pk),
        )

    def test_checkout_rejects_invoice_that_does_not_allow_online_payment(self):
        invoice = self.make_invoice(accept_payments=False)

        with self.assertRaises(ValidationError):
            create_checkout_session(
                invoice=invoice,
                success_url="https://app.example.com/success",
                cancel_url="https://app.example.com/cancel",
            )

    def test_public_checkout_redirects_only_after_server_session_creation(self):
        invoice = self.make_invoice()
        with patch(
            "documents.stripe_views.create_checkout_session",
            return_value=SimpleNamespace(url="https://checkout.stripe.test/session"),
        ) as create:
            response = self.client.post(
                reverse("public-documents:checkout", args=(invoice.public_token,))
            )

        self.assertRedirects(
            response,
            "https://checkout.stripe.test/session",
            fetch_redirect_response=False,
        )
        self.assertEqual(create.call_args.kwargs["invoice"].pk, invoice.pk)

    def test_public_pay_button_requires_complete_configuration_and_invoice_opt_in(self):
        invoice = self.make_invoice()
        public_url = reverse("public-documents:view", args=(invoice.public_token,))

        configured = self.client.get(public_url)
        with override_settings(STRIPE_WEBHOOK_SECRET=""):
            unconfigured = self.client.get(public_url)

        self.assertContains(configured, "Pay $100.00")
        self.assertNotContains(unconfigured, "Pay $100.00")

    def test_customer_payment_journey_updates_view_status_revenue_and_net(self):
        invoice = self.make_invoice()
        public_path = reverse("public-documents:view", args=(invoice.public_token,))
        delivery = send_document_email(
            document=invoice,
            recipient_name="Alex Smith",
            recipient_email="alex@example.com",
            document_url=f"https://app.example.com{public_path}",
        )

        self.assertEqual(delivery.status, DocumentDelivery.Status.SENT)
        self.assertIn(public_path, mail.outbox[0].body)

        public_response = self.client.get(public_path)
        invoice.refresh_from_db()
        self.assertEqual(public_response.status_code, 200)
        self.assertEqual(invoice.status, Document.Status.VIEWED)
        self.assertIsNotNone(invoice.viewed_at)

        with patch(
            "documents.stripe_views.create_checkout_session",
            return_value=SimpleNamespace(url="https://checkout.stripe.test/session"),
        ):
            checkout_response = self.client.post(
                reverse("public-documents:checkout", args=(invoice.public_token,))
            )
        self.assertEqual(checkout_response.status_code, 302)
        self.assertEqual(
            checkout_response.url,
            "https://checkout.stripe.test/session",
        )

        self.set_stripe_fee(320)
        event = self.stripe_event(invoice)
        with patch(
            "documents.stripe_views.stripe.Webhook.construct_event",
            return_value=event,
        ):
            webhook_response = self.client.post(
                reverse("webhooks:stripe"),
                data=json.dumps(event).encode(),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signed-header",
            )

        self.assertEqual(webhook_response.status_code, 200)
        invoice.refresh_from_db()
        payment = invoice.payments.get()
        self.assertEqual(invoice.status, Document.Status.PAID)
        self.assertEqual(invoice.outstanding_balance, Decimal("0.00"))
        self.assertEqual(payment.amount, Decimal("100.00"))
        self.assertEqual(payment.fee_amount, Decimal("3.20"))
        self.assertEqual(payment.net_amount, Decimal("96.80"))

        revenue_response = self.client.get(
            reverse("core:revenue"),
            {"month": payment.received_at.strftime("%Y-%m")},
        )
        self.assertEqual(revenue_response.context["revenue_total"], Decimal("100.00"))
        self.assertEqual(revenue_response.context["fee_total"], Decimal("3.20"))
        self.assertEqual(revenue_response.context["net_total"], Decimal("96.80"))

    def test_webhook_payment_and_replay_share_idempotent_payment_service(self):
        invoice = self.make_invoice()
        event = self.stripe_event(invoice)

        first = process_stripe_event(event=event)
        replay = process_stripe_event(event=event)

        self.assertEqual(first.pk, replay.pk)
        self.assertEqual(Payment.objects.filter(document=invoice).count(), 1)
        notifications = DocumentDelivery.objects.filter(
            document=invoice,
            purpose=DocumentDelivery.Purpose.PAYMENT_NOTIFICATION,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.get().status, DocumentDelivery.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Payment received", mail.outbox[0].subject)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PAID)
        self.assertEqual(invoice.outstanding_balance, Decimal("0.00"))

    def test_async_checkout_success_records_payment(self):
        invoice = self.make_invoice()
        event = self.stripe_event(invoice, intent="pi_async")
        event["type"] = "checkout.session.async_payment_succeeded"
        event["data"]["object"]["payment_status"] = "unpaid"

        payment = process_stripe_event(event=event)

        self.assertEqual(payment.method, Payment.Method.STRIPE)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PAID)

    def test_stripe_capture_records_even_when_balance_dropped_after_checkout(self):
        # A manual payment can land between Checkout creation and the webhook,
        # leaving the captured amount larger than the current balance. The
        # verified capture is real money and must be recorded, not rejected into
        # an endlessly retried webhook.
        invoice = self.make_invoice(amount="100.00")
        record_payment(
            invoice=invoice,
            payment_data={
                "amount": Decimal("40.00"),
                "method": Payment.Method.CHECK,
                "received_at": date(2026, 7, 22),
                "reference": "walk-in check",
            },
        )
        event = self.stripe_event(invoice, intent="pi_overpay", amount=10000)

        payment = process_stripe_event(event=event)

        self.assertEqual(payment.amount, Decimal("100.00"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PAID)
        self.assertEqual(invoice.amount_paid, Decimal("140.00"))
        self.assertEqual(invoice.outstanding_balance, Decimal("0.00"))

    def test_manual_payment_still_rejects_amount_over_the_balance(self):
        invoice = self.make_invoice(amount="100.00")

        with self.assertRaises(ValidationError):
            record_payment(
                invoice=invoice,
                payment_data={
                    "amount": Decimal("150.00"),
                    "method": Payment.Method.CHECK,
                    "received_at": date(2026, 7, 22),
                    "reference": "entry typo",
                },
            )
        self.assertFalse(Payment.objects.filter(document=invoice).exists())

    def test_stripe_payment_records_exact_provider_fee_and_net(self):
        invoice = self.make_invoice()  # $100.00 invoice
        self.set_stripe_fee(320)  # 2.9% + $0.30 on $100
        event = self.stripe_event(invoice)

        payment = process_stripe_event(event=event)

        self.assertEqual(payment.amount, Decimal("100.00"))
        self.assertEqual(payment.fee_amount, Decimal("3.20"))
        self.assertEqual(payment.net_amount, Decimal("96.80"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PAID)

    def test_stripe_fee_lookup_failure_still_records_payment_with_zero_fee(self):
        invoice = self.make_invoice()
        self.mock_stripe_fee.side_effect = stripe.StripeError("fee not available yet")
        event = self.stripe_event(invoice)

        payment = process_stripe_event(event=event)

        self.assertEqual(payment.amount, Decimal("100.00"))
        self.assertEqual(payment.fee_amount, Decimal("0.00"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PAID)

    def test_later_charge_event_reconciles_temporarily_missing_fee(self):
        invoice = self.make_invoice()
        self.mock_stripe_fee.side_effect = stripe.StripeError("fee not available yet")
        payment = process_stripe_event(event=self.stripe_event(invoice))
        self.assertEqual(payment.fee_amount, Decimal("0.00"))

        reconciled = process_stripe_event(
            event={
                "type": "charge.updated",
                "data": {
                    "object": {
                        "payment_intent": "pi_phase5",
                        "balance_transaction": {"fee": 320},
                    }
                },
            }
        )

        reconciled.refresh_from_db()
        self.assertEqual(reconciled.pk, payment.pk)
        self.assertEqual(reconciled.fee_amount, Decimal("3.20"))

    def test_manual_payment_carries_no_provider_fee(self):
        invoice = self.make_invoice()
        record_payment(
            invoice=invoice,
            payment_data={
                "amount": Decimal("100.00"),
                "method": Payment.Method.CHECK,
                "received_at": date(2026, 7, 22),
                "reference": "check 1201",
            },
        )

        payment = invoice.payments.get()
        self.assertEqual(payment.fee_amount, Decimal("0.00"))
        self.assertEqual(payment.net_amount, Decimal("100.00"))

    def test_webhook_rejects_untrusted_company_metadata_and_currency(self):
        invoice = self.make_invoice()
        wrong_company = self.stripe_event(invoice)
        wrong_company["data"]["object"]["metadata"]["company_id"] = "999999"
        wrong_currency = self.stripe_event(invoice, intent="pi_currency")
        wrong_currency["data"]["object"]["currency"] = "eur"

        with self.assertRaises(ValidationError):
            process_stripe_event(event=wrong_company)
        with self.assertRaises(ValidationError):
            process_stripe_event(event=wrong_currency)
        self.assertFalse(Payment.objects.exists())

    def test_webhook_view_passes_raw_body_to_signature_verifier_and_replays_safely(self):
        invoice = self.make_invoice()
        event = self.stripe_event(invoice)
        payload = json.dumps(event).encode()
        webhook_url = reverse("webhooks:stripe")

        with patch(
            "documents.stripe_views.stripe.Webhook.construct_event",
            return_value=event,
        ) as construct:
            first = self.client.post(
                webhook_url,
                data=payload,
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signed-header",
            )
            replay = self.client.post(
                webhook_url,
                data=payload,
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="signed-header",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(construct.call_args_list[0].args[0], payload)
        self.assertEqual(construct.call_args_list[0].args[1], "signed-header")
        self.assertEqual(Payment.objects.filter(document=invoice).count(), 1)

    def test_invalid_webhook_signature_is_rejected(self):
        response = self.client.post(
            reverse("webhooks:stripe"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="invalid",
        )

        self.assertEqual(response.status_code, 400)

    def test_integration_status_reports_presence_without_exposing_secrets(self):
        response = self.client.get(reverse("accounts:integrations"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Configured", count=2)
        self.assertNotContains(response, "sk_test_configured")
        self.assertNotContains(response, "whsec_test_configured")
