from datetime import UTC, date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from accounts.models import Company, User
from assistant.models import AIInteraction
from assistant.registry import ActionContext, registry
from clients.tests.test_clients import create_client
from documents.models import Document, InvoiceCredit, Payment
from documents.proposal_services import (
    accept_proposal,
    create_proposal,
    create_retainer_invoice,
)
from documents.services import issue_document, record_payment, save_line_item
from projects.models import Project, TimeEntry
from projects.services import create_project
from projects.tests.test_projects import project_data
from projects.time_services import save_manual_entry


@override_settings(AI_ASSISTANT_ENABLED=True)
class AssistantPhaseFourDraftTests(TestCase):
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
        self.client_record = create_client(self.company, company_name="Smith Household")
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
            prompt_summary="phase four",
        )
        self.context = ActionContext(user=self.user, interaction=self.interaction)

    def _prepare(self, name, arguments):
        return registry.invoke(
            context=self.context,
            name=name,
            arguments=arguments,
        ).pending_action

    def _proposal_arguments(self, **overrides):
        data = {
            "project_reference": self.project.number,
            "issue_date": "2026-07-27",
            "terms": None,
            "notes": "Internal draft note.",
            "sections": [
                {
                    "heading": "Scope of work",
                    "body": "<p>Prepare architectural drawings for the addition.</p>",
                }
            ],
            "line_items": [
                {
                    "description": "Residential design services",
                    "rate": 4500,
                    "quantity": 1,
                    "tax_rate": 0,
                }
            ],
        }
        data.update(overrides)
        return data

    def _accepted_proposal(self, amount="4500.00"):
        proposal = create_proposal(
            company=self.company,
            project=self.project,
            proposal_data={
                "number": "",
                "issue_date": date(2026, 7, 20),
                "terms": "<p>Accepted terms.</p>",
                "notes": "",
            },
        )
        save_line_item(
            document=proposal,
            line_data={
                "description": "Design services",
                "rate": Decimal(amount),
                "quantity": Decimal("1.00"),
                "tax_rate": Decimal("0"),
            },
        )
        issue_document(document=proposal)
        proposal.refresh_from_db()
        return accept_proposal(
            proposal=proposal,
            signer_name="Alex Smith",
            signer_email="alex@example.com",
            ip_address="203.0.113.10",
        )

    def test_document_context_returns_only_company_scoped_draft_inputs(self):
        other_client = create_client(self.other_company, company_name="Hidden")
        hidden = create_project(
            company=self.other_company,
            client=other_client,
            project_data=project_data(number="HIDDEN-1", name="Hidden Project"),
        )

        result = registry.invoke(
            context=self.context,
            name="get_document_draft_context",
            arguments={"project_reference": self.project.number},
        ).data

        self.assertEqual(result["project"]["number"], self.project.number)
        self.assertNotEqual(result["project"]["number"], hidden.number)
        self.assertEqual(result["company_defaults"]["invoice_due_days"], 30)

    def test_proposal_draft_requires_confirmation_and_opens_normal_editor(self):
        attempt = self._prepare("prepare_proposal_draft", self._proposal_arguments())

        self.assertFalse(Document.objects.exists())
        self.assertIn("draft only", " ".join(attempt.preview["details"]).lower())

        result = registry.execute_attempt(attempt=attempt)

        proposal = Document.objects.get(doc_type=Document.Type.PROPOSAL)
        self.assertEqual(proposal.status, Document.Status.DRAFT)
        self.assertEqual(proposal.body_sections[0]["heading"], "Scope of work")
        self.assertEqual(proposal.total, Decimal("4500.00"))
        self.assertIn(str(proposal.pk), result["redirect_url"])
        self.assertIsNone(proposal.sent_at)

    def test_proposal_draft_sanitizes_ai_authored_content(self):
        attempt = self._prepare(
            "prepare_proposal_draft",
            self._proposal_arguments(
                sections=[
                    {
                        "heading": "Scope<script>x</script>",
                        "body": '<p>Safe</p><img src="x"><script>bad()</script>',
                    }
                ]
            ),
        )

        registry.execute_attempt(attempt=attempt)
        proposal = Document.objects.get(doc_type=Document.Type.PROPOSAL)

        self.assertNotIn("script", proposal.body_sections[0]["heading"].lower())
        self.assertNotIn("img", proposal.body_sections[0]["body"].lower())

    def test_retainer_invoice_draft_uses_accepted_proposal_service(self):
        proposal = self._accepted_proposal()
        attempt = self._prepare(
            "prepare_retainer_invoice_draft",
            {
                "proposal_reference": proposal.number,
                "mode": "percentage",
                "value": 25,
                "issue_date": "2026-07-27",
                "due_date": "2026-08-26",
                "terms": None,
                "notes": None,
                "accept_payments": None,
            },
        )

        result = registry.execute_attempt(attempt=attempt)

        invoice = Document.objects.get(
            doc_type=Document.Type.INVOICE,
            invoice_kind=Document.InvoiceKind.RETAINER,
        )
        self.assertEqual(invoice.status, Document.Status.DRAFT)
        self.assertEqual(invoice.source_proposal, proposal)
        self.assertEqual(invoice.total, Decimal("4500.00"))
        self.assertEqual(invoice.deposit_amount, Decimal("1125.00"))
        self.assertEqual(invoice.outstanding_balance, Decimal("1125.00"))
        self.assertTrue(invoice.accept_payments)
        self.assertIn(str(invoice.pk), result["redirect_url"])

    def test_hourly_final_invoice_attaches_time_and_uses_ai_descriptions(self):
        first = save_manual_entry(
            user=self.user,
            project=self.project,
            entry_data={
                "start_time": datetime(2026, 7, 25, 13, 0, tzinfo=UTC),
                "end_time": datetime(2026, 7, 25, 15, 0, tzinfo=UTC),
                "description": "floor changes",
                "billable": True,
            },
        )
        second = save_manual_entry(
            user=self.user,
            project=self.project,
            entry_data={
                "start_time": datetime(2026, 7, 26, 13, 0, tzinfo=UTC),
                "end_time": datetime(2026, 7, 26, 14, 30, tzinfo=UTC),
                "description": "roof changes",
                "billable": True,
            },
        )
        ids = [first.pk, second.pk]
        attempt = self._prepare(
            "prepare_final_invoice_draft",
            {
                "project_reference": self.project.number,
                "issue_date": "2026-07-27",
                "due_date": "2026-08-26",
                "terms": None,
                "notes": None,
                "accept_payments": None,
                "include_time": True,
                "time_entry_ids": ids,
                "grouping": "combined",
                "description_groups": [
                    {
                        "time_entry_ids": ids,
                        "description": "Architectural plan revisions to floor and roof layouts",
                    }
                ],
                "fixed_fee_description": None,
                "apply_retainer_credit": False,
                "retainer_invoice_reference": None,
                "credit_amount": None,
            },
        )

        registry.execute_attempt(attempt=attempt)

        invoice = Document.objects.get(doc_type=Document.Type.INVOICE)
        line = invoice.line_items.get()
        self.assertEqual(invoice.status, Document.Status.DRAFT)
        self.assertEqual(line.description, "Architectural plan revisions to floor and roof layouts")
        self.assertEqual(line.quantity, Decimal("3.50"))
        self.assertEqual(invoice.total, Decimal("612.50"))
        self.assertEqual(
            TimeEntry.objects.filter(status=TimeEntry.Status.INVOICED).count(),
            2,
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.description, "floor changes")
        self.assertEqual(second.description, "roof changes")

    def test_fixed_fee_final_invoice_applies_only_available_paid_retainer(self):
        flat_project = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(
                number="2607002",
                name="Flat Fee Addition",
                billing_type=Project.BillingType.FLAT_FEE,
                hourly_rate=None,
                fixed_fee=Decimal("5000.00"),
            ),
        )
        self.project = flat_project
        proposal = self._accepted_proposal(amount="5000.00")
        retainer = create_retainer_invoice(
            proposal=proposal,
            mode="amount",
            value=Decimal("1500.00"),
            invoice_data={
                "number": "",
                "issue_date": date(2026, 7, 22),
                "due_date": date(2026, 8, 21),
                "terms": "",
                "notes": "",
                "accept_payments": False,
            },
        )
        issue_document(document=retainer)
        retainer.refresh_from_db()
        record_payment(
            invoice=retainer,
            payment_data={
                "amount": retainer.amount_due,
                "method": Payment.Method.CHECK,
                "received_at": date(2026, 7, 23),
                "reference": "1001",
            },
        )
        retainer.refresh_from_db()
        attempt = self._prepare(
            "prepare_final_invoice_draft",
            {
                "project_reference": flat_project.number,
                "issue_date": "2026-07-27",
                "due_date": "2026-08-26",
                "terms": None,
                "notes": None,
                "accept_payments": False,
                "include_time": False,
                "time_entry_ids": [],
                "grouping": "combined",
                "description_groups": [],
                "fixed_fee_description": "Residential design services — final balance",
                "apply_retainer_credit": True,
                "retainer_invoice_reference": retainer.number,
                "credit_amount": None,
            },
        )

        registry.execute_attempt(attempt=attempt)

        final = Document.objects.get(
            project=flat_project,
            invoice_kind=Document.InvoiceKind.FINAL,
        )
        self.assertEqual(final.subtotal, Decimal("5000.00"))
        self.assertEqual(final.credit_total, Decimal("1500.00"))
        self.assertEqual(final.total, Decimal("3500.00"))
        self.assertEqual(final.line_items.get().description, "Residential design services — final balance")
        self.assertTrue(
            InvoiceCredit.objects.filter(
                source_invoice=retainer,
                destination_invoice=final,
                amount=Decimal("1500.00"),
            ).exists()
        )

    def test_final_invoice_can_apply_a_specific_partial_retainer_credit(self):
        flat_project = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(
                number="2607003",
                name="Partial Credit Addition",
                billing_type=Project.BillingType.FLAT_FEE,
                hourly_rate=None,
                fixed_fee=Decimal("5000.00"),
            ),
        )
        self.project = flat_project
        proposal = self._accepted_proposal(amount="5000.00")
        retainer = create_retainer_invoice(
            proposal=proposal,
            mode="amount",
            value=Decimal("1500.00"),
            invoice_data={
                "number": "",
                "issue_date": date(2026, 7, 22),
                "due_date": date(2026, 8, 21),
                "terms": "",
                "notes": "",
                "accept_payments": False,
            },
        )
        issue_document(document=retainer)
        retainer.refresh_from_db()
        record_payment(
            invoice=retainer,
            payment_data={
                "amount": retainer.amount_due,
                "method": Payment.Method.CHECK,
                "received_at": date(2026, 7, 23),
                "reference": "1002",
            },
        )
        retainer.refresh_from_db()
        attempt = self._prepare(
            "prepare_final_invoice_draft",
            {
                "project_reference": flat_project.number,
                "issue_date": "2026-07-27",
                "due_date": "2026-08-26",
                "terms": None,
                "notes": None,
                "accept_payments": False,
                "include_time": False,
                "time_entry_ids": [],
                "grouping": "combined",
                "description_groups": [],
                "fixed_fee_description": "Residential design services — final balance",
                "apply_retainer_credit": True,
                "retainer_invoice_reference": retainer.number,
                "credit_amount": 500,
            },
        )

        registry.execute_attempt(attempt=attempt)

        final = Document.objects.get(
            project=flat_project,
            invoice_kind=Document.InvoiceKind.FINAL,
        )
        self.assertEqual(final.credit_total, Decimal("500.00"))
        self.assertEqual(final.total, Decimal("4500.00"))
        self.assertTrue(
            InvoiceCredit.objects.filter(
                source_invoice=retainer,
                destination_invoice=final,
                amount=Decimal("500.00"),
            ).exists()
        )

    def test_repeated_identical_draft_preparation_reuses_pending_attempt(self):
        arguments = self._proposal_arguments()

        first = self._prepare("prepare_proposal_draft", arguments)
        second = self._prepare("prepare_proposal_draft", arguments)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Document.objects.count(), 0)

    def test_cross_company_project_cannot_create_document_draft(self):
        other_client = create_client(self.other_company, company_name="Hidden")
        other_project = create_project(
            company=self.other_company,
            client=other_client,
            project_data=project_data(number="HIDDEN-1"),
        )

        with self.assertRaisesMessage(ValidationError, "No project matched"):
            self._prepare(
                "prepare_proposal_draft",
                self._proposal_arguments(project_reference=other_project.number),
            )

    def test_selected_time_is_rechecked_at_execution(self):
        entry = save_manual_entry(
            user=self.user,
            project=self.project,
            entry_data={
                "start_time": datetime(2026, 7, 25, 13, 0, tzinfo=UTC),
                "end_time": datetime(2026, 7, 25, 14, 0, tzinfo=UTC),
                "description": "drafting",
                "billable": True,
            },
        )
        attempt = self._prepare(
            "prepare_final_invoice_draft",
            {
                "project_reference": self.project.number,
                "issue_date": None,
                "due_date": None,
                "terms": None,
                "notes": None,
                "accept_payments": None,
                "include_time": True,
                "time_entry_ids": [entry.pk],
                "grouping": "individual",
                "description_groups": [],
                "fixed_fee_description": None,
                "apply_retainer_credit": False,
                "retainer_invoice_reference": None,
                "credit_amount": None,
            },
        )
        entry.billable = False
        entry.save(update_fields=["billable"])

        with self.assertRaisesMessage(ValidationError, "no longer billable"):
            registry.execute_attempt(attempt=attempt)
        self.assertFalse(Document.objects.filter(doc_type=Document.Type.INVOICE).exists())
