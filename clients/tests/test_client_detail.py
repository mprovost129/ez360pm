from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Company, User
from documents.models import Document, Payment
from documents.proposal_services import create_proposal
from documents.services import (
    create_invoice,
    issue_document,
    record_payment,
    save_line_item,
)
from intake.models import Note
from projects.models import TimeEntry
from projects.services import create_project
from projects.tests.test_projects import project_data

from .test_clients import create_client


def make_final_invoice(*, company, project, amount="100.00"):
    invoice = create_invoice(
        company=company,
        project=project,
        invoice_data={
            "invoice_kind": Document.InvoiceKind.FINAL,
            "number": "",
            "issue_date": date(2026, 7, 21),
            "due_date": date(2026, 8, 20),
            "terms": "",
            "notes": "",
            "accept_payments": False,
        },
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


class ClientDetailConnectedInfoTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.client.force_login(self.user)
        self.client_record = create_client(self.company)
        self.project = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="CLIENT-TABS-1"),
        )

    def test_detail_page_shows_connected_records_across_tabs(self):
        invoice = make_final_invoice(company=self.company, project=self.project)
        record_payment(
            invoice=invoice,
            payment_data={
                "amount": Decimal("100.00"),
                "method": Payment.Method.CHECK,
                "received_at": date(2026, 7, 22),
                "reference": "check 900",
            },
        )
        proposal = create_proposal(
            company=self.company,
            project=self.project,
            proposal_data={
                "number": "",
                "issue_date": date(2026, 7, 21),
                "terms": "",
                "notes": "",
            },
        )
        TimeEntry.objects.create(
            company=self.company,
            project=self.project,
            user=self.user,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
            description="Site visit",
        )
        Note.objects.create(
            company=self.company,
            client=self.client_record,
            body="Called about timeline.",
        )

        response = self.client.get(reverse("clients:detail", args=(self.client_record.pk,)))

        self.assertContains(response, invoice.number)
        self.assertContains(response, proposal.number)
        self.assertContains(response, "Site visit")
        self.assertContains(response, "Called about timeline.")
        self.assertContains(response, "$100.00")

    def test_detail_page_does_not_leak_another_companys_data(self):
        make_final_invoice(company=self.company, project=self.project)

        other_client = create_client(self.other_company, company_name="Other Client")
        other_project = create_project(
            company=self.other_company,
            client=other_client,
            project_data=project_data(number="OTHER-TABS-1"),
        )
        other_invoice = make_final_invoice(
            company=self.other_company, project=other_project, amount="500.00"
        )
        record_payment(
            invoice=other_invoice,
            payment_data={
                "amount": Decimal("500.00"),
                "method": Payment.Method.CHECK,
                "received_at": date(2026, 7, 22),
                "reference": "other check",
            },
        )
        Note.objects.create(
            company=self.other_company,
            client=other_client,
            body="Secret other-company note.",
        )

        response = self.client.get(reverse("clients:detail", args=(self.client_record.pk,)))

        # Per-company document numbering means invoice numbers can collide
        # across companies (each starts its own sequence at 0001), so isolation
        # is asserted on project number and amount instead of invoice.number.
        self.assertNotContains(response, other_project.number)
        self.assertNotContains(response, "Secret other-company note.")
        self.assertNotContains(response, "$500.00")
        self.assertNotContains(
            response, reverse("documents:invoice-detail", args=(other_invoice.pk,))
        )

    def test_time_tab_reports_full_count_when_recent_entries_are_limited(self):
        now = timezone.now()
        TimeEntry.objects.bulk_create(
            [
                TimeEntry(
                    company=self.company,
                    project=self.project,
                    user=self.user,
                    start_time=now - timedelta(days=index, hours=1),
                    end_time=now - timedelta(days=index),
                    description=f"Session {index + 1}",
                )
                for index in range(27)
            ]
        )

        response = self.client.get(
            reverse("clients:detail", args=(self.client_record.pk,))
        )

        self.assertEqual(response.context["time_entry_count"], 27)
        self.assertEqual(len(response.context["time_entries"]), 25)
        self.assertTrue(response.context["time_entries_truncated"])
        self.assertContains(response, 'Time <span class="tab-count">27</span>')
        self.assertContains(response, "Showing the latest 25 of 27 time entries")
        self.assertContains(response, "27h")
