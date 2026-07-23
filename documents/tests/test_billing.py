from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Company, User
from clients.tests.test_clients import create_client
from documents.models import Document, Payment
from documents.pdf import build_invoice_pdf
from documents.services import (
    attach_time_to_invoice,
    create_invoice,
    delete_draft_document,
    delete_line_item,
    delete_payment,
    issue_document,
    move_line_item,
    record_payment,
    record_public_view,
    release_void_invoice_time,
    save_line_item,
    void_invoice,
)
from projects.models import Project, TimeEntry
from projects.services import create_project
from projects.tests.test_projects import project_data
from projects.time_services import save_manual_entry


def invoice_data(**overrides):
    data = {
        "invoice_kind": Document.InvoiceKind.FINAL,
        "number": "",
        "issue_date": date(2026, 7, 21),
        "due_date": date(2026, 8, 20),
        "terms": "Payment due within 30 days.",
        "notes": "Thank you.",
        "accept_payments": False,
    }
    data.update(overrides)
    return data


class BillingServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Provost Home Design",
            address_1="1 Studio Way",
            city="Richmond",
            state="VA",
            postal_code="23220",
            email="office@example.com",
        )
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        client = create_client(self.company)
        self.hourly_project = create_project(
            company=self.company,
            client=client,
            project_data=project_data(number="BILL-HOURLY", hourly_rate=Decimal("100.00")),
        )
        self.flat_project = create_project(
            company=self.company,
            client=client,
            project_data=project_data(
                number="BILL-FLAT",
                billing_type=Project.BillingType.FLAT_FEE,
                hourly_rate=None,
                fixed_fee=Decimal("2500.00"),
            ),
        )

    def make_hourly_invoice(self):
        return create_invoice(
            company=self.company,
            project=self.hourly_project,
            invoice_data=invoice_data(),
        )

    def add_line(self, invoice, **overrides):
        data = {
            "description": "Professional services",
            "rate": Decimal("100.00"),
            "quantity": Decimal("1.00"),
            "tax_rate": Decimal("0"),
        }
        data.update(overrides)
        return save_line_item(document=invoice, line_data=data)

    def add_time(self, *, description, hours, day=1):
        start = datetime(2026, 7, day, 13, tzinfo=UTC)
        return save_manual_entry(
            user=self.user,
            project=self.hourly_project,
            entry_data={
                "start_time": start,
                "end_time": start + timedelta(hours=hours),
                "description": description,
                "billable": True,
            },
        )

    def test_numbering_and_flat_fee_line_are_created_atomically(self):
        first = create_invoice(
            company=self.company,
            project=self.flat_project,
            invoice_data=invoice_data(),
        )
        second = self.make_hourly_invoice()

        self.assertEqual(first.number, "I-26-0001")
        self.assertEqual(second.number, "I-26-0002")
        self.assertEqual(first.line_items.count(), 1)
        self.assertEqual(first.total, Decimal("2500.00"))

    def test_totals_round_each_line_and_tax_to_cents(self):
        invoice = self.make_hourly_invoice()
        self.add_line(
            invoice,
            rate=Decimal("10.0050"),
            quantity=Decimal("1.00"),
            tax_rate=Decimal("7.500"),
        )
        invoice.refresh_from_db()

        self.assertEqual(invoice.subtotal, Decimal("10.01"))
        self.assertEqual(invoice.tax_total, Decimal("0.75"))
        self.assertEqual(invoice.total, Decimal("10.76"))

    def test_grouped_time_attaches_to_lines_and_delete_releases_it(self):
        invoice = self.make_hourly_invoice()
        entries = [
            self.add_time(description="Schematic design", hours=1, day=1),
            self.add_time(description="Schematic design", hours=2, day=2),
            self.add_time(description="Site visit", hours=0.5, day=3),
        ]

        attach_time_to_invoice(invoice=invoice, entries=entries, grouping="description")
        invoice.refresh_from_db()
        self.assertEqual(invoice.line_items.count(), 2)
        self.assertEqual(invoice.total, Decimal("350.00"))
        self.assertFalse(
            TimeEntry.objects.filter(pk__in=[entry.pk for entry in entries], status="logged").exists()
        )

        design_line = invoice.line_items.get(description="Schematic design")
        delete_line_item(line=design_line)
        self.assertEqual(
            TimeEntry.objects.filter(
                pk__in=[entries[0].pk, entries[1].pk],
                status=TimeEntry.Status.LOGGED,
                line_item__isnull=True,
            ).count(),
            2,
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.total, Decimal("50.00"))

    def test_deleting_draft_releases_all_attached_time(self):
        invoice = self.make_hourly_invoice()
        entry = self.add_time(description="Drafting", hours=1)
        attach_time_to_invoice(invoice=invoice, entries=[entry], grouping="combined")

        delete_draft_document(document=invoice)

        entry.refresh_from_db()
        self.assertEqual(entry.status, TimeEntry.Status.LOGGED)
        self.assertIsNone(entry.line_item_id)
        self.assertFalse(Document.objects.filter(pk=invoice.pk).exists())

    def test_payment_rows_drive_partial_paid_and_reversal_statuses(self):
        invoice = self.make_hourly_invoice()
        self.add_line(invoice)
        issue_document(document=invoice)
        invoice.refresh_from_db()

        first = record_payment(
            invoice=invoice,
            payment_data={
                "amount": Decimal("40.00"),
                "method": Payment.Method.CHECK,
                "received_at": date(2026, 7, 22),
                "reference": "1001",
            },
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PARTIALLY_PAID)
        self.assertEqual(invoice.outstanding_balance, Decimal("60.00"))

        second = record_payment(
            invoice=invoice,
            payment_data={
                "amount": Decimal("60.00"),
                "method": Payment.Method.CASH,
                "received_at": date(2026, 7, 23),
                "reference": "",
            },
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PAID)
        self.assertEqual(invoice.outstanding_balance, Decimal("0.00"))

        delete_payment(payment=second)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PARTIALLY_PAID)
        self.assertEqual(invoice.amount_paid, first.amount)

    def test_overpayment_is_rejected(self):
        invoice = self.make_hourly_invoice()
        self.add_line(invoice)
        issue_document(document=invoice)

        with self.assertRaises(ValidationError):
            record_payment(
                invoice=invoice,
                payment_data={
                    "amount": Decimal("100.01"),
                    "method": Payment.Method.CHECK,
                    "received_at": date(2026, 7, 22),
                    "reference": "",
                },
            )

    def test_stripe_intent_is_idempotent_and_cannot_cross_invoices(self):
        invoice = self.make_hourly_invoice()
        self.add_line(invoice)
        issue_document(document=invoice)
        data = {
            "amount": Decimal("100.00"),
            "method": Payment.Method.STRIPE,
            "received_at": date(2026, 7, 22),
            "reference": "",
            "stripe_payment_intent_id": "pi_test_123",
        }

        first = record_payment(invoice=invoice, payment_data=data)
        repeated = record_payment(invoice=invoice, payment_data=data)
        self.assertEqual(first.pk, repeated.pk)
        self.assertEqual(Payment.objects.count(), 1)

        other = self.make_hourly_invoice()
        self.add_line(other)
        issue_document(document=other)
        with self.assertRaises(ValidationError):
            record_payment(invoice=other, payment_data=data)

    def test_void_keeps_time_until_explicit_release(self):
        invoice = self.make_hourly_invoice()
        entry = self.add_time(description="Permit set", hours=1)
        attach_time_to_invoice(invoice=invoice, entries=[entry], grouping="combined")
        issue_document(document=invoice)
        void_invoice(invoice=invoice, reason="Issued in error")

        entry.refresh_from_db()
        self.assertEqual(entry.status, TimeEntry.Status.INVOICED)
        released = release_void_invoice_time(invoice=invoice)
        entry.refresh_from_db()
        self.assertEqual(released, 1)
        self.assertEqual(entry.status, TimeEntry.Status.LOGGED)
        self.assertIsNone(entry.line_item_id)

    def test_public_view_stamps_only_first_view(self):
        invoice = self.make_hourly_invoice()
        self.add_line(invoice)
        issue_document(document=invoice)
        first_time = datetime(2026, 7, 22, 12, tzinfo=UTC)
        later_time = first_time + timedelta(hours=1)

        viewed = record_public_view(document=invoice, at=first_time)
        repeated = record_public_view(document=viewed, at=later_time)

        self.assertEqual(repeated.status, Document.Status.VIEWED)
        self.assertEqual(repeated.viewed_at, first_time)

    def test_issued_invoice_cannot_be_deleted_directly(self):
        invoice = self.make_hourly_invoice()
        self.add_line(invoice)
        invoice = issue_document(document=invoice)

        with self.assertRaises(ValidationError):
            invoice.delete()

    def test_pdf_is_a_real_pdf(self):
        invoice = create_invoice(
            company=self.company,
            project=self.flat_project,
            invoice_data=invoice_data(),
        )

        pdf = build_invoice_pdf(invoice)

        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)


class InvoiceViewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        client = create_client(self.company)
        other_client = create_client(self.other_company, company_name="Other Client")
        self.project = create_project(
            company=self.company,
            client=client,
            project_data=project_data(number="VIEW-BILL"),
        )
        self.other_project = create_project(
            company=self.other_company,
            client=other_client,
            project_data=project_data(number="OTHER-BILL"),
        )
        self.client.force_login(self.user)

    def make_invoice(self, *, other=False):
        company = self.other_company if other else self.company
        project = self.other_project if other else self.project
        invoice = create_invoice(company=company, project=project, invoice_data=invoice_data())
        save_line_item(
            document=invoice,
            line_data={
                "description": "Design services",
                "rate": Decimal("100.00"),
                "quantity": Decimal("1.00"),
                "tax_rate": Decimal("0"),
            },
        )
        invoice.refresh_from_db()
        return invoice

    def test_create_invoice_form_and_add_line(self):
        response = self.client.post(
            reverse("documents:invoice-create"),
            {
                "project": self.project.pk,
                "invoice_kind": "final",
                "number": "",
                "issue_date": "2026-07-21",
                "due_date": "2026-08-20",
                "terms": "Net 30",
                "notes": "",
            },
        )
        invoice = Document.objects.get(company=self.company)
        self.assertRedirects(response, reverse("documents:invoice-detail", args=(invoice.pk,)))

        line_response = self.client.post(
            reverse("documents:line-create", args=(invoice.pk,)),
            {
                "description": "Design services",
                "rate": "125.00",
                "quantity": "2.00",
                "tax_rate": "0",
            },
        )
        self.assertRedirects(line_response, reverse("documents:invoice-detail", args=(invoice.pk,)))
        invoice.refresh_from_db()
        self.assertEqual(invoice.total, Decimal("250.00"))

    def test_invoice_authoring_defaults_and_locks_project_context(self):
        self.company.default_invoice_due_days = 14
        self.company.default_invoice_terms = "Due after delivery."
        self.company.default_tax_rate = Decimal("5.300")
        self.company.save(
            update_fields=[
                "default_invoice_due_days",
                "default_invoice_terms",
                "default_tax_rate",
            ]
        )
        response = self.client.get(
            reverse("documents:invoice-create"),
            {"project": self.project.pk},
        )

        form = response.context["form"]
        self.assertTrue(form.fields["project"].disabled)
        self.assertEqual(form.fields["project"].initial, self.project)
        self.assertEqual(
            form.fields["due_date"].initial,
            timezone.localdate() + timedelta(days=14),
        )
        self.assertEqual(form.fields["terms"].initial, "Due after delivery.")
        self.assertEqual(form.fields["notes"].label, "Internal notes")
        self.assertEqual(
            form.fields["accept_payments"].label,
            "Allow online payment with Stripe",
        )

    def test_invoice_detail_improves_line_and_time_authoring_context(self):
        invoice = self.make_invoice()
        start = timezone.now() - timedelta(hours=2)
        TimeEntry.objects.create(
            company=self.company,
            project=self.project,
            user=self.user,
            start_time=start,
            end_time=start + timedelta(hours=2),
            description="Design development",
        )

        response = self.client.get(
            reverse("documents:invoice-detail", args=(invoice.pk,))
        )

        line_form = response.context["line_item_form"]
        self.assertEqual(line_form.fields["quantity"].initial, Decimal("1.00"))
        self.assertEqual(line_form.fields["tax_rate"].initial, Decimal("0.000"))
        self.assertContains(response, "Line amount")
        self.assertContains(response, "Select all")
        self.assertContains(response, "Design development")
        self.assertContains(response, "$175.00/hr")
        self.assertContains(response, "Draft readiness")

    def test_draft_invoice_lines_can_be_reordered(self):
        invoice = self.make_invoice()
        second = save_line_item(
            document=invoice,
            line_data={
                "description": "Second phase",
                "rate": Decimal("50.00"),
                "quantity": Decimal("1.00"),
                "tax_rate": Decimal("0"),
            },
        )
        first = invoice.line_items.exclude(pk=second.pk).get()

        move_line_item(document=invoice, line=second, direction="up")

        self.assertEqual(
            list(invoice.line_items.values_list("pk", flat=True)),
            [second.pk, first.pk],
        )

    def test_issue_and_email_continues_to_delivery_form(self):
        invoice = self.make_invoice()

        response = self.client.post(
            reverse("documents:invoice-issue", args=(invoice.pk,)),
            {"send_after_issue": "1"},
        )

        self.assertRedirects(
            response,
            reverse("documents:invoice-send", args=(invoice.pk,)),
            fetch_redirect_response=False,
        )

    def test_other_company_invoice_is_not_retrievable(self):
        hidden = self.make_invoice(other=True)

        response = self.client.get(reverse("documents:invoice-detail", args=(hidden.pk,)))

        self.assertEqual(response.status_code, 404)

    def test_issued_invoice_public_view_and_pdf(self):
        invoice = self.make_invoice()
        issue_document(document=invoice)
        invoice.refresh_from_db()

        public_response = self.client.get(
            reverse("public-documents:view", args=(invoice.public_token,))
        )
        pdf_response = self.client.get(
            reverse("public-documents:pdf", args=(invoice.public_token,))
        )

        self.assertEqual(public_response.status_code, 200)
        self.assertContains(public_response, invoice.number)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")
        for response in (public_response, pdf_response):
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(response["Referrer-Policy"], "no-referrer")
            self.assertEqual(
                response["X-Robots-Tag"],
                "noindex, nofollow, noarchive",
            )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.VIEWED)

    def test_draft_public_token_returns_not_found(self):
        invoice = self.make_invoice()

        response = self.client.get(
            reverse("public-documents:view", args=(invoice.public_token,))
        )

        self.assertEqual(response.status_code, 404)

    def test_manual_payment_form_recalculates_status(self):
        invoice = self.make_invoice()
        issue_document(document=invoice)

        response = self.client.post(
            reverse("documents:payment-create", args=(invoice.pk,)),
            {
                "amount": "100.00",
                "method": "check",
                "received_at": "2026-07-22",
                "reference": "1002",
            },
        )

        self.assertRedirects(response, reverse("documents:invoice-detail", args=(invoice.pk,)))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Document.Status.PAID)
