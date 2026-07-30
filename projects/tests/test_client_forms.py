import tempfile
from types import SimpleNamespace

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Company, User
from assistant.tools import project_summary
from clients.tests.test_clients import create_client
from projects.client_form_services import create_project_client_form
from projects.models import (
    ClientFormQuestion,
    ClientFormTemplate,
    ProjectClientForm,
    ProjectFormAnswer,
    ProjectFormUpload,
)
from projects.services import create_project
from projects.tests.test_projects import project_data


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="forms@example.com",
    PUBLIC_BASE_URL="https://app.example.com",
)
class ClientFormWorkflowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._media_directory = tempfile.TemporaryDirectory()
        cls._media_settings = override_settings(MEDIA_ROOT=cls._media_directory.name)
        cls._media_settings.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_settings.disable()
        cls._media_directory.cleanup()

    def setUp(self):
        self.company = Company.objects.create(
            name="Provost Home Design",
            email="office@example.com",
        )
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.project = create_project(
            company=self.company,
            client=create_client(self.company),
            project_data=project_data(number="FORM-001"),
        )
        self.template = ClientFormTemplate.objects.create(
            company=self.company,
            name="Initial project questionnaire",
            welcome_message="Help us prepare for your project.",
            estimated_minutes=10,
        )
        self.name_question = ClientFormQuestion.objects.create(
            template=self.template,
            section="Owner information",
            label="Legal owner name",
            field_type=ClientFormQuestion.FieldType.SHORT_TEXT,
            required=True,
            order=1,
        )
        self.style_question = ClientFormQuestion.objects.create(
            template=self.template,
            section="Design",
            label="Preferred styles",
            field_type=ClientFormQuestion.FieldType.MULTI_SELECT,
            options=["Traditional", "Modern", "Farmhouse"],
            order=2,
        )
        self.client.force_login(self.user)

    def send_form(self):
        contact = self.project.client.primary_contact
        response = self.client.post(
            reverse("projects:client-form-create", args=(self.project.pk,)),
            {
                "template": self.template.pk,
                "recipient_name": contact.get_full_name(),
                "recipient_email": contact.email,
                "email_subject": "Your project questionnaire",
                "email_message": "Please complete this before our next meeting.",
            },
        )
        project_form = ProjectClientForm.objects.get(project=self.project)
        self.assertRedirects(
            response,
            reverse(
                "projects:client-form-detail",
                args=(self.project.pk, project_form.pk),
            ),
        )
        return project_form

    def test_project_form_is_snapshotted_and_emailed_with_branded_link(self):
        project_form = self.send_form()

        self.assertEqual(project_form.status, ProjectClientForm.Status.SENT)
        self.assertEqual(project_form.email_status, ProjectClientForm.EmailStatus.SENT)
        self.assertEqual(project_form.email_deliveries.count(), 1)
        self.assertEqual(project_form.email_deliveries.get().provider, "django")
        self.assertEqual(project_form.questions.count(), 2)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Provost Home Design", mail.outbox[0].alternatives[0].content)
        self.assertIn(
            f"https://app.example.com/f/{project_form.public_token}/",
            mail.outbox[0].body,
        )

        self.name_question.label = "Changed template question"
        self.name_question.save(update_fields=["label"])
        self.assertEqual(
            project_form.questions.order_by("order").first().label,
            "Legal owner name",
        )

    def test_client_can_save_progress_then_submit_required_answers(self):
        project_form = self.send_form()
        public_url = reverse("public-project-form", args=(project_form.public_token,))
        self.client.logout()

        opened = self.client.get(public_url)
        self.assertContains(opened, "Help us prepare for your project.")
        project_form.refresh_from_db()
        self.assertEqual(project_form.status, ProjectClientForm.Status.VIEWED)

        first, second = project_form.questions.order_by("order")
        saved = self.client.post(
            public_url,
            {
                "action": "save",
                f"question_{first.pk}": "",
                f"question_{second.pk}": ["Modern"],
            },
        )
        self.assertRedirects(saved, f"{public_url}?saved=1")
        self.assertEqual(second.answer.value, ["Modern"])

        incomplete = self.client.post(
            public_url,
            {
                "action": "submit",
                f"question_{first.pk}": "",
                f"question_{second.pk}": ["Modern"],
            },
        )
        self.assertEqual(incomplete.status_code, 400)
        self.assertContains(incomplete, "This field is required", status_code=400)

        submitted = self.client.post(
            public_url,
            {
                "action": "submit",
                f"question_{first.pk}": "Alex and Jamie Smith",
                f"question_{second.pk}": ["Modern", "Farmhouse"],
            },
        )
        self.assertRedirects(submitted, public_url)
        project_form.refresh_from_db()
        self.assertEqual(project_form.status, ProjectClientForm.Status.SUBMITTED)
        self.assertIsNotNone(project_form.submitted_at)
        self.assertIsNotNone(project_form.submission_notified_at)
        self.assertEqual(ProjectFormAnswer.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].to, [self.company.email])

        self.client.force_login(self.user)
        specifications = self.client.get(
            reverse("projects:specifications", args=(self.project.pk,))
        )
        self.assertContains(specifications, "Alex and Jamie Smith")
        self.assertContains(specifications, "Modern, Farmhouse")
        ai_summary = project_summary(
            SimpleNamespace(company=self.company),
            {"project_reference": self.project.number},
        )
        self.assertEqual(
            ai_summary["specifications"]["forms"][0]["answers"][0]["answer"],
            "Alex and Jamie Smith",
        )

    def test_required_questions_and_company_boundaries_are_enforced(self):
        empty_template = ClientFormTemplate.objects.create(
            company=self.company,
            name="Empty template",
        )
        contact = self.project.client.primary_contact
        response = self.client.post(
            reverse("projects:client-form-create", args=(self.project.pk,)),
            {
                "template": empty_template.pk,
                "recipient_name": contact.get_full_name(),
                "recipient_email": contact.email,
                "email_subject": "",
                "email_message": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add at least one question")
        self.assertFalse(ProjectClientForm.objects.exists())

        other_company = Company.objects.create(name="Other company")
        other_user = User.objects.create_user(
            "other@example.com",
            "Strong-Test-Password-483!",
            company=other_company,
        )
        self.client.force_login(other_user)
        self.assertEqual(
            self.client.get(
                reverse("projects:form-template-detail", args=(self.template.pk,))
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("projects:client-form-create", args=(self.project.pk,))
            ).status_code,
            404,
        )

    def test_settings_can_add_modify_and_reorder_template_questions(self):
        created = self.client.post(
            reverse("projects:form-question-create", args=(self.template.pk,)),
            {
                "section": "Budget",
                "label": "Budget range",
                "help_text": "Select the closest range.",
                "field_type": ClientFormQuestion.FieldType.SELECT,
                "required": "on",
                "options_text": "$250k-$500k\n$500k-$750k",
            },
        )
        self.assertRedirects(
            created,
            reverse("projects:form-template-detail", args=(self.template.pk,)),
        )
        budget = self.template.questions.get(label="Budget range")
        self.assertEqual(budget.options, ["$250k-$500k", "$500k-$750k"])
        self.assertEqual(budget.order, 3)

        moved = self.client.post(
            reverse(
                "projects:form-question-move",
                args=(self.template.pk, budget.pk, "up"),
            )
        )
        self.assertRedirects(
            moved,
            reverse("projects:form-template-detail", args=(self.template.pk,)),
        )
        self.assertEqual(
            list(self.template.questions.order_by("order").values_list("label", flat=True)),
            ["Legal owner name", "Budget range", "Preferred styles"],
        )

    def test_draft_public_link_is_inactive_and_submitted_form_is_locked(self):
        contact = self.project.client.primary_contact
        project_form = create_project_client_form(
            project=self.project,
            template=self.template,
            data={
                "recipient_name": contact.get_full_name(),
                "recipient_email": contact.email,
                "email_subject": "",
                "email_message": "",
            },
        )
        public_url = reverse("public-project-form", args=(project_form.public_token,))
        self.client.logout()
        self.assertEqual(self.client.get(public_url).status_code, 404)

        ProjectClientForm.objects.filter(pk=project_form.pk).update(
            status=ProjectClientForm.Status.SUBMITTED
        )
        self.assertContains(self.client.get(public_url), "Thank you")
        self.assertEqual(self.client.post(public_url, {"action": "save"}).status_code, 404)

    def test_file_upload_is_validated_stored_privately_and_download_is_company_scoped(self):
        ClientFormQuestion.objects.create(
            template=self.template,
            section="Existing conditions",
            label="Plans or site photos",
            field_type=ClientFormQuestion.FieldType.FILE,
            required=True,
            order=3,
        )
        project_form = self.send_form()
        first, _second, upload_question = project_form.questions.order_by("order")
        public_url = reverse("public-project-form", args=(project_form.public_token,))
        self.client.logout()

        missing = self.client.post(
            public_url,
            {"action": "submit", f"question_{first.pk}": "Alex Smith"},
        )
        self.assertEqual(missing.status_code, 400)
        self.assertContains(missing, "This field is required", status_code=400)

        invalid = self.client.post(
            public_url,
            {
                "action": "save",
                f"question_{upload_question.pk}": SimpleUploadedFile(
                    "malware.exe", b"not an executable", content_type="application/octet-stream"
                ),
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertContains(invalid, "Upload a PDF", status_code=400)

        submitted = self.client.post(
            public_url,
            {
                "action": "submit",
                f"question_{first.pk}": "Alex Smith",
                f"question_{upload_question.pk}": SimpleUploadedFile(
                    "Plans Final.pdf", b"%PDF-1.4 test plan", content_type="application/pdf"
                ),
            },
        )
        self.assertRedirects(submitted, public_url)
        upload = ProjectFormUpload.objects.get(question=upload_question)
        self.assertEqual(upload.original_name, "Plans Final.pdf")
        self.assertNotIn("Plans Final", upload.file.name)
        self.assertIn(f"company_{self.company.pk}", upload.file.name)

        download_url = reverse(
            "projects:client-form-upload-download",
            args=(self.project.pk, project_form.pk, upload.pk),
        )
        self.assertEqual(self.client.get(download_url).status_code, 302)

        other_company = Company.objects.create(name="Other company")
        other_user = User.objects.create_user(
            "other-upload@example.com",
            "Strong-Test-Password-483!",
            company=other_company,
        )
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(download_url).status_code, 404)

        self.client.force_login(self.user)
        downloaded = self.client.get(download_url)
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", downloaded["Content-Disposition"])
        self.assertEqual(b"".join(downloaded.streaming_content), b"%PDF-1.4 test plan")
        summary = project_summary(
            SimpleNamespace(company=self.company),
            {"project_reference": self.project.number},
        )
        file_answer = summary["specifications"]["forms"][0]["answers"][-1]["answer"]
        self.assertEqual(file_answer["file_name"], "Plans Final.pdf")

    def test_owner_can_revoke_and_restore_public_form_link(self):
        project_form = self.send_form()
        public_url = reverse("public-project-form", args=(project_form.public_token,))
        revoke_url = reverse(
            "projects:client-form-access",
            args=(self.project.pk, project_form.pk, "revoke"),
        )
        restore_url = reverse(
            "projects:client-form-access",
            args=(self.project.pk, project_form.pk, "restore"),
        )

        self.client.post(revoke_url)
        project_form.refresh_from_db()
        self.assertIsNotNone(project_form.revoked_at)
        self.client.logout()
        self.assertEqual(self.client.get(public_url).status_code, 404)

        self.client.force_login(self.user)
        self.client.post(restore_url)
        project_form.refresh_from_db()
        self.assertIsNone(project_form.revoked_at)
        self.client.logout()
        self.assertEqual(self.client.get(public_url).status_code, 200)
