from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Company, User
from clients.tests.test_clients import create_client
from documents.models import Payment
from documents.services import (
    create_invoice,
    issue_document,
    record_payment,
    save_line_item,
)
from documents.tests.test_billing import invoice_data
from projects.models import Project
from projects.services import create_project
from projects.tests.test_projects import project_data
from projects.time_services import save_manual_entry


class DashboardAndReportingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other Studio")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.client_record = create_client(self.company)
        self.other_client = create_client(self.other_company, company_name="Other Client")
        self.client.force_login(self.user)

    def make_project(self, number, status=Project.Status.LEAD, *, other=False):
        company = self.other_company if other else self.company
        client = self.other_client if other else self.client_record
        project = create_project(
            company=company,
            client=client,
            project_data=project_data(number=number, name=f"Project {number}"),
        )
        if status != Project.Status.LEAD:
            project.status = status
            project.save(update_fields=["status"])
        return project

    def make_invoice(
        self,
        project,
        *,
        amount="100.00",
        due_date=None,
        issue=True,
    ):
        invoice = create_invoice(
            company=project.company,
            project=project,
            invoice_data=invoice_data(
                issue_date=timezone.localdate(),
                due_date=due_date or timezone.localdate() + timedelta(days=30),
            ),
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

    def record(self, invoice, amount, *, reference="payment"):
        return record_payment(
            invoice=invoice,
            payment_data={
                "amount": Decimal(amount),
                "method": Payment.Method.CHECK,
                "received_at": timezone.localdate(),
                "reference": reference,
            },
        )

    def test_dashboard_metrics_reconcile_and_exclude_other_company(self):
        self.make_project("LEAD-1")
        self.make_project("LEAD-OTHER", other=True)
        self.make_project("APPROVED-1", Project.Status.APPROVED)
        active = self.make_project("ACTIVE-1", Project.Status.ACTIVE)
        start = datetime(2026, 7, 10, 13, tzinfo=UTC)
        save_manual_entry(
            user=self.user,
            project=active,
            entry_data={
                "start_time": start,
                "end_time": start + timedelta(hours=2),
                "description": "Unbilled design",
                "billable": True,
            },
        )
        self.make_invoice(active, amount="25.00", issue=False)
        overdue = self.make_invoice(
            active,
            amount="100.00",
            due_date=timezone.localdate() - timedelta(days=1),
        )
        revenue_invoice = self.make_invoice(active, amount="50.00")
        self.record(revenue_invoice, "50.00")
        other_project = self.make_project("ACTIVE-OTHER", Project.Status.ACTIVE, other=True)
        other_invoice = self.make_invoice(other_project, amount="900.00")
        self.record(other_invoice, "900.00", reference="other")

        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["lead_count"], 1)
        self.assertEqual(response.context["approved_count"], 1)
        self.assertEqual(response.context["active_count"], 1)
        self.assertEqual(response.context["draft_count"], 1)
        self.assertEqual(response.context["unbilled_count"], 1)
        self.assertEqual(response.context["unbilled_hours"], Decimal("2.00"))
        self.assertEqual(response.context["unpaid_count"], 1)
        self.assertEqual(response.context["overdue_count"], 1)
        self.assertEqual(response.context["month_revenue"], Decimal("50.00"))
        self.assertContains(response, overdue.number)
        self.assertNotContains(response, "LEAD-OTHER")
        self.assertNotContains(response, "$900.00")

    def test_unbilled_hours_excludes_paused_duration(self):
        active = self.make_project("ACTIVE-PAUSED", Project.Status.ACTIVE)
        start = datetime(2026, 7, 10, 13, tzinfo=UTC)
        entry = save_manual_entry(
            user=self.user,
            project=active,
            entry_data={
                "start_time": start,
                "end_time": start + timedelta(hours=3),
                "description": "Design with a lunch break",
                "billable": True,
            },
        )
        entry.paused_duration = timedelta(hours=1)
        entry.save(update_fields=["paused_duration"])

        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.context["unbilled_hours"], Decimal("2.00"))

    def test_revenue_view_uses_payment_received_month_and_company(self):
        project = self.make_project("REVENUE-1", Project.Status.ACTIVE)
        invoice = self.make_invoice(project, amount="75.00")
        payment = self.record(invoice, "75.00", reference="own")
        other_project = self.make_project("REVENUE-OTHER", Project.Status.ACTIVE, other=True)
        other_invoice = self.make_invoice(other_project, amount="400.00")
        self.record(other_invoice, "400.00", reference="other-reference-unique")

        response = self.client.get(
            reverse("core:revenue"),
            {"month": payment.received_at.strftime("%Y-%m")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["revenue_total"], Decimal("75.00"))
        self.assertContains(response, "own")
        self.assertNotContains(response, "other-reference-unique")
        self.assertNotContains(response, "$400.00")

    def test_outstanding_and_draft_views_reconcile_balances(self):
        project = self.make_project("AR-1", Project.Status.ACTIVE)
        partial = self.make_invoice(project, amount="100.00")
        self.record(partial, "30.00")
        paid = self.make_invoice(project, amount="40.00")
        self.record(paid, "40.00")
        draft = self.make_invoice(project, amount="20.00", issue=False)
        other_project = self.make_project("AR-OTHER", Project.Status.ACTIVE, other=True)
        self.make_invoice(other_project, amount="500.00")

        outstanding = self.client.get(reverse("documents:outstanding-list"))
        drafts = self.client.get(reverse("core:draft-documents"))

        self.assertEqual(outstanding.context["outstanding_total"], Decimal("70.00"))
        self.assertContains(outstanding, partial.number)
        self.assertNotContains(outstanding, paid.number)
        self.assertNotContains(outstanding, "Other Client")
        self.assertContains(drafts, draft.number)
        self.assertNotContains(drafts, "Other Client")

    def test_project_and_time_filters_match_dashboard_links(self):
        lead = self.make_project("FILTER-LEAD")
        active = self.make_project("FILTER-ACTIVE", Project.Status.ACTIVE)
        start = datetime(2026, 7, 11, 13, tzinfo=UTC)
        save_manual_entry(
            user=self.user,
            project=active,
            entry_data={
                "start_time": start,
                "end_time": start + timedelta(hours=1),
                "description": "Shown unbilled",
                "billable": True,
            },
        )
        save_manual_entry(
            user=self.user,
            project=active,
            entry_data={
                "start_time": start + timedelta(days=1),
                "end_time": start + timedelta(days=1, hours=1),
                "description": "Hidden nonbillable",
                "billable": False,
            },
        )

        projects = self.client.get(reverse("projects:list"), {"status": "lead"})
        time = self.client.get(reverse("projects:time-list"), {"unbilled": "on"})

        self.assertContains(projects, lead.number)
        self.assertNotContains(projects, active.number)
        self.assertContains(time, "Shown unbilled")
        self.assertNotContains(time, "Hidden nonbillable")

    def test_hourly_effective_rate_uses_issued_final_invoice_subtotal(self):
        project = self.make_project("RATE-1", Project.Status.ACTIVE)
        start = datetime(2026, 7, 12, 13, tzinfo=UTC)
        save_manual_entry(
            user=self.user,
            project=project,
            entry_data={
                "start_time": start,
                "end_time": start + timedelta(hours=2),
                "description": "Work",
                "billable": True,
            },
        )
        self.make_invoice(project, amount="300.00")

        self.assertEqual(project.effective_hourly_rate, Decimal("150.00"))


class CompanySettingsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Original Studio")
        self.other_company = Company.objects.create(name="Other Studio")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.client.force_login(self.user)

    def test_owner_updates_only_assigned_company_and_defaults(self):
        response = self.client.post(
            reverse("accounts:settings"),
            {
                "name": "Provost Home Design",
                "address_1": "1 Studio Way",
                "address_2": "",
                "city": "Richmond",
                "state": "VA",
                "postal_code": "23220",
                "country": "United States",
                "phone": "555-0100",
                "email": "office@example.com",
                "default_hourly_rate": "185.00",
                "accept_payments_default": "on",
                "default_proposal_terms": "Valid for 30 days.",
                "default_invoice_terms": "Payment due on receipt.",
                "default_invoice_due_days": "21",
                "default_tax_rate": "5.300",
            },
        )

        self.assertRedirects(response, reverse("accounts:settings"))
        self.company.refresh_from_db()
        self.other_company.refresh_from_db()
        self.assertEqual(self.company.name, "Provost Home Design")
        self.assertEqual(self.company.default_hourly_rate, Decimal("185.00"))
        self.assertTrue(self.company.accept_payments_default)
        self.assertEqual(self.company.default_proposal_terms, "Valid for 30 days.")
        self.assertEqual(self.company.default_invoice_due_days, 21)
        self.assertEqual(self.company.default_tax_rate, Decimal("5.300"))
        self.assertEqual(self.other_company.name, "Other Studio")

    def test_settings_require_login(self):
        self.client.logout()

        response = self.client.get(reverse("accounts:settings"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('accounts:settings')}",
        )
