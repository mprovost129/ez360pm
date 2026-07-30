from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Company, User
from assistant.models import AIActionAttempt, AIInteraction
from assistant.registry import ActionContext, registry
from clients.tests.test_clients import create_client
from documents.models import Document, DocumentDelivery, Payment
from documents.proposal_services import create_proposal
from documents.services import create_invoice, issue_document, save_line_item
from projects.services import create_project
from projects.tests.test_projects import project_data


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    PUBLIC_BASE_URL="https://example.test",
    STRIPE_SECRET_KEY="",
    STRIPE_WEBHOOK_SECRET="",
)
class AssistantPhaseFiveConsequentialActionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Provost Home Design",
            email="office@example.com",
        )
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.client_record = create_client(self.company, company_name="Smith Household")
        self.contact = self.client_record.primary_contact
        self.project = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="2607001", name="Smith Addition"),
        )
        self.interaction = AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="test",
            model="test-model",
            prompt_summary="phase five",
        )
        self.context = ActionContext(user=self.user, interaction=self.interaction)

    def _prepare(self, name, arguments):
        result = registry.invoke(context=self.context, name=name, arguments=arguments)
        self.assertIsNotNone(result.pending_action)
        return result.pending_action

    def _proposal(self):
        proposal = create_proposal(
            company=self.company,
            project=self.project,
            proposal_data={
                "number": "",
                "issue_date": date(2026, 7, 27),
                "terms": "Proposal terms",
                "notes": "",
            },
        )
        save_line_item(
            document=proposal,
            line_data={
                "description": "Residential design services",
                "rate": Decimal("4500.00"),
                "quantity": Decimal("1.00"),
                "tax_rate": Decimal("0"),
            },
        )
        proposal.refresh_from_db()
        return proposal

    def _invoice(self):
        invoice = create_invoice(
            company=self.company,
            project=self.project,
            invoice_data={
                "invoice_kind": Document.InvoiceKind.FINAL,
                "number": "",
                "issue_date": date(2026, 7, 27),
                "due_date": date(2026, 8, 26),
                "terms": "Due within 30 days",
                "notes": "",
                "accept_payments": False,
            },
        )
        if not invoice.line_items.exists():
            save_line_item(
                document=invoice,
                line_data={
                    "description": "Residential design services",
                    "rate": Decimal("4500.00"),
                    "quantity": Decimal("1.00"),
                    "tax_rate": Decimal("0"),
                },
            )
        invoice.refresh_from_db()
        return invoice

    def test_issue_and_send_requires_external_confirmation_and_preserves_wording(self):
        proposal = self._proposal()
        attempt = self._prepare(
            "issue_and_send_document",
            {
                "document_reference": proposal.number,
                "recipient_contact_id": self.contact.pk,
                "email_subject": "Your Smith Addition proposal",
                "email_message": "Please review the attached scope and pricing.",
            },
        )

        self.assertEqual(attempt.risk_level, AIActionAttempt.RiskLevel.EXTERNAL_COMMIT)
        self.assertEqual(proposal.status, Document.Status.DRAFT)
        self.assertIn(self.contact.email, " ".join(attempt.preview["details"]))

        result = registry.execute_attempt(attempt=attempt)

        proposal.refresh_from_db()
        delivery = DocumentDelivery.objects.get(document=proposal)
        self.assertEqual(proposal.status, Document.Status.SENT)
        self.assertEqual(delivery.status, DocumentDelivery.Status.SENT)
        self.assertEqual(delivery.subject, "Your Smith Addition proposal")
        self.assertEqual(delivery.message, "Please review the attached scope and pricing.")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Please review", mail.outbox[0].body)
        self.assertEqual(result["delivery_status"], DocumentDelivery.Status.SENT)

    def test_stale_document_confirmation_is_rejected_before_issue(self):
        proposal = self._proposal()
        attempt = self._prepare(
            "issue_document",
            {"document_reference": proposal.number},
        )
        save_line_item(
            document=proposal,
            line_data={
                "description": "Additional service",
                "rate": Decimal("100.00"),
                "quantity": Decimal("1.00"),
                "tax_rate": Decimal("0"),
            },
        )

        with self.assertRaises(ValidationError):
            registry.execute_attempt(attempt=attempt)

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Document.Status.DRAFT)
        self.assertFalse(DocumentDelivery.objects.exists())

    def test_other_company_contact_cannot_receive_document(self):
        proposal = self._proposal()
        other_client = create_client(self.other_company, company_name="Hidden")

        with self.assertRaises(ValidationError):
            self._prepare(
                "issue_and_send_document",
                {
                    "document_reference": proposal.number,
                    "recipient_contact_id": other_client.primary_contact.pk,
                    "email_subject": None,
                    "email_message": None,
                },
            )

    def test_delivery_failure_preserves_issued_document_and_failed_attempt(self):
        proposal = self._proposal()
        attempt = self._prepare(
            "issue_and_send_document",
            {
                "document_reference": proposal.number,
                "recipient_contact_id": self.contact.pk,
                "email_subject": None,
                "email_message": None,
            },
        )

        with patch(
            "core.emailing.EmailMultiAlternatives.send",
            side_effect=TimeoutError("mail timeout"),
        ):
            result = registry.execute_attempt(attempt=attempt)

        proposal.refresh_from_db()
        delivery = DocumentDelivery.objects.get(document=proposal)
        self.assertEqual(proposal.status, Document.Status.SENT)
        self.assertEqual(delivery.status, DocumentDelivery.Status.FAILED)
        self.assertEqual(result["delivery_status"], DocumentDelivery.Status.FAILED)

    def test_manual_payment_uses_current_balance_and_existing_service(self):
        invoice = self._invoice()
        issue_document(document=invoice)
        invoice.refresh_from_db()
        attempt = self._prepare(
            "record_manual_payment",
            {
                "invoice_reference": invoice.number,
                "amount": 500,
                "method": "check",
                "received_at": "2026-07-28",
                "reference": "Check 1042",
            },
        )

        registry.execute_attempt(attempt=attempt)

        payment = Payment.objects.get(document=invoice)
        invoice.refresh_from_db()
        self.assertEqual(payment.amount, Decimal("500.00"))
        self.assertEqual(payment.method, Payment.Method.CHECK)
        self.assertEqual(invoice.status, Document.Status.PARTIALLY_PAID)

    def test_invoice_with_payment_cannot_be_voided_through_assistant(self):
        invoice = self._invoice()
        issue_document(document=invoice)
        invoice.refresh_from_db()
        Payment.objects.create(
            document=invoice,
            amount=Decimal("100.00"),
            method=Payment.Method.CHECK,
            received_at=date(2026, 7, 28),
        )

        with self.assertRaises(ValidationError):
            self._prepare(
                "void_invoice",
                {"invoice_reference": invoice.number, "reason": "Entered incorrectly"},
            )


    def test_external_commit_endpoint_requires_final_review_acknowledgement(self):
        proposal = self._proposal()
        attempt = self._prepare("issue_document", {"document_reference": proposal.number})
        self.client.force_login(self.user)
        url = reverse("assistant:confirm-action", args=(attempt.confirmation_token,))

        response = self.client.post(url, data="{}", content_type="application/json")

        self.assertEqual(response.status_code, 409)
        attempt.refresh_from_db()
        proposal.refresh_from_db()
        self.assertEqual(attempt.status, AIActionAttempt.Status.PENDING)
        self.assertEqual(proposal.status, Document.Status.DRAFT)

    def test_confirm_endpoint_is_idempotent(self):
        proposal = self._proposal()
        attempt = self._prepare("issue_document", {"document_reference": proposal.number})
        self.client.force_login(self.user)
        url = reverse("assistant:confirm-action", args=(attempt.confirmation_token,))

        payload = '{"final_review_acknowledged": true}'
        first = self.client.post(url, data=payload, content_type="application/json")
        second = self.client.post(url, data=payload, content_type="application/json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["already_completed"])
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Document.Status.SENT)
