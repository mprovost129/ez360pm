from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Company, User
from clients.tests.test_clients import create_client
from documents.models import Document, InvoiceCredit, Payment
from documents.pdf import build_proposal_pdf
from documents.proposal_services import (
    accept_proposal,
    apply_retainer_credit,
    available_retainer_credit,
    create_proposal,
    create_retainer_invoice,
    decline_proposal,
    move_proposal_section,
    remove_retainer_credit,
    save_proposal_section,
    withdraw_proposal,
)
from documents.services import (
    create_invoice,
    issue_document,
    record_payment,
    save_line_item,
)
from projects.models import Project
from projects.services import create_project
from projects.tests.test_projects import project_data
from projects.workflow import complete_paid_project, start_without_retainer

from .test_billing import invoice_data


class ProposalWorkflowTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.project = create_project(
            company=self.company,
            client=create_client(self.company),
            project_data=project_data(number="PROPOSAL-1"),
        )
        self.client.force_login(self.user)

    def make_proposal(self, *, amount="1000.00"):
        proposal = create_proposal(
            company=self.company,
            project=self.project,
            proposal_data={
                "number": "",
                "issue_date": date(2026, 7, 21),
                "terms": "<p>Due on acceptance.</p>",
                "notes": "Internal secret",
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
        proposal.refresh_from_db()
        return proposal

    def accept(self, proposal):
        issue_document(document=proposal)
        proposal.refresh_from_db()
        return accept_proposal(
            proposal=proposal,
            signer_name="Alex Smith",
            signer_email="ALEX@example.com",
            ip_address="203.0.113.8",
        )

    def make_retainer(self, proposal, *, value="50.00", mode="percentage"):
        return create_retainer_invoice(
            proposal=proposal,
            mode=mode,
            value=Decimal(value),
            invoice_data=invoice_data(
                invoice_kind=Document.InvoiceKind.RETAINER,
                number="",
            ),
        )

    def pay(self, invoice):
        issue_document(document=invoice)
        invoice.refresh_from_db()
        return record_payment(
            invoice=invoice,
            payment_data={
                "amount": invoice.total,
                "method": Payment.Method.CHECK,
                "received_at": date(2026, 7, 22),
                "reference": "retainer",
            },
        )

    def test_proposal_number_and_rich_text_are_sanitized(self):
        proposal = create_proposal(
            company=self.company,
            project=self.project,
            proposal_data={
                "number": "",
                "issue_date": date(2026, 7, 21),
                "terms": '<p><strong>Safe</strong><script>alert("x")</script></p>',
                "notes": '<a href="javascript:alert(1)">unsafe link</a>',
            },
        )
        save_proposal_section(
            proposal=proposal,
            heading="Scope<script>x</script>",
            body='<p>Drawings <em>included</em>.</p><img src="x">',
        )
        proposal.refresh_from_db()

        self.assertEqual(proposal.number, "P-26-0001")
        self.assertNotIn("script", proposal.terms)
        self.assertNotIn("javascript", proposal.notes)
        self.assertEqual(proposal.body_sections[0]["heading"], "Scopex")
        self.assertNotIn("img", proposal.body_sections[0]["body"])
        self.assertIn("<em>included</em>", proposal.body_sections[0]["body"])

    def test_public_acceptance_snapshots_agreement_and_approves_project(self):
        proposal = self.make_proposal()
        issue_document(document=proposal)
        proposal.refresh_from_db()

        view_response = self.client.get(
            reverse("public-documents:view", args=(proposal.public_token,))
        )
        response = self.client.post(
            reverse("public-documents:accept", args=(proposal.public_token,)),
            {"signer_name": "Alex Smith", "signer_email": "ALEX@example.com"},
            REMOTE_ADDR="203.0.113.8",
        )

        self.assertEqual(view_response.status_code, 200)
        self.assertNotContains(view_response, "Internal secret")
        self.assertRedirects(
            response,
            reverse("public-documents:view", args=(proposal.public_token,)),
        )
        proposal.refresh_from_db()
        self.project.refresh_from_db()
        self.assertEqual(proposal.status, Document.Status.ACCEPTED)
        self.assertEqual(proposal.accepted_total, Decimal("1000.00"))
        self.assertEqual(proposal.accepted_by_email, "alex@example.com")
        self.assertEqual(proposal.acceptance_ip, "203.0.113.8")
        self.assertEqual(self.project.status, Project.Status.APPROVED)

        repeated = accept_proposal(
            proposal=proposal,
            signer_name="Someone Else",
            signer_email="else@example.com",
            ip_address="198.51.100.2",
        )
        self.assertEqual(repeated.accepted_by_name, "Alex Smith")

    def test_decline_and_withdraw_only_close_open_proposals(self):
        declined = self.make_proposal()
        issue_document(document=declined)
        declined.refresh_from_db()
        decline_proposal(proposal=declined)
        declined.refresh_from_db()
        self.assertEqual(declined.status, Document.Status.DECLINED)

        withdrawn = self.make_proposal()
        issue_document(document=withdrawn)
        withdrawn.refresh_from_db()
        withdraw_proposal(proposal=withdrawn)
        withdrawn.refresh_from_db()
        self.assertEqual(withdrawn.status, Document.Status.WITHDRAWN)
        with self.assertRaises(ValidationError):
            accept_proposal(
                proposal=withdrawn,
                signer_name="Alex",
                signer_email="alex@example.com",
                ip_address=None,
            )

    def test_proposal_pdf_and_authenticated_workflow_views(self):
        proposal = self.make_proposal()
        save_proposal_section(
            proposal=proposal,
            heading="Scope",
            body="<p>Design work.</p><ul><li>Plans</li><li>Details</li></ul>",
        )

        detail = self.client.get(reverse("proposals:detail", args=(proposal.pk,)))
        pdf = build_proposal_pdf(Document.objects.get(pk=proposal.pk))

        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Scope")
        self.assertContains(detail, "Internal secret")
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)

    def test_other_company_proposal_is_not_visible_to_authenticated_user(self):
        other_company = Company.objects.create(name="Other Studio")
        other_project = create_project(
            company=other_company,
            client=create_client(other_company, company_name="Other Client"),
            project_data=project_data(number="OTHER-PROP"),
        )
        other = create_proposal(
            company=other_company,
            project=other_project,
            proposal_data={"number": "OTHER", "issue_date": date(2026, 7, 21)},
        )

        response = self.client.get(reverse("proposals:detail", args=(other.pk,)))

        self.assertEqual(response.status_code, 404)

    def test_authenticated_authoring_flow_creates_sections_prices_and_issues(self):
        response = self.client.post(
            reverse("proposals:create"),
            {
                "project": self.project.pk,
                "number": "",
                "issue_date": "2026-07-21",
                "terms": "<p>Valid for 30 days.</p>",
                "notes": "Internal",
            },
        )
        proposal = Document.objects.get(
            company=self.company,
            doc_type=Document.Type.PROPOSAL,
        )
        self.assertRedirects(response, reverse("proposals:detail", args=(proposal.pk,)))

        section_response = self.client.post(
            reverse("proposals:section-create", args=(proposal.pk,)),
            {"heading": "Scope", "body": "<p>Design services.</p>"},
        )
        line_response = self.client.post(
            reverse("proposals:line-create", args=(proposal.pk,)),
            {
                "description": "Design services",
                "rate": "1000.00",
                "quantity": "1.00",
                "tax_rate": "0",
            },
        )
        issue_response = self.client.post(reverse("proposals:issue", args=(proposal.pk,)))

        self.assertRedirects(
            section_response,
            f"{reverse('proposals:detail', args=(proposal.pk,))}#document-preview",
        )
        self.assertRedirects(
            line_response,
            f"{reverse('proposals:detail', args=(proposal.pk,))}#document-preview",
        )
        self.assertRedirects(issue_response, reverse("proposals:detail", args=(proposal.pk,)))
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Document.Status.SENT)
        self.assertEqual(proposal.body_sections[0]["heading"], "Scope")
        self.assertEqual(proposal.total, Decimal("1000.00"))

    def test_estimate_authoring_locks_project_and_guides_scope(self):
        self.company.default_proposal_terms = "Valid for 45 days."
        self.company.save(update_fields=["default_proposal_terms"])
        create_response = self.client.get(
            reverse("proposals:create"),
            {"project": self.project.pk},
        )

        form = create_response.context["form"]
        self.assertTrue(form.fields["project"].disabled)
        self.assertEqual(form.fields["project"].initial, self.project)
        self.assertEqual(form.fields["notes"].label, "Internal notes")
        self.assertEqual(form.fields["terms"].initial, "Valid for 45 days.")
        self.assertContains(create_response, "New estimate / proposal")

        proposal = self.make_proposal()
        detail = self.client.get(reverse("proposals:detail", args=(proposal.pk,)))
        section = self.client.get(
            reverse("proposals:section-create", args=(proposal.pk,))
        )
        self.assertContains(detail, "Estimate / Draft proposal")
        self.assertContains(detail, "Draft readiness")
        self.assertContains(detail, "Estimate / proposal settings")
        self.assertContains(detail, "Save details and review")
        self.assertContains(detail, "Save scope section and review")
        self.assertEqual(detail.context["details_form"].instance, proposal)
        self.assertEqual(
            detail.context["section_form"].initial["heading"],
            "Scope of work",
        )
        self.assertContains(detail, "Line amount")
        self.assertEqual(section.context["form"].initial["heading"], "Scope of work")

    def test_draft_proposal_details_save_back_to_live_preview(self):
        proposal = self.make_proposal()

        response = self.client.post(
            reverse("proposals:update", args=(proposal.pk,)),
            {
                "number": proposal.number,
                "issue_date": proposal.issue_date.isoformat(),
                "terms": "<p>Valid for 60 days.</p>",
                "notes": "<p>Confirm structural allowance.</p>",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('proposals:detail', args=(proposal.pk,))}"
            "#document-preview",
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.terms, "<p>Valid for 60 days.</p>")
        self.assertEqual(proposal.notes, "<p>Confirm structural allowance.</p>")

    def test_proposal_list_searches_project_number(self):
        proposal = self.make_proposal()

        response = self.client.get(
            reverse("proposals:list"),
            {"q": self.project.number},
        )

        self.assertEqual(list(response.context["proposals"]), [proposal])

    def test_proposal_status_filters_preserve_project_and_search_context(self):
        proposal = self.make_proposal()

        response = self.client.get(
            reverse("proposals:list"),
            {
                "project": self.project.pk,
                "q": self.project.number,
                "status": Document.Status.DRAFT,
            },
        )

        self.assertEqual(list(response.context["proposals"]), [proposal])
        self.assertContains(
            response,
            f'href="{reverse("proposals:list")}?project={self.project.pk}'
            f'&amp;q={self.project.number}&amp;status=accepted"',
        )
        self.assertContains(
            response,
            f'href="{reverse("proposals:list")}?project={self.project.pk}'
            '&amp;status=draft">Clear search</a>',
        )
        self.assertContains(
            response,
            'class="is-active" aria-current="page">Estimates / Drafts</a>',
        )

    def test_proposal_list_includes_withdrawn_and_ignores_invoice_only_statuses(self):
        withdrawn = self.make_proposal()
        issue_document(document=withdrawn)
        withdrawn.refresh_from_db()
        withdraw_proposal(proposal=withdrawn)
        draft = self.make_proposal()

        withdrawn_response = self.client.get(
            reverse("proposals:list"),
            {"status": Document.Status.WITHDRAWN},
        )
        invalid_response = self.client.get(
            reverse("proposals:list"),
            {"status": Document.Status.PAID},
        )

        self.assertEqual(list(withdrawn_response.context["proposals"]), [withdrawn])
        self.assertContains(
            withdrawn_response,
            'class="is-active" aria-current="page">Withdrawn</a>',
        )
        self.assertCountEqual(
            invalid_response.context["proposals"],
            [withdrawn, draft],
        )

    def test_draft_proposal_sections_can_be_reordered(self):
        proposal = self.make_proposal()
        save_proposal_section(proposal=proposal, heading="First", body="One")
        save_proposal_section(proposal=proposal, heading="Second", body="Two")

        move_proposal_section(proposal=proposal, index=1, direction="up")

        proposal.refresh_from_db()
        self.assertEqual(
            [section["heading"] for section in proposal.body_sections],
            ["Second", "First"],
        )

    def test_accepted_proposal_can_be_duplicated_as_clean_draft(self):
        proposal = self.make_proposal()
        save_proposal_section(
            proposal=proposal,
            heading="Scope",
            body="<p>Original scope.</p>",
        )
        proposal = self.accept(proposal)

        response = self.client.post(
            reverse("proposals:duplicate", args=(proposal.pk,))
        )

        duplicate = Document.objects.filter(
            company=self.company,
            doc_type=Document.Type.PROPOSAL,
        ).exclude(pk=proposal.pk).get()
        self.assertRedirects(
            response,
            reverse("proposals:detail", args=(duplicate.pk,)),
        )
        self.assertEqual(duplicate.status, Document.Status.DRAFT)
        self.assertNotEqual(duplicate.number, proposal.number)
        self.assertNotEqual(duplicate.public_token, proposal.public_token)
        self.assertEqual(duplicate.body_sections, proposal.body_sections)
        self.assertEqual(duplicate.total, proposal.total)
        self.assertIsNone(duplicate.responded_at)
        self.assertEqual(duplicate.accepted_by_name, "")
        self.assertFalse(duplicate.deliveries.exists())

    def test_issue_and_email_continues_to_delivery_form(self):
        proposal = self.make_proposal()

        response = self.client.post(
            reverse("proposals:issue", args=(proposal.pk,)),
            {"send_after_issue": "1"},
        )

        self.assertRedirects(
            response,
            reverse("proposals:send", args=(proposal.pk,)),
            fetch_redirect_response=False,
        )

    def test_retainer_percentage_and_fixed_amount_use_accepted_snapshot(self):
        proposal = self.accept(self.make_proposal())

        percentage = self.make_retainer(proposal, value="25.00")
        fixed = self.make_retainer(proposal, value="300.00", mode="amount")

        self.assertEqual(percentage.total, Decimal("250.00"))
        self.assertEqual(fixed.total, Decimal("300.00"))
        self.assertEqual(percentage.source_proposal, proposal)
        with self.assertRaises(ValidationError):
            self.make_retainer(proposal, value="1000.01", mode="amount")
        with self.assertRaises(ValidationError):
            self.make_retainer(proposal, value="500.00", mode="amount")

    def test_paid_retainer_activates_approved_project(self):
        proposal = self.accept(self.make_proposal())
        retainer = self.make_retainer(proposal)

        self.pay(retainer)

        self.project.refresh_from_db()
        self.assertEqual(self.project.status, Project.Status.ACTIVE)

    def test_retainer_create_view_links_invoice_to_accepted_proposal(self):
        proposal = self.accept(self.make_proposal())

        response = self.client.post(
            reverse("proposals:retainer-create", args=(proposal.pk,)),
            {
                "mode": "percentage",
                "value": "30.00",
                "number": "",
                "issue_date": "2026-07-21",
                "due_date": "2026-08-20",
                "terms": "Due before work begins.",
                "notes": "",
            },
        )

        retainer = Document.objects.get(source_proposal=proposal)
        self.assertRedirects(
            response,
            reverse("documents:invoice-detail", args=(retainer.pk,)),
        )
        self.assertEqual(retainer.invoice_kind, Document.InvoiceKind.RETAINER)
        self.assertEqual(retainer.total, Decimal("300.00"))

    def test_explicit_start_without_retainer_and_retainer_guard(self):
        self.accept(self.make_proposal())
        start_without_retainer(project=self.project)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, Project.Status.ACTIVE)

        guarded_project = create_project(
            company=self.company,
            client=self.project.client,
            project_data=project_data(number="PROPOSAL-2"),
        )
        guarded_proposal = create_proposal(
            company=self.company,
            project=guarded_project,
            proposal_data={"number": "P-GUARD", "issue_date": date(2026, 7, 21)},
        )
        save_line_item(
            document=guarded_proposal,
            line_data={
                "description": "Services",
                "rate": Decimal("500.00"),
                "quantity": Decimal("1"),
                "tax_rate": Decimal("0"),
            },
        )
        guarded_proposal = self.accept(guarded_proposal)
        self.make_retainer(guarded_proposal)
        with self.assertRaises(ValidationError):
            start_without_retainer(project=guarded_project)

    def test_credit_application_is_capped_and_reversible(self):
        proposal = self.accept(self.make_proposal())
        retainer = self.make_retainer(proposal, value="400.00", mode="amount")
        self.pay(retainer)
        final = create_invoice(
            company=self.company,
            project=self.project,
            invoice_data=invoice_data(),
        )
        save_line_item(
            document=final,
            line_data={
                "description": "Final services",
                "rate": Decimal("1000.00"),
                "quantity": Decimal("1"),
                "tax_rate": Decimal("0"),
            },
        )
        final.refresh_from_db()

        credit = apply_retainer_credit(
            source_invoice=retainer,
            destination_invoice=final,
            amount=Decimal("400.00"),
        )
        final.refresh_from_db()
        self.assertEqual(final.credit_total, Decimal("400.00"))
        self.assertEqual(final.total, Decimal("600.00"))
        self.assertEqual(available_retainer_credit(retainer), Decimal("0.00"))
        with self.assertRaises(ValidationError):
            apply_retainer_credit(
                source_invoice=retainer,
                destination_invoice=final,
                amount=Decimal("0.01"),
            )

        remove_retainer_credit(credit=credit)
        final.refresh_from_db()
        self.assertEqual(final.credit_total, Decimal("0.00"))
        self.assertEqual(final.total, Decimal("1000.00"))
        self.assertFalse(InvoiceCredit.objects.exists())

    def test_credit_and_project_transition_actions_are_available_in_the_ui(self):
        proposal = self.accept(self.make_proposal())
        start_response = self.client.post(
            reverse("projects:start-without-retainer", args=(self.project.pk,))
        )
        self.assertRedirects(start_response, reverse("projects:detail", args=(self.project.pk,)))

        retainer = self.make_retainer(proposal, value="200.00", mode="amount")
        self.pay(retainer)
        final = create_invoice(
            company=self.company,
            project=self.project,
            invoice_data=invoice_data(),
        )
        save_line_item(
            document=final,
            line_data={
                "description": "Final services",
                "rate": Decimal("500.00"),
                "quantity": Decimal("1"),
                "tax_rate": Decimal("0"),
            },
        )

        response = self.client.post(
            reverse("documents:credit-create", args=(final.pk,)),
            {"source_invoice": retainer.pk, "amount": "200.00"},
        )

        self.assertRedirects(
            response,
            reverse("documents:invoice-detail", args=(final.pk,)),
        )
        final.refresh_from_db()
        self.assertEqual(final.total, Decimal("300.00"))

    def test_final_payment_requires_explicit_project_completion(self):
        self.project.status = Project.Status.ACTIVE
        self.project.save(update_fields=["status"])
        final = create_invoice(
            company=self.company,
            project=self.project,
            invoice_data=invoice_data(),
        )
        save_line_item(
            document=final,
            line_data={
                "description": "Final services",
                "rate": Decimal("100.00"),
                "quantity": Decimal("1"),
                "tax_rate": Decimal("0"),
            },
        )
        self.pay(final)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, Project.Status.ACTIVE)

        complete_paid_project(project=self.project)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, Project.Status.COMPLETED)

    def test_public_draft_and_invoice_accept_endpoints_do_not_accept(self):
        proposal = self.make_proposal()
        draft_response = self.client.get(
            reverse("public-documents:view", args=(proposal.public_token,))
        )
        final = create_invoice(
            company=self.company,
            project=self.project,
            invoice_data=invoice_data(),
        )
        save_line_item(
            document=final,
            line_data={
                "description": "Services",
                "rate": Decimal("100.00"),
                "quantity": Decimal("1"),
                "tax_rate": Decimal("0"),
            },
        )
        issue_document(document=final)
        invoice_response = self.client.post(
            reverse("public-documents:accept", args=(final.public_token,)),
            {"signer_name": "Alex", "signer_email": "alex@example.com"},
        )

        self.assertEqual(draft_response.status_code, 404)
        self.assertRedirects(
            invoice_response,
            reverse("public-documents:view", args=(final.public_token,)),
        )
        final.refresh_from_db()
        self.assertNotEqual(final.status, Document.Status.ACCEPTED)
