from datetime import UTC, date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from accounts.models import Company, User
from assistant.draft_tracking import track_completed_draft_action
from assistant.models import AIDocumentDraftReview, AIInteraction
from assistant.registry import ActionContext, registry
from assistant.security import write_intent_authorized
from clients.tests.test_clients import create_client
from documents.models import Document
from documents.proposal_services import create_proposal, save_proposal_section
from documents.services import attach_time_to_invoice, create_invoice, save_line_item
from projects.models import TimeEntry
from projects.services import create_project
from projects.tests.test_projects import project_data
from projects.time_services import save_manual_entry


@override_settings(AI_ASSISTANT_ENABLED=True)
class AssistantPhaseThirteenDocumentRevisionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Provost Home Design",
            default_proposal_terms="<p>Proposal terms.</p>",
            default_invoice_terms="<p>Invoice terms.</p>",
            default_invoice_due_days=30,
            accept_payments_default=True,
        )
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.client_record = create_client(
            self.company,
            company_name="Smith Household",
        )
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
            prompt_summary="phase thirteen",
        )
        self.context = ActionContext(user=self.user, interaction=self.interaction)

    def _prepare(self, name, arguments):
        return registry.invoke(
            context=self.context,
            name=name,
            arguments=arguments,
        ).pending_action

    def _proposal(self):
        proposal = create_proposal(
            company=self.company,
            project=self.project,
            proposal_data={
                "number": "",
                "issue_date": date(2026, 7, 27),
                "terms": "<p>Original terms.</p>",
                "notes": "Original internal note.",
            },
        )
        save_proposal_section(
            proposal=proposal,
            heading="Scope of work",
            body="<p>Original scope.</p>",
        )
        save_line_item(
            document=proposal,
            line_data={
                "description": "Design services",
                "rate": Decimal("4500.00"),
                "quantity": Decimal("1.00"),
                "tax_rate": Decimal("0"),
            },
        )
        proposal.refresh_from_db()
        return proposal

    def _hourly_invoice(self):
        entry = save_manual_entry(
            user=self.user,
            project=self.project,
            entry_data={
                "start_time": datetime(2026, 7, 27, 13, 0, tzinfo=UTC),
                "end_time": datetime(2026, 7, 27, 15, 0, tzinfo=UTC),
                "description": "roof revisions",
                "billable": True,
            },
        )
        invoice = create_invoice(
            company=self.company,
            project=self.project,
            invoice_data={
                "invoice_kind": Document.InvoiceKind.FINAL,
                "number": "",
                "issue_date": date(2026, 7, 27),
                "due_date": date(2026, 8, 26),
                "terms": "<p>Original invoice terms.</p>",
                "notes": "Original invoice note.",
                "accept_payments": False,
            },
        )
        attach_time_to_invoice(invoice=invoice, entries=[entry], grouping="individual")
        invoice.refresh_from_db()
        entry.refresh_from_db()
        return invoice, entry

    def test_existing_draft_context_returns_editable_document_only(self):
        proposal = self._proposal()

        result = registry.invoke(
            context=self.context,
            name="get_existing_document_draft_context",
            arguments={"document_reference": proposal.number},
        ).data

        self.assertEqual(result["document"]["number"], proposal.number)
        self.assertEqual(result["document"]["type"], Document.Type.PROPOSAL)
        self.assertEqual(result["document"]["line_items"][0]["description"], "Design services")

    def test_proposal_revision_replaces_sections_and_pricing_but_remains_draft(self):
        proposal = self._proposal()
        attempt = self._prepare(
            "revise_proposal_draft",
            {
                "document_reference": proposal.number,
                "issue_date": None,
                "terms": "<p>Revised client terms.</p>",
                "notes": None,
                "sections": [
                    {
                        "heading": "Revised scope",
                        "body": "<p>Prepare updated architectural drawings.</p>",
                    }
                ],
                "line_items": [
                    {
                        "description": "Revised residential design services",
                        "rate": 5000,
                        "quantity": 1,
                        "tax_rate": 0,
                    }
                ],
            },
        )

        result = registry.execute_attempt(attempt=attempt)
        proposal.refresh_from_db()

        self.assertEqual(proposal.status, Document.Status.DRAFT)
        self.assertEqual(proposal.body_sections[0]["heading"], "Revised scope")
        self.assertEqual(proposal.line_items.get().description, "Revised residential design services")
        self.assertEqual(proposal.total, Decimal("5000.00"))
        self.assertIsNone(proposal.sent_at)
        self.assertIn("remains unissued", result["message"])

    def test_proposal_revision_rejects_stale_preview(self):
        proposal = self._proposal()
        attempt = self._prepare(
            "revise_proposal_draft",
            {
                "document_reference": proposal.number,
                "issue_date": None,
                "terms": "<p>Revised terms.</p>",
                "notes": None,
                "sections": None,
                "line_items": None,
            },
        )
        proposal.notes = "Changed in normal editor."
        proposal.save(update_fields=["notes", "updated_at"])

        with self.assertRaisesMessage(ValidationError, "changed after the AI preview"):
            registry.execute_attempt(attempt=attempt)

    def test_invoice_revision_preserves_amounts_time_links_and_original_time_text(self):
        invoice, entry = self._hourly_invoice()
        line = invoice.line_items.get()
        original_total = invoice.total
        original_quantity = line.quantity
        attempt = self._prepare(
            "revise_invoice_draft",
            {
                "document_reference": invoice.number,
                "issue_date": None,
                "due_date": "2026-09-01",
                "terms": "<p>Revised payment terms.</p>",
                "notes": None,
                "accept_payments": True,
                "line_descriptions": [
                    {
                        "line_id": line.pk,
                        "description": "Architectural roof-plan revisions",
                    }
                ],
            },
        )

        result = registry.execute_attempt(attempt=attempt)
        invoice.refresh_from_db()
        line.refresh_from_db()
        entry.refresh_from_db()

        self.assertEqual(invoice.status, Document.Status.DRAFT)
        self.assertEqual(invoice.total, original_total)
        self.assertEqual(line.quantity, original_quantity)
        self.assertEqual(line.description, "Architectural roof-plan revisions")
        self.assertEqual(entry.description, "roof revisions")
        self.assertEqual(entry.line_item_id, line.pk)
        self.assertEqual(entry.status, TimeEntry.Status.INVOICED)
        self.assertTrue(invoice.accept_payments)
        self.assertEqual(invoice.due_date, date(2026, 9, 1))
        self.assertIn("remains unissued", result["message"])

    def test_invoice_revision_rejects_line_from_another_document(self):
        invoice, _entry = self._hourly_invoice()
        other_project = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="2607002", name="Other Job"),
        )
        other_invoice = create_invoice(
            company=self.company,
            project=other_project,
            invoice_data={
                "invoice_kind": Document.InvoiceKind.FINAL,
                "number": "",
                "issue_date": date(2026, 7, 27),
                "due_date": date(2026, 8, 26),
                "terms": "",
                "notes": "",
                "accept_payments": False,
            },
        )
        other_line = save_line_item(
            document=other_invoice,
            line_data={
                "description": "Other work",
                "rate": Decimal("100.00"),
                "quantity": Decimal("1.00"),
                "tax_rate": Decimal("0"),
            },
        )

        with self.assertRaisesMessage(ValidationError, "do not belong"):
            self._prepare(
                "revise_invoice_draft",
                {
                    "document_reference": invoice.number,
                    "issue_date": None,
                    "due_date": None,
                    "terms": None,
                    "notes": "Changed note.",
                    "accept_payments": None,
                    "line_descriptions": [
                        {"line_id": other_line.pk, "description": "Wrong line"}
                    ],
                },
            )

    def test_cross_company_draft_cannot_be_revised(self):
        other_client = create_client(self.other_company, company_name="Hidden")
        other_project = create_project(
            company=self.other_company,
            client=other_client,
            project_data=project_data(number="HIDDEN-1", name="Hidden Project"),
        )
        hidden = create_proposal(
            company=self.other_company,
            project=other_project,
            proposal_data={
                "number": "",
                "issue_date": date(2026, 7, 27),
                "terms": "",
                "notes": "",
            },
        )

        with self.assertRaisesMessage(ValidationError, "No editable company draft"):
            self._prepare(
                "revise_proposal_draft",
                {
                    "document_reference": hidden.number,
                    "issue_date": None,
                    "terms": "<p>Changed.</p>",
                    "notes": None,
                    "sections": None,
                    "line_items": None,
                },
            )

    def test_revision_action_creates_metadata_evidence_for_manual_draft(self):
        proposal = self._proposal()
        attempt = self._prepare(
            "revise_proposal_draft",
            {
                "document_reference": proposal.number,
                "issue_date": None,
                "terms": "<p>Revised terms.</p>",
                "notes": None,
                "sections": None,
                "line_items": None,
            },
        )
        result = registry.execute_attempt(attempt=attempt)
        review = track_completed_draft_action(action_attempt=attempt, result=result)

        self.assertIsNotNone(review)
        self.assertEqual(review.document_id, proposal.pk)
        self.assertEqual(review.revision_count, 1)
        self.assertIn("terms", review.changed_fields)
        self.assertNotIn("Revised terms", str(review.latest_snapshot))
        self.assertTrue(AIDocumentDraftReview.objects.filter(pk=review.pk).exists())

    def test_revision_tools_require_explicit_current_message_intent(self):
        self.assertTrue(
            write_intent_authorized(
                prompt="Revise proposal P-26-0001 to improve the scope language.",
                tool_name="revise_proposal_draft",
            )
        )
        self.assertTrue(
            write_intent_authorized(
                prompt="Update invoice I-26-0001 descriptions.",
                tool_name="revise_invoice_draft",
            )
        )
        self.assertFalse(
            write_intent_authorized(
                prompt="What is on invoice I-26-0001?",
                tool_name="revise_invoice_draft",
            )
        )
