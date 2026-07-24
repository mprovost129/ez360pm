from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Company, User
from clients.tests.test_clients import create_client
from documents.models import Document
from projects.models import Project
from projects.services import allocate_project_number, create_project
from projects.time_services import start_timer


def project_data(**overrides):
    data = {
        "number": "",
        "name": "Kitchen addition",
        "description": "Design and permitting.",
        "address_1": "100 Main Street",
        "address_2": "",
        "city": "Richmond",
        "state": "VA",
        "postal_code": "23220",
        "municipality": "City of Richmond",
        "parcel_id": "P-100",
        "billing_type": Project.BillingType.HOURLY,
        "hourly_rate": Decimal("175.00"),
        "fixed_fee": None,
        "estimated_hours": Decimal("40.00"),
    }
    data.update(overrides)
    return data


class ProjectServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.client_record = create_client(self.company)

    def test_number_allocator_uses_monthly_sequence(self):
        first = allocate_project_number(company=self.company, on_date=date(2026, 7, 1))
        second = allocate_project_number(company=self.company, on_date=date(2026, 7, 31))
        next_month = allocate_project_number(company=self.company, on_date=date(2026, 8, 1))

        self.assertEqual(first, "2607001")
        self.assertEqual(second, "2607002")
        self.assertEqual(next_month, "2608001")

    def test_create_project_generates_number_and_lead_status(self):
        project = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(),
        )

        self.assertRegex(project.number, r"^\d{4}\d{3}$")
        self.assertEqual(project.status, Project.Status.LEAD)

    def test_cross_company_client_is_rejected(self):
        other = Company.objects.create(name="Other Company")
        other_client = create_client(other)

        with self.assertRaises(ValidationError):
            create_project(
                company=self.company,
                client=other_client,
                project_data=project_data(),
            )

    def test_billing_fields_must_match_type(self):
        with self.assertRaises(ValidationError):
            create_project(
                company=self.company,
                client=self.client_record,
                project_data=project_data(hourly_rate=None),
            )


class ProjectViewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Provost Home Design",
            default_hourly_rate=Decimal("175.00"),
        )
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.client_record = create_client(self.company)
        self.client.force_login(self.user)

    def test_project_create_flow_generates_editable_number(self):
        data = project_data()
        data["client"] = self.client_record.pk
        data["number"] = ""
        data["fixed_fee"] = ""

        response = self.client.post(reverse("projects:create"), data)

        project = Project.objects.get(company=self.company)
        self.assertRedirects(response, reverse("projects:detail", args=(project.pk,)))
        self.assertRegex(project.number, r"^\d{7}$")

    def test_project_create_flow_allows_blank_postal_code(self):
        data = project_data(postal_code="")
        data["client"] = self.client_record.pk
        data["fixed_fee"] = ""

        response = self.client.post(reverse("projects:create"), data)

        project = Project.objects.get(company=self.company)
        self.assertRedirects(response, reverse("projects:detail", args=(project.pk,)))
        self.assertEqual(project.postal_code, "")

    def test_fixed_fee_clears_default_hourly_rate_and_selects_flat_fee(self):
        data = project_data(
            billing_type=Project.BillingType.HOURLY,
            hourly_rate=self.company.default_hourly_rate,
            fixed_fee=Decimal("2500.00"),
        )
        data["client"] = self.client_record.pk

        response = self.client.post(reverse("projects:create"), data)

        project = Project.objects.get(company=self.company)
        self.assertRedirects(response, reverse("projects:detail", args=(project.pk,)))
        self.assertEqual(project.billing_type, Project.BillingType.FLAT_FEE)
        self.assertEqual(project.fixed_fee, Decimal("2500.00"))
        self.assertIsNone(project.hourly_rate)

    def test_project_form_scopes_client_choices(self):
        other_client = create_client(self.other_company, company_name="Hidden Client")
        data = project_data()
        data["client"] = other_client.pk
        data["fixed_fee"] = ""

        response = self.client.post(reverse("projects:create"), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(Project.objects.exists())

    def test_other_company_project_is_not_retrievable(self):
        other_client = create_client(self.other_company)
        project = create_project(
            company=self.other_company,
            client=other_client,
            project_data=project_data(number="OTHER-1"),
        )

        response = self.client.get(reverse("projects:detail", args=(project.pk,)))

        self.assertEqual(response.status_code, 404)

    def test_project_list_searches_project_and_client_details(self):
        visible = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="SEARCH-42", name="Porch addition"),
        )
        create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="OTHER-42", name="Kitchen"),
        )

        response = self.client.get(reverse("projects:list"), {"q": "Porch"})

        self.assertEqual(list(response.context["projects"]), [visible])

    def test_project_filter_empty_state_does_not_claim_there_are_no_projects(self):
        create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="EXISTS-42", name="Existing project"),
        )

        response = self.client.get(
            reverse("projects:list"),
            {"q": "No match", "status": Project.Status.ACTIVE},
        )

        self.assertContains(response, "No projects match this view")
        self.assertContains(response, "Clear filters")
        self.assertNotContains(response, "No projects yet")

    def test_project_status_filters_preserve_search_and_mark_the_active_view(self):
        visible = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="FILTER-42", name="Porch addition"),
        )
        visible.status = Project.Status.ACTIVE
        visible.save(update_fields=["status", "updated_at"])

        response = self.client.get(
            reverse("projects:list"),
            {"q": "Porch", "status": Project.Status.ACTIVE},
        )

        self.assertEqual(list(response.context["projects"]), [visible])
        self.assertContains(
            response,
            f'href="{reverse("projects:list")}?q=Porch&amp;status=lead"',
        )
        self.assertContains(
            response,
            f'href="{reverse("projects:list")}?status=active">Clear search</a>',
        )
        self.assertContains(
            response,
            'class="is-active" aria-current="page">Active</a>',
        )

    def test_project_detail_prioritizes_the_next_workflow_action(self):
        project = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="NEXT-STEP"),
        )

        response = self.client.get(reverse("projects:detail", args=(project.pk,)))

        self.assertContains(response, "Recommended next step")
        self.assertContains(response, "Prepare the customer proposal")
        self.assertContains(response, "More project actions")
        self.assertContains(response, 'href="#project-proposals"')
        self.assertContains(response, 'id="project-proposals"')

    def test_project_document_sections_have_independent_empty_states(self):
        project = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="DOCUMENT-SECTIONS"),
        )
        proposal = Document.objects.create(
            company=self.company,
            project=project,
            doc_type=Document.Type.PROPOSAL,
            invoice_kind="",
            number="P-SECTION",
        )

        response = self.client.get(reverse("projects:detail", args=(project.pk,)))

        self.assertEqual(response.context["proposals"], [proposal])
        self.assertEqual(response.context["invoices"], [])
        self.assertContains(response, "P-SECTION")
        self.assertContains(response, "No invoices.")
        self.assertNotContains(response, "No proposals.")

    def test_review_retainer_targets_the_invoice_section(self):
        project = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="RETAINER-ANCHOR"),
        )
        project.status = Project.Status.APPROVED
        project.save(update_fields=["status", "updated_at"])
        Document.objects.create(
            company=self.company,
            project=project,
            doc_type=Document.Type.INVOICE,
            invoice_kind=Document.InvoiceKind.RETAINER,
            number="I-RETAINER",
            due_date=date(2026, 8, 22),
        )

        response = self.client.get(reverse("projects:detail", args=(project.pk,)))

        self.assertContains(response, "Review retainer")
        self.assertContains(response, 'href="#project-invoices"')
        self.assertContains(response, 'id="project-invoices"')

    def test_status_is_managed_on_edit_but_new_projects_still_start_as_leads(self):
        project = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="STATUS-EDIT"),
        )

        create_response = self.client.get(reverse("projects:create"))
        edit_response = self.client.get(reverse("projects:update", args=(project.pk,)))

        self.assertNotIn("status", create_response.context["form"].fields)
        self.assertIn("status", edit_response.context["form"].fields)
        self.assertContains(edit_response, "Project status")
        self.assertContains(edit_response, "Confirm this manual status change")

    def test_manual_status_change_requires_confirmation_and_can_activate_lead(self):
        project = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="STATUS-ACTIVE"),
        )
        data = project_data(number=project.number)
        data.update(
            client=self.client_record.pk,
            fixed_fee="",
            status=Project.Status.ACTIVE,
        )

        unconfirmed = self.client.post(
            reverse("projects:update", args=(project.pk,)),
            data,
        )
        project.refresh_from_db()
        self.assertEqual(unconfirmed.status_code, 200)
        self.assertContains(unconfirmed, "Confirm the manual status change")
        self.assertEqual(project.status, Project.Status.LEAD)

        data["confirm_status_change"] = "on"
        confirmed = self.client.post(
            reverse("projects:update", args=(project.pk,)),
            data,
        )
        project.refresh_from_db()
        self.assertRedirects(
            confirmed,
            reverse("projects:detail", args=(project.pk,)),
        )
        self.assertEqual(project.status, Project.Status.ACTIVE)

    def test_manual_status_change_cannot_close_project_with_running_timer(self):
        project = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="STATUS-RUNNING"),
        )
        start_timer(user=self.user, project=project)
        data = project_data(number=project.number)
        data.update(
            client=self.client_record.pk,
            fixed_fee="",
            status=Project.Status.CANCELED,
            confirm_status_change="on",
        )

        response = self.client.post(
            reverse("projects:update", args=(project.pk,)),
            data,
        )

        project.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Stop the running timer")
        self.assertEqual(project.status, Project.Status.LEAD)
