from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Company, User
from assistant.followups import follow_up_metrics
from assistant.models import AIActionAttempt, AIInteraction
from assistant.registry import ActionContext, registry
from assistant.security import write_intent_authorized
from clients.tests.test_clients import create_client
from documents.delivery_services import public_document_url, send_document_email
from documents.models import Document, DocumentDelivery
from documents.proposal_services import create_proposal
from documents.services import (
    create_invoice,
    issue_document,
    record_payment,
    save_line_item,
)
from projects.services import create_project
from projects.tests.test_projects import project_data


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    AI_FOLLOW_UP_MIN_INTERVAL_HOURS=24,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    PUBLIC_BASE_URL="https://example.test",
    STRIPE_SECRET_KEY="",
    STRIPE_WEBHOOK_SECRET="",
)
class AssistantPhaseFourteenFollowUpTests(TestCase):
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
            prompt_summary="phase fourteen",
        )
        self.context = ActionContext(user=self.user, interaction=self.interaction)

    def _proposal(self):
        proposal = create_proposal(
            company=self.company,
            project=self.project,
            proposal_data={
                "number": "",
                "issue_date": timezone.localdate(),
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
        return issue_document(document=proposal)

    def _invoice(self, *, retainer=False, overdue=False):
        today = timezone.localdate()
        invoice = create_invoice(
            company=self.company,
            project=self.project,
            invoice_data={
                "invoice_kind": (
                    Document.InvoiceKind.RETAINER
                    if retainer
                    else Document.InvoiceKind.FINAL
                ),
                "number": "",
                "issue_date": today - timedelta(days=30),
                "due_date": today - timedelta(days=1) if overdue else today + timedelta(days=14),
                "terms": "Invoice terms",
                "notes": "",
                "accept_payments": False,
            },
        )
        save_line_item(
            document=invoice,
            line_data={
                "description": "Design services",
                "rate": Decimal("1000.00"),
                "quantity": Decimal("1.00"),
                "tax_rate": Decimal("0"),
            },
        )
        invoice.refresh_from_db()
        return issue_document(document=invoice)

    def _prepare(self, name, arguments):
        result = registry.invoke(context=self.context, name=name, arguments=arguments)
        self.assertIsNotNone(result.pending_action)
        return result.pending_action

    def test_context_classifies_open_proposal_and_exposes_only_company_contacts(self):
        proposal = self._proposal()
        result = registry.invoke(
            context=self.context,
            name="get_document_follow_up_context",
            arguments={"document_reference": proposal.number},
        ).data

        self.assertEqual(result["follow_up_kind"], DocumentDelivery.FollowUpKind.PROPOSAL)
        self.assertEqual(result["document"]["number"], proposal.number)
        self.assertEqual(result["eligible_recipients"][0]["contact_id"], self.contact.pk)

    def test_follow_up_requires_external_confirmation_and_records_purpose(self):
        proposal = self._proposal()
        attempt = self._prepare(
            "send_document_follow_up",
            {
                "document_reference": proposal.number,
                "follow_up_kind": "proposal",
                "recipient_contact_id": self.contact.pk,
                "email_subject": "Following up on your proposal",
                "email_message": "Please let me know if you have any questions about the proposal.",
            },
        )

        self.assertEqual(attempt.risk_level, AIActionAttempt.RiskLevel.EXTERNAL_COMMIT)
        self.assertIn("does not schedule", " ".join(attempt.preview["details"]))

        result = registry.execute_attempt(attempt=attempt)
        delivery = DocumentDelivery.objects.get(document=proposal)

        self.assertEqual(delivery.purpose, DocumentDelivery.Purpose.CLIENT_FOLLOW_UP)
        self.assertEqual(delivery.follow_up_kind, DocumentDelivery.FollowUpKind.PROPOSAL)
        self.assertEqual(delivery.status, DocumentDelivery.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(result["delivery_status"], DocumentDelivery.Status.SENT)

    def test_recent_follow_up_blocks_accidental_repeat(self):
        proposal = self._proposal()
        send_document_email(
            document=proposal,
            recipient_name=self.contact.get_full_name(),
            recipient_email=self.contact.email,
            document_url=public_document_url(proposal),
            subject="First reminder",
            message="Please review.",
            purpose=DocumentDelivery.Purpose.CLIENT_FOLLOW_UP,
            follow_up_kind=DocumentDelivery.FollowUpKind.PROPOSAL,
        )

        with self.assertRaisesMessage(ValidationError, "already sent within"):
            self._prepare(
                "send_document_follow_up",
                {
                    "document_reference": proposal.number,
                    "follow_up_kind": "proposal",
                    "recipient_contact_id": self.contact.pk,
                    "email_subject": "Second reminder",
                    "email_message": "Following up again.",
                },
            )

    def test_overdue_final_invoice_is_classified_separately(self):
        invoice = self._invoice(overdue=True)
        result = registry.invoke(
            context=self.context,
            name="get_document_follow_up_context",
            arguments={"document_reference": invoice.number},
        ).data

        self.assertEqual(
            result["follow_up_kind"],
            DocumentDelivery.FollowUpKind.OVERDUE_INVOICE,
        )
        self.assertGreaterEqual(result["document"]["days_overdue"], 1)

    def test_follow_up_report_is_company_scoped_and_detects_later_payment(self):
        invoice = self._invoice(overdue=True)
        delivery = send_document_email(
            document=invoice,
            recipient_name=self.contact.get_full_name(),
            recipient_email=self.contact.email,
            document_url=public_document_url(invoice),
            subject="Invoice reminder",
            message="The invoice is overdue.",
            purpose=DocumentDelivery.Purpose.CLIENT_FOLLOW_UP,
            follow_up_kind=DocumentDelivery.FollowUpKind.OVERDUE_INVOICE,
        )
        record_payment(
            invoice=invoice,
            payment_data={
                "amount": Decimal("1000.00"),
                "method": "check",
                "received_at": timezone.localdate(),
                "reference": "1001",
            },
        )

        metrics = follow_up_metrics(self.user, days=30)

        self.assertEqual(metrics["total"], 1)
        self.assertEqual(metrics["sent"], 1)
        self.assertEqual(metrics["subsequent_outcomes"], 1)
        self.assertEqual(metrics["recent"][0]["delivery"].pk, delivery.pk)

    def test_follow_up_report_view_and_export_are_company_scoped(self):
        proposal = self._proposal()
        send_document_email(
            document=proposal,
            recipient_name=self.contact.get_full_name(),
            recipient_email=self.contact.email,
            document_url=public_document_url(proposal),
            subject="Proposal reminder",
            message="Please review.",
            purpose=DocumentDelivery.Purpose.CLIENT_FOLLOW_UP,
            follow_up_kind=DocumentDelivery.FollowUpKind.PROPOSAL,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("assistant:follow-up-evidence"))
        export = self.client.get(reverse("assistant:follow-up-evidence-export"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, proposal.number)
        self.assertEqual(export.status_code, 200)
        self.assertIn(proposal.number, export.content.decode())

    def test_write_intent_requires_an_explicit_follow_up_request(self):
        self.assertTrue(
            write_intent_authorized(
                prompt="Send a follow-up on the Smith proposal.",
                tool_name="send_document_follow_up",
            )
        )
        self.assertFalse(
            write_intent_authorized(
                prompt="What proposals are still open?",
                tool_name="send_document_follow_up",
            )
        )
