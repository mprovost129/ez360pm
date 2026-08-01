import json
from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import Company
from clients.tests.test_clients import create_client
from documents.models import Document, Payment, StripeWebhookEvent
from documents.services import (
    create_invoice,
    issue_document,
    record_payment,
    record_refund,
    save_line_item,
)
from projects.models import Project
from projects.services import create_project
from projects.tests.test_projects import project_data


class DataAuditCommandTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        client = create_client(self.company)
        project = create_project(
            company=self.company,
            client=client,
            project_data=project_data(
                number="AUDIT-001",
                billing_type=Project.BillingType.FLAT_FEE,
                hourly_rate=None,
                fixed_fee=Decimal("2500.00"),
            ),
        )
        self.invoice = create_invoice(
            company=self.company,
            project=project,
            invoice_data={
                "invoice_kind": Document.InvoiceKind.FINAL,
                "number": "I-AUDIT-001",
                "issue_date": date(2026, 7, 21),
                "due_date": date(2026, 8, 20),
                "terms": "",
                "notes": "",
                "accept_payments": False,
            },
        )

    def test_valid_records_pass_and_json_is_machine_readable(self):
        output = StringIO()

        call_command(
            "data_audit",
            company_id=self.company.pk,
            as_json=True,
            stdout=output,
        )

        result = json.loads(output.getvalue())
        self.assertEqual(result["company_id"], self.company.pk)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["warnings"], 0)
        self.assertEqual(result["issues"], [])

    def test_total_drift_fails_without_modifying_the_record(self):
        Document.objects.filter(pk=self.invoice.pk).update(total=Decimal("2499.00"))
        output = StringIO()

        with self.assertRaisesMessage(CommandError, "Data audit failed"):
            call_command("data_audit", stdout=output)

        self.assertIn("document_total", output.getvalue())
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.total, Decimal("2499.00"))

    def test_unknown_company_is_rejected(self):
        with self.assertRaisesMessage(CommandError, "Company 999999 does not exist"):
            call_command("data_audit", company_id=999999)

    def test_refund_history_reconciles_and_cache_drift_is_detected(self):
        save_line_item(
            document=self.invoice,
            line_data={
                "description": "Design",
                "rate": Decimal("100.00"),
                "quantity": Decimal("1.00"),
                "tax_rate": Decimal("0"),
            },
        )
        issue_document(document=self.invoice)
        payment = record_payment(
            invoice=self.invoice,
            payment_data={
                "amount": Decimal("100.00"),
                "method": Payment.Method.CHECK,
                "received_at": date(2026, 7, 22),
                "reference": "Check",
            },
        )
        record_refund(
            payment=payment,
            amount=Decimal("40.00"),
            effective_at=date(2026, 7, 30),
        )
        output = StringIO()
        call_command("data_audit", company_id=self.company.pk, as_json=True, stdout=output)
        self.assertEqual(json.loads(output.getvalue())["errors"], 0)

        StripeWebhookEvent.objects.create(
            event_id="evt_audit_dispute",
            event_type="charge.dispute.created",
            payment_intent_id="pi_audit_dispute",
            payment=payment,
            status=StripeWebhookEvent.Status.REQUIRES_REVIEW,
        )
        output = StringIO()
        call_command("data_audit", company_id=self.company.pk, as_json=True, stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual(result["warnings"], 1)
        self.assertEqual(result["issues"][0]["code"], "stripe_event_attention")

        Payment.objects.filter(pk=payment.pk).update(refunded_amount=Decimal("0.00"))
        output = StringIO()
        with self.assertRaisesMessage(CommandError, "Data audit failed"):
            call_command("data_audit", company_id=self.company.pk, stdout=output)
        self.assertIn("refund_cache", output.getvalue())
