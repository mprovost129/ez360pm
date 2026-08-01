import os
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from accounts.models import Company, User
from clients.services import create_client_with_primary_contact
from documents.models import Document, Payment
from documents.services import create_invoice, issue_document, save_line_item
from intake.models import Note
from projects.models import (
    ClientFormQuestion,
    ClientFormTemplate,
    Project,
    ProjectClientForm,
    ProjectFormUpload,
)
from projects.services import create_project

# Playwright's synchronous driver runs an event loop in this test process. The
# browser suite is isolated in its own command/job, while Django's live server
# handles requests on a separate thread, so synchronous fixture ORM access is
# intentional here and never enables this escape hatch in the application.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@override_settings(
    EMAIL_PROVIDER="django",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="browser-tests@example.test",
    PUBLIC_BASE_URL="http://localhost",
)
class CriticalWorkflowBrowserTests(StaticLiveServerTestCase):
    """Rendered-browser proof for workflows where several UI layers interact."""

    password = "Browser-Test-Password-483!"

    @classmethod
    def setUpClass(cls):
        cls._media_directory = tempfile.TemporaryDirectory()
        cls._media_settings = override_settings(MEDIA_ROOT=cls._media_directory.name)
        cls._media_settings.enable()
        super().setUpClass()
        try:
            cls.playwright = sync_playwright().start()
            launch_options = {
                "headless": os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0"
            }
            browser_channel = os.environ.get("PLAYWRIGHT_BROWSER_CHANNEL", "").strip()
            if browser_channel:
                launch_options["channel"] = browser_channel
            cls.browser = cls.playwright.chromium.launch(**launch_options)
        except Exception:
            super().tearDownClass()
            cls._media_settings.disable()
            cls._media_directory.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()
        cls._media_settings.disable()
        cls._media_directory.cleanup()

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
        self._browser_contexts = []
        self.context, self.page = self._new_browser_context("owner")
        self.addCleanup(self._close_browser_contexts)
        self._login()

    def _new_browser_context(self, trace_label):
        context = self.browser.new_context(
            viewport={"width": 1600, "height": 1000}
        )
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.set_default_timeout(10_000)
        self._browser_contexts.append((context, trace_label))
        return context, page

    def _close_browser_contexts(self):
        if not getattr(self, "_browser_contexts", None):
            return
        results = Path("test-results")
        results.mkdir(exist_ok=True)
        for context, trace_label in reversed(self._browser_contexts):
            context.tracing.stop(
                path=results / f"{self._testMethodName}-{trace_label}.zip"
            )
            context.close()
        self._browser_contexts = []
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

    def test_client_form_submission_and_upload_populate_project_specifications(self):
        template = ClientFormTemplate.objects.create(
            company=self.company,
            name="Initial project questionnaire",
            welcome_message="Help us prepare for your project.",
            estimated_minutes=10,
        )
        ClientFormQuestion.objects.create(
            template=template,
            section="Owner information",
            label="Legal owner name",
            field_type=ClientFormQuestion.FieldType.SHORT_TEXT,
            required=True,
            order=1,
        )
        ClientFormQuestion.objects.create(
            template=template,
            section="Design",
            label="Preferred styles",
            field_type=ClientFormQuestion.FieldType.MULTI_SELECT,
            options=["Traditional", "Modern", "Farmhouse"],
            order=2,
        )
        ClientFormQuestion.objects.create(
            template=template,
            section="Existing conditions",
            label="Plans or site photos",
            field_type=ClientFormQuestion.FieldType.FILE,
            required=True,
            order=3,
        )

        self.page.goto(f"{self.live_server_url}/projects/{self.project.pk}/")
        self.page.get_by_role("link", name="New form").first.click()
        send_form = self.page.locator("form.structured-form")
        send_form.get_by_label("Template").select_option(str(template.pk))
        send_form.get_by_label("Email subject").fill("Your project questionnaire")
        send_form.get_by_label("Email message").fill(
            "Please complete this before our next meeting."
        )
        send_form.get_by_role("button", name="Create & email form").click()

        expect(
            self.page.get_by_role("heading", name="Initial project questionnaire")
        ).to_be_visible()
        expect(self.page.locator(".page-heading .eyebrow")).to_contain_text("Sent")
        project_form = ProjectClientForm.objects.get(project=self.project)
        self.assertEqual(project_form.status, ProjectClientForm.Status.SENT)

        client_context, client_page = self._new_browser_context("client")
        self.assertNotEqual(client_context, self.context)
        client_page.goto(
            f"{self.live_server_url}/f/{project_form.public_token}/"
        )
        expect(
            client_page.get_by_role("heading", name="Initial project questionnaire")
        ).to_be_visible()
        expect(client_page.get_by_text("Help us prepare for your project.")).to_be_visible()
        client_page.get_by_label("Legal owner name").fill("Alex and Jamie Smith")
        client_page.get_by_label("Modern").check()
        client_page.get_by_label("Farmhouse").check()
        client_page.get_by_label("Plans or site photos").set_input_files(
            {
                "name": "Plans Final.pdf",
                "mimeType": "application/pdf",
                "buffer": b"%PDF-1.4 browser test plan",
            }
        )
        client_page.get_by_role("button", name="Submit completed form").click()
        expect(client_page.get_by_role("heading", name="Thank you")).to_be_visible()

        self.page.goto(
            f"{self.live_server_url}/projects/{self.project.pk}/specifications/"
        )
        expect(self.page.get_by_role("heading", name="Project specifications")).to_be_visible()
        expect(self.page.get_by_text("Alex and Jamie Smith")).to_be_visible()
        expect(self.page.get_by_text("Modern, Farmhouse")).to_be_visible()
        expect(self.page.get_by_role("link", name="Plans Final.pdf")).to_be_visible()

        project_form.refresh_from_db()
        self.assertEqual(project_form.status, ProjectClientForm.Status.SUBMITTED)
        upload = ProjectFormUpload.objects.get(
            question__project_form=project_form
        )
        self.assertEqual(upload.original_name, "Plans Final.pdf")
