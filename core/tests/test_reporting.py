from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.forms import CompanySettingsForm
from accounts.models import Company, User
from clients.tests.test_clients import create_client
from documents.models import (
    Document,
    Payment,
    PaymentAdjustment,
    PaymentFeeReconciliationAttempt,
)
from documents.services import (
    create_invoice,
    issue_document,
    record_payment,
    record_payment_adjustment,
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
        self.assertEqual(response.context["oldest_unbilled_at"], start)
        self.assertEqual(response.context["unpaid_count"], 1)
        self.assertEqual(response.context["overdue_count"], 1)
        self.assertEqual(response.context["month_revenue"], Decimal("50.00"))
        self.assertContains(response, overdue.number)
        self.assertContains(response, "oldest")
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


class RevenueReportingV11Tests(TestCase):
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

    def make_payment(
        self,
        *,
        company=None,
        amount="100.00",
        method=Payment.Method.CHECK,
        received_at=date(2026, 1, 1),
        fee="0.00",
        fee_pending=False,
        reference="receipt",
    ):
        company = company or self.company
        client = self.client_record if company == self.company else self.other_client
        project = create_project(
            company=company,
            client=client,
            project_data=project_data(
                number=f"REV-{company.pk}-{received_at:%Y%m%d}-{method}-{reference[-4:]}",
                name="Revenue project",
            ),
        )
        invoice = create_invoice(
            company=company,
            project=project,
            invoice_data=invoice_data(
                issue_date=received_at,
                due_date=received_at + timedelta(days=30),
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
        issue_document(document=invoice)
        return record_payment(
            invoice=invoice,
            payment_data={
                "amount": Decimal(amount),
                "fee_amount": Decimal(fee),
                "fee_pending": fee_pending,
                "method": method,
                "received_at": received_at,
                "reference": reference,
                "stripe_payment_intent_id": (
                    f"pi_{company.pk}_{received_at:%Y%m%d}_{reference[-4:]}"
                    if method == Payment.Method.STRIPE
                    else None
                ),
            },
        )

    def test_calendar_year_and_method_filter_include_all_revenue_sources(self):
        self.make_payment(
            amount="100.00",
            method=Payment.Method.STRIPE,
            received_at=date(2026, 1, 1),
            fee="3.20",
            reference="stripe-one",
        )
        self.make_payment(
            amount="50.00",
            method=Payment.Method.CHECK,
            received_at=date(2026, 12, 31),
            reference="check-one",
        )
        self.make_payment(
            company=self.other_company,
            amount="900.00",
            method=Payment.Method.STRIPE,
            received_at=date(2026, 6, 1),
            fee="30.00",
            reference="other-company",
        )

        all_methods = self.client.get(
            reverse("core:revenue"),
            {"preset": "year", "year": "2026"},
        )
        stripe_only = self.client.get(
            reverse("core:revenue"),
            {"preset": "year", "year": "2026", "method": "stripe"},
        )

        self.assertEqual(all_methods.context["report"].gross, Decimal("150.00"))
        self.assertEqual(all_methods.context["report"].fees, Decimal("3.20"))
        self.assertEqual(all_methods.context["report"].net, Decimal("146.80"))
        self.assertEqual(stripe_only.context["report"].gross, Decimal("100.00"))
        self.assertEqual(stripe_only.context["report"].fees, Decimal("3.20"))
        self.assertNotContains(all_methods, "other-company")

    def test_custom_range_is_inclusive_and_pending_fee_is_explicit(self):
        self.make_payment(
            amount="25.00",
            method=Payment.Method.STRIPE,
            received_at=date(2026, 2, 1),
            fee_pending=True,
            reference="pending-fee",
        )

        response = self.client.get(
            reverse("core:revenue"),
            {
                "preset": "custom",
                "start_date": "2026-02-01",
                "end_date": "2026-02-01",
            },
        )

        self.assertEqual(response.context["report"].gross, Decimal("25.00"))
        self.assertEqual(response.context["report"].pending_fee_count, 1)
        self.assertContains(response, "Pending")

    def test_pending_fee_filter_shows_latest_reconciliation_detail(self):
        pending = self.make_payment(
            amount="25.00",
            method=Payment.Method.STRIPE,
            received_at=date(2026, 2, 1),
            fee_pending=True,
            reference="pending-only",
        )
        self.make_payment(
            amount="40.00",
            method=Payment.Method.CHECK,
            received_at=date(2026, 2, 1),
            reference="not-pending",
        )
        attempt = PaymentFeeReconciliationAttempt(
            company=self.company,
            payment=pending,
            status=PaymentFeeReconciliationAttempt.Status.ERROR,
            error_code="api_connection_error",
            error_message="Stripe could not return the processing fee. Retry later.",
        )
        attempt.full_clean()
        attempt.save()

        response = self.client.get(
            reverse("core:revenue"),
            {
                "preset": "year",
                "year": "2026",
                "fee_status": "pending",
            },
        )

        report = response.context["report"]
        self.assertEqual(report.payment_count, 1)
        self.assertEqual(report.gross, Decimal("25.00"))
        self.assertTrue(response.context["filters"].pending_fees_only)
        self.assertContains(response, "Provider error")
        self.assertContains(response, "Stripe could not return the processing fee")
        self.assertNotContains(response, "not-pending")

    def test_additional_processing_fee_stays_in_fee_totals(self):
        payment = self.make_payment(
            amount="100.00",
            method=Payment.Method.STRIPE,
            received_at=date(2026, 7, 1),
            fee="3.20",
            reference="fee-increase",
        )
        adjustment = record_payment_adjustment(
            payment=payment,
            adjustment_data={
                "adjustment_type": PaymentAdjustment.Type.FEE_ADJUSTMENT,
                "amount": Decimal("-0.20"),
                "effective_at": date(2026, 7, 2),
                "affects_invoice_balance": False,
                "reference": "Additional Stripe fee",
            },
        )

        response = self.client.get(
            reverse("core:revenue"), {"preset": "year", "year": "2026"}
        )
        report = response.context["report"]

        self.assertTrue(adjustment.affects_processing_fees)
        self.assertEqual(report.original_fees, Decimal("3.20"))
        self.assertEqual(report.fee_adjustments, Decimal("-0.20"))
        self.assertEqual(report.fees, Decimal("3.40"))
        self.assertEqual(report.adjustments, Decimal("0.00"))
        self.assertEqual(report.net, Decimal("96.60"))

    def test_fee_refund_reduces_processing_fee_total_not_customer_adjustments(self):
        payment = self.make_payment(
            amount="100.00",
            method=Payment.Method.STRIPE,
            received_at=date(2026, 7, 1),
            fee="3.20",
            reference="fee-refund",
        )
        record_payment_adjustment(
            payment=payment,
            adjustment_data={
                "adjustment_type": PaymentAdjustment.Type.FEE_REFUND,
                "amount": Decimal("0.30"),
                "effective_at": date(2026, 7, 2),
                "affects_invoice_balance": False,
                "reference": "Stripe fee refund",
            },
        )

        response = self.client.get(
            reverse("core:revenue"), {"preset": "year", "year": "2026"}
        )
        report = response.context["report"]

        self.assertEqual(report.original_fees, Decimal("3.20"))
        self.assertEqual(report.fee_adjustments, Decimal("0.30"))
        self.assertEqual(report.fees, Decimal("2.90"))
        self.assertEqual(report.adjustments, Decimal("0.00"))
        self.assertEqual(report.net, Decimal("97.10"))
        self.assertContains(response, "Stripe fee refund")

    def test_refund_is_reported_in_effective_year_and_reopens_invoice_balance(self):
        payment = self.make_payment(
            amount="100.00",
            method=Payment.Method.STRIPE,
            received_at=date(2026, 12, 20),
            fee="3.20",
            reference="year-end",
        )
        record_payment_adjustment(
            payment=payment,
            adjustment_data={
                "adjustment_type": PaymentAdjustment.Type.REFUND,
                "amount": Decimal("-25.00"),
                "effective_at": date(2027, 1, 5),
                "affects_invoice_balance": True,
                "provider_id": "stripe-refund:re_123",
                "reference": "Partial refund",
            },
        )

        prior_year = self.client.get(
            reverse("core:revenue"), {"preset": "year", "year": "2026"}
        )
        refund_year = self.client.get(
            reverse("core:revenue"), {"preset": "year", "year": "2027"}
        )
        payment.document.refresh_from_db()

        self.assertEqual(prior_year.context["report"].gross, Decimal("100.00"))
        self.assertEqual(prior_year.context["report"].adjustments, Decimal("0.00"))
        self.assertEqual(refund_year.context["report"].gross, Decimal("0.00"))
        self.assertEqual(refund_year.context["report"].adjustments, Decimal("-25.00"))
        self.assertEqual(refund_year.context["report"].net, Decimal("-25.00"))
        self.assertEqual(payment.document.status, Document.Status.PARTIALLY_PAID)
        self.assertEqual(payment.document.outstanding_balance, Decimal("25.00"))

    def test_financial_period_cannot_close_with_pending_stripe_fees(self):
        self.make_payment(
            amount="25.00",
            method=Payment.Method.STRIPE,
            received_at=date(2026, 1, 15),
            fee_pending=True,
            reference="pending-at-close",
        )
        form = CompanySettingsForm(
            data={
                "name": self.company.name,
                "default_hourly_rate": "0.00",
                "default_invoice_due_days": "30",
                "default_tax_rate": "0.000",
                "books_closed_through": "2026-01-31",
            },
            instance=self.company,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("books_closed_through", form.errors)
        self.assertIn("pending Stripe fees", form.errors["books_closed_through"][0])

    def test_csv_matches_filters_and_neutralizes_spreadsheet_formulas(self):
        self.make_payment(
            amount="70.00",
            method=Payment.Method.CASH,
            received_at=date(2026, 7, 1),
            reference=" \t=SUM(A1:A2)",
        )

        response = self.client.get(
            reverse("core:revenue-csv"),
            {"preset": "year", "year": "2026", "method": "cash"},
        )
        content = response.content.decode("utf-8-sig")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Gross received,70.00", content)
        self.assertIn("' \t=SUM(A1:A2)", content)
        self.assertIn("ez360pm-payments-2026-01-01-to-2026-12-31-cash.csv", response["Content-Disposition"])

    def test_invalid_filters_fall_back_without_widening_company_scope(self):
        self.make_payment(
            company=self.other_company,
            amount="500.00",
            received_at=timezone.localdate(),
            reference="never-visible",
        )

        response = self.client.get(
            reverse("core:revenue"),
            {
                "preset": "custom",
                "start_date": "bad",
                "end_date": "also-bad",
                "method": "untrusted",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "never-visible")



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
                "books_closed_through": "2025-12-31",
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
        self.assertEqual(self.company.books_closed_through, date(2025, 12, 31))
        self.assertEqual(self.other_company.name, "Other Studio")

    def test_financial_lock_cannot_be_set_in_the_future(self):
        future_day = timezone.localdate() + timedelta(days=1)

        response = self.client.post(
            reverse("accounts:settings"),
            {
                "name": self.company.name,
                "address_1": "",
                "address_2": "",
                "city": "",
                "state": "",
                "postal_code": "",
                "country": "United States",
                "phone": "",
                "email": "",
                "default_hourly_rate": "0.00",
                "default_invoice_due_days": "30",
                "default_tax_rate": "0.000",
                "books_closed_through": future_day.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be in the future")
        self.company.refresh_from_db()
        self.assertIsNone(self.company.books_closed_through)

    def test_settings_require_login(self):
        self.client.logout()

        response = self.client.get(reverse("accounts:settings"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('accounts:settings')}",
        )
