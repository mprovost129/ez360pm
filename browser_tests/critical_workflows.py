import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from accounts.models import Company, User
from clients.services import create_client_with_primary_contact
from documents.models import Document, Payment
from documents.services import create_invoice, issue_document, save_line_item
from intake.models import Note
from projects.models import Project
from projects.services import create_project

# Playwright's synchronous driver runs an event loop in this test process. The
# browser suite is isolated in its own command/job, while Django's live server
# handles requests on a separate thread, so synchronous fixture ORM access is
# intentional here and never enables this escape hatch in the application.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


class CriticalWorkflowBrowserTests(StaticLiveServerTestCase):
    """Rendered-browser proof for workflows where several UI layers interact."""

    password = "Browser-Test-Password-483!"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        launch_options = {
            "headless": os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0"
        }
        browser_channel = os.environ.get("PLAYWRIGHT_BROWSER_CHANNEL", "").strip()
        if browser_channel:
            launch_options["channel"] = browser_channel
        cls.browser = cls.playwright.chromium.launch(**launch_options)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def setUp(self):
        self.company = Company.objects.create(
            name="Browser Test Design",
            email="office@example.test",
        )
        self.user = User.objects.create_user(
            "browser-owner@example.test",
            self.password,
            company=self.company,
        )
        self.client_record = create_client_with_primary_contact(
            company=self.company,
            client_data={"company_name": "Browser Test Client"},
            contact_data={
                "first_name": "Alex",
                "last_name": "Browser",
                "email": "client@example.test",
                "phone": "555-0100",
            },
        )
        self.project = create_project(
            company=self.company,
            client=self.client_record,
            project_data={
                "number": "E2E-001",
                "name": "Browser Workflow Project",
                "description": "Critical workflow browser fixture.",
                "address_1": "100 Main Street",
                "address_2": "",
                "city": "Richmond",
                "state": "VA",
                "postal_code": "23220",
                "municipality": "Richmond",
                "parcel_id": "E2E-PARCEL",
                "billing_type": Project.BillingType.FLAT_FEE,
                "hourly_rate": None,
                "fixed_fee": Decimal("100.00"),
                "estimated_hours": Decimal("1.00"),
            },
        )
        self.context = self.browser.new_context(
            viewport={"width": 1600, "height": 1000}
        )
        self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10_000)
        self.addCleanup(self._close_browser_context)
        self._login()

    def _close_browser_context(self):
        if getattr(self, "context", None) is None:
            return
        results = Path("test-results")
        results.mkdir(exist_ok=True)
        self.context.tracing.stop(path=results / f"{self._testMethodName}.zip")
        self.context.close()
        self.context = None

    def _login(self):
        self.page.goto(f"{self.live_server_url}/accounts/login/")
        self.page.locator("#id_username").fill(self.user.email)
        self.page.locator("#id_password").fill(self.password)
        self.page.get_by_role("button", name="Log in").click()
        expect(self.page.get_by_role("heading", name="Dashboard")).to_be_visible()

    def _issued_invoice(self):
        invoice = create_invoice(
            company=self.company,
            project=self.project,
            invoice_data={
                "invoice_kind": Document.InvoiceKind.FINAL,
                "number": "I-E2E-001",
                "issue_date": timezone.localdate(),
                "due_date": timezone.localdate() + timedelta(days=30),
                "terms": "Due within 30 days.",
                "notes": "Browser test invoice.",
                "accept_payments": False,
            },
            populate_project_lines=False,
        )
        save_line_item(
            document=invoice,
            line_data={
                "description": "Design services",
                "rate": Decimal("100.00"),
                "quantity": Decimal("1.00"),
                "tax_rate": Decimal("0"),
            },
        )
        issue_document(document=invoice)
        invoice.refresh_from_db()
        return invoice

    def test_quick_note_routes_client_change_to_project_activity(self):
        body = "Move the slider to the materials side and review the basement door."
        self.page.locator("#id_project").focus()
        project_option = self.page.locator(f"#id_project option[value='{self.project.pk}']")
        expect(project_option).to_have_count(1)

        self.page.locator("#id_project").select_option(str(self.project.pk))
        self.page.locator("#id_activity_type").select_option(Note.ActivityType.CLIENT_CHANGE)
        self.page.locator("#id_source_type").select_option(Note.SourceType.EMAIL)
        self.page.locator("#id_body").fill(body)
        self.page.get_by_role("button", name="Save update").click()

        expect(self.page.get_by_text("Project update captured.")).to_be_visible()
        self.page.goto(f"{self.live_server_url}/projects/{self.project.pk}/#project-activity")
        expect(self.page.get_by_role("heading", name="Project activity")).to_be_visible()
        expect(
            self.page.locator("#project-activity article.note-row > div:nth-child(2)")
        ).to_have_text(body)
        note = Note.objects.get(project=self.project)
        self.assertEqual(note.status, Note.Status.ACTION_REQUIRED)
        self.assertEqual(note.source_type, Note.SourceType.EMAIL)

    def test_manual_payment_and_refund_reconcile_visible_invoice_state(self):
        invoice = self._issued_invoice()
        self.page.goto(f"{self.live_server_url}/invoices/{invoice.pk}/")

        self.page.get_by_role("link", name="Record payment").click()
        self.page.get_by_label("Amount").fill("100.00")
        self.page.get_by_label("Method").select_option(Payment.Method.CHECK)
        self.page.get_by_label("Received at").fill(timezone.localdate().isoformat())
        self.page.locator("#id_reference").fill("Browser check 1001")
        self.page.get_by_role("button", name="Record payment").click()

        expect(self.page.locator(".page-heading .eyebrow")).to_contain_text("Paid")
        expect(self.page.get_by_text("Browser check 1001")).to_be_visible()
        self.page.get_by_role("link", name="Record refund").click()
        self.page.get_by_label("Refund amount").fill("25.00")
        self.page.get_by_label("Refund date").fill(timezone.localdate().isoformat())
        self.page.locator("#id_reference").fill("Browser refund 1001")
        self.page.get_by_role("button", name="Record refund").click()

        expect(self.page.locator(".page-heading .eyebrow")).to_contain_text(
            "Partially paid"
        )
        expect(self.page.get_by_text("$25.00 refunded")).to_be_visible()
        expect(self.page.get_by_text("Browser refund 1001")).to_be_visible()
        payment = invoice.payments.get()
        self.assertEqual(payment.refunded_amount, Decimal("25.00"))
        self.assertEqual(payment.refunds.count(), 1)
