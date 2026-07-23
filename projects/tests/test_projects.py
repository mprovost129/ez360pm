from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Company, User
from clients.tests.test_clients import create_client
from projects.models import Project
from projects.services import allocate_project_number, create_project


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
