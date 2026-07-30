import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Company, User
from clients.models import Client
from clients.tests.test_clients import create_client
from intake.forms import NoteForm
from intake.models import ActivityItem, Note, NoteAttachment
from projects.models import Project
from projects.services import create_project
from projects.tests.test_projects import project_data


class NoteWorkflowTests(TestCase):
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
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.client.force_login(self.user)

    def test_quick_add_captures_prospect_identity_and_preserves_text(self):
        response = self.client.post(
            reverse("intake:quick-add"),
            {
                "contact_first_name": "Morgan",
                "contact_last_name": "Taylor",
                "prospect_company_name": "Taylor Household",
                "body": "Call from Morgan about a porch addition.",
                "next": "/",
            },
        )

        self.assertRedirects(response, reverse("core:home"))
        note = Note.objects.get()
        self.assertEqual(note.company, self.company)
        self.assertEqual(note.contact_first_name, "Morgan")
        self.assertEqual(note.contact_last_name, "Taylor")
        self.assertEqual(note.prospect_company_name, "Taylor Household")
        self.assertEqual(note.body, "Call from Morgan about a porch addition.")
        self.assertFalse(note.is_archived)

    def test_quick_add_still_requires_only_note_body(self):
        response = self.client.post(
            reverse("intake:quick-add"),
            {"body": "Name not captured yet.", "next": "/"},
        )

        self.assertRedirects(response, reverse("core:home"))
        self.assertEqual(Note.objects.get().body, "Name not captured yet.")

    def test_invalid_quick_add_preserves_entered_details(self):
        response = self.client.post(
            reverse("intake:quick-add"),
            {
                "contact_first_name": "Morgan",
                "contact_last_name": "Taylor",
                "prospect_company_name": "Taylor Household",
                "body": "",
                "next": "/",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["quick_note_form"]
        self.assertTrue(form.is_bound)
        self.assertEqual(form["contact_first_name"].value(), "Morgan")
        self.assertEqual(form["contact_last_name"].value(), "Taylor")
        self.assertEqual(form["prospect_company_name"].value(), "Taylor Household")
        self.assertIn("body", form.errors)

    def test_quick_add_rejects_external_next_url(self):
        response = self.client.post(
            reverse("intake:quick-add"),
            {"body": "Safe redirect", "next": "https://malicious.example/"},
        )

        self.assertRedirects(response, reverse("intake:list"))

    def test_open_and_archived_note_views_are_separate_and_company_scoped(self):
        open_note = Note.objects.create(company=self.company, body="Open inquiry")
        archived_note = Note.objects.create(
            company=self.company,
            body="Archived inquiry",
            is_archived=True,
        )
        Note.objects.create(
            company=self.other_company,
            body="Other company archive",
            is_archived=True,
        )

        open_response = self.client.get(reverse("intake:list"))
        archived_response = self.client.get(
            reverse("intake:list"),
            {"archived": "1"},
        )

        self.assertEqual(list(open_response.context["notes"]), [open_note])
        self.assertContains(open_response, "Activity &amp; notes")
        self.assertContains(open_response, "Show archived")
        self.assertNotContains(open_response, "Archived inquiry")
        self.assertEqual(list(archived_response.context["notes"]), [archived_note])
        self.assertContains(archived_response, "Archived activity")
        self.assertContains(archived_response, "Show open")
        self.assertNotContains(archived_response, "Open inquiry")
        self.assertNotContains(archived_response, "Other company archive")

    def test_project_attachment_derives_client(self):
        client_record = create_client(self.company)
        project = create_project(
            company=self.company,
            client=client_record,
            project_data=project_data(number="ATTACH-1"),
        )
        note = Note.objects.create(company=self.company, body="Attach me")
        form = NoteForm(
            {"body": note.body, "project": project.pk, "client": ""},
            instance=note,
            company=self.company,
        )

        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.client, client_record)
        self.assertEqual(saved.project, project)

    def test_unrelated_client_and_project_are_rejected(self):
        first_client = create_client(self.company, company_name="First")
        second_client = create_client(self.company, company_name="Second", last_name="Two")
        project = create_project(
            company=self.company,
            client=first_client,
            project_data=project_data(number="ATTACH-2"),
        )
        note = Note(company=self.company, body="Mismatch")
        form = NoteForm(
            {
                "body": note.body,
                "project": project.pk,
                "client": second_client.pk,
            },
            instance=note,
            company=self.company,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("client", form.errors)

    def test_create_client_from_note_preserves_and_archives_note(self):
        note = Note.objects.create(
            company=self.company,
            body="Taylor called about renovating 20 Oak Street.",
        )

        response = self.client.post(
            reverse("intake:create-client", args=(note.pk,)),
            {
                "company_name": "Taylor Household",
                "billing_address_1": "20 Oak Street",
                "billing_address_2": "",
                "billing_city": "Richmond",
                "billing_state": "VA",
                "billing_postal_code": "23220",
                "billing_country": "United States",
                "internal_note": "",
                "contact_first_name": "Morgan",
                "contact_last_name": "Taylor",
                "contact_email": "morgan@example.com",
                "contact_phone": "555-0199",
                "archive_note": "on",
            },
        )

        client_record = Client.objects.get(company=self.company)
        self.assertRedirects(
            response,
            reverse("clients:detail", args=(client_record.pk,)),
        )
        note.refresh_from_db()
        self.assertEqual(note.body, "Taylor called about renovating 20 Oak Street.")
        self.assertEqual(note.client, client_record)
        self.assertTrue(note.is_archived)

    def test_client_conversion_is_prefilled_from_prospect_identity(self):
        note = Note.objects.create(
            company=self.company,
            contact_first_name="Morgan",
            contact_last_name="Taylor",
            prospect_company_name="Taylor Household",
            body="Porch addition inquiry.",
        )

        response = self.client.get(reverse("intake:create-client", args=(note.pk,)))

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial["contact_first_name"], "Morgan")
        self.assertEqual(form.initial["contact_last_name"], "Taylor")
        self.assertEqual(form.initial["company_name"], "Taylor Household")

    def test_client_conversion_can_attach_existing_client_without_duplicate(self):
        existing = create_client(self.company, company_name="Taylor Household")
        note = Note.objects.create(
            company=self.company,
            prospect_company_name="Taylor Household",
            body="Porch addition inquiry.",
        )

        response = self.client.post(
            reverse("intake:create-client", args=(note.pk,)),
            {
                "conversion_action": "use_existing",
                "client": existing.pk,
                "archive_note": "on",
            },
        )

        self.assertRedirects(response, reverse("clients:detail", args=(existing.pk,)))
        note.refresh_from_db()
        self.assertEqual(note.client, existing)
        self.assertTrue(note.is_archived)
        self.assertEqual(Client.objects.filter(company=self.company).count(), 1)

    def test_client_conversion_rejects_existing_client_from_other_company(self):
        hidden = create_client(self.other_company, company_name="Hidden Client")
        note = Note.objects.create(company=self.company, body="New inquiry.")

        response = self.client.post(
            reverse("intake:create-client", args=(note.pk,)),
            {
                "conversion_action": "use_existing",
                "client": hidden.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")
        note.refresh_from_db()
        self.assertIsNone(note.client_id)

    def test_client_conversion_can_continue_to_project(self):
        note = Note.objects.create(
            company=self.company,
            contact_first_name="Morgan",
            contact_last_name="Taylor",
            body="Porch addition inquiry.",
        )

        response = self.client.post(
            reverse("intake:create-client", args=(note.pk,)),
            {
                "company_name": "Taylor Household",
                "billing_address_1": "20 Oak Street",
                "billing_address_2": "",
                "billing_city": "Richmond",
                "billing_state": "VA",
                "billing_postal_code": "23220",
                "billing_country": "United States",
                "internal_note": "",
                "contact_first_name": "Morgan",
                "contact_last_name": "Taylor",
                "contact_email": "morgan@example.com",
                "contact_phone": "555-0199",
                "create_project": "on",
                "archive_note": "on",
            },
        )

        self.assertRedirects(response, reverse("intake:create-project", args=(note.pk,)))
        note.refresh_from_db()
        self.assertIsNotNone(note.client)
        self.assertFalse(note.is_archived)

    def test_create_project_from_note_prefills_and_attaches_note(self):
        client_record = create_client(self.company, company_name="Taylor Household")
        client_record.billing_address_1 = "20 Oak Street"
        client_record.billing_city = "Richmond"
        client_record.billing_state = "VA"
        client_record.billing_postal_code = "23220"
        client_record.save(
            update_fields=[
                "billing_address_1",
                "billing_city",
                "billing_state",
                "billing_postal_code",
            ]
        )
        note = Note.objects.create(
            company=self.company,
            client=client_record,
            body="Porch addition inquiry.",
        )

        get_response = self.client.get(reverse("intake:create-project", args=(note.pk,)))
        self.assertEqual(get_response.status_code, 200)
        form = get_response.context["form"]
        self.assertEqual(form.initial["client"], client_record.pk)
        self.assertEqual(form.initial["description"], note.body)
        self.assertEqual(form.initial["address_1"], "20 Oak Street")

        data = project_data(name="Porch addition", description=note.body)
        data["fixed_fee"] = ""
        data["archive_note"] = "on"
        post_response = self.client.post(
            reverse("intake:create-project", args=(note.pk,)),
            data,
        )

        project = Project.objects.get(company=self.company)
        self.assertRedirects(
            post_response,
            reverse("projects:detail", args=(project.pk,)),
        )
        note.refresh_from_db()
        self.assertEqual(note.client, client_record)
        self.assertEqual(note.project, project)
        self.assertTrue(note.is_archived)

    def test_other_company_note_is_not_visible_or_editable(self):
        Note.objects.create(company=self.company, body="Visible note")
        hidden = Note.objects.create(company=self.other_company, body="Hidden note")

        list_response = self.client.get(reverse("intake:list"))
        edit_response = self.client.get(reverse("intake:update", args=(hidden.pk,)))
        client_response = self.client.get(
            reverse("intake:create-client", args=(hidden.pk,))
        )
        project_response = self.client.get(
            reverse("intake:create-project", args=(hidden.pk,))
        )

        self.assertContains(list_response, "Visible note")
        self.assertNotContains(list_response, "Hidden note")
        self.assertEqual(edit_response.status_code, 404)
        self.assertEqual(client_response.status_code, 404)
        self.assertEqual(project_response.status_code, 404)

    def test_quick_email_change_is_structured_and_attached_directly_to_project(self):
        client_record = create_client(self.company, company_name="Arruda Household")
        project = create_project(
            company=self.company,
            client=client_record,
            project_data=project_data(number="ARRUDA-1"),
        )
        email_body = "Use a four-panel slider where the four windows are."

        response = self.client.post(
            reverse("intake:quick-add"),
            {
                "project": project.pk,
                "activity_type": Note.ActivityType.CLIENT_CHANGE,
                "source_type": Note.SourceType.EMAIL,
                "contact_first_name": "Rob",
                "contact_last_name": "Arruda",
                "prospect_company_name": "Marchon Eyewear, Inc",
                "source_email": "rob@example.com",
                "source_reference": "Materials-side walkout changes",
                "body": email_body,
                "next": reverse("projects:detail", args=(project.pk,)),
            },
        )

        self.assertRedirects(response, reverse("projects:detail", args=(project.pk,)))
        note = Note.objects.get()
        self.assertEqual(note.project, project)
        self.assertEqual(note.client, client_record)
        self.assertEqual(note.created_by, self.user)
        self.assertEqual(note.status, Note.Status.ACTION_REQUIRED)
        self.assertEqual(note.title, "Materials-side walkout changes")
        self.assertEqual(note.original_content, email_body)

        project_page = self.client.get(reverse("projects:detail", args=(project.pk,)))
        self.assertContains(project_page, "Project activity")
        self.assertContains(project_page, "Materials-side walkout changes")
        self.assertContains(project_page, "Action required")

    def test_quick_project_options_are_loaded_lazily_and_company_scoped(self):
        visible_client = create_client(self.company, company_name="Visible client")
        visible = create_project(
            company=self.company,
            client=visible_client,
            project_data=project_data(number="VISIBLE-1"),
        )
        hidden_client = create_client(self.other_company, company_name="Hidden client")
        hidden = create_project(
            company=self.other_company,
            client=hidden_client,
            project_data=project_data(number="HIDDEN-1"),
        )

        page = self.client.get(reverse("accounts:settings"))
        self.assertNotContains(page, visible.number)
        response = self.client.get(reverse("intake:project-options"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()["projects"]
        self.assertEqual([item["id"] for item in payload], [visible.pk])
        self.assertNotIn(hidden.number, str(payload))

    def test_project_activity_attachment_is_private_and_company_scoped(self):
        client_record = create_client(self.company)
        project = create_project(
            company=self.company,
            client=client_record,
            project_data=project_data(number="FILES-1"),
        )
        response = self.client.post(
            reverse("intake:create"),
            {
                "title": "Revised client sketch",
                "activity_type": Note.ActivityType.CLIENT_CHANGE,
                "status": Note.Status.ACTION_REQUIRED,
                "source_type": Note.SourceType.DOCUMENT,
                "body": "Review the revised opening layout.",
                "client": client_record.pk,
                "project": project.pk,
                "attachment": SimpleUploadedFile(
                    "Revised Layout.pdf",
                    b"%PDF-1.4 revised layout",
                    content_type="application/pdf",
                ),
            },
        )
        note = Note.objects.get()
        self.assertRedirects(response, reverse("intake:detail", args=(note.pk,)))
        attachment = NoteAttachment.objects.get(note=note)
        self.assertEqual(attachment.original_name, "Revised Layout.pdf")
        self.assertNotIn("Revised Layout", attachment.file.name)
        self.assertEqual(attachment.uploaded_by, self.user)

        download_url = reverse("intake:attachment-download", args=(attachment.pk,))
        self.client.logout()
        self.assertEqual(self.client.get(download_url).status_code, 302)

        other_user = User.objects.create_user(
            "other-files@example.com",
            "Strong-Test-Password-483!",
            company=self.other_company,
        )
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(download_url).status_code, 404)

        self.client.force_login(self.user)
        downloaded = self.client.get(download_url)
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", downloaded["Content-Disposition"])
        self.assertEqual(
            b"".join(downloaded.streaming_content),
            b"%PDF-1.4 revised layout",
        )

    def test_activity_resolution_records_actor_and_can_be_reopened(self):
        note = Note.objects.create(
            company=self.company,
            body="Confirm whether the existing door remains.",
            status=Note.Status.ACTION_REQUIRED,
        )
        resolved = self.client.post(
            reverse("intake:update-status", args=(note.pk, Note.Status.RESOLVED))
        )
        self.assertRedirects(resolved, reverse("intake:detail", args=(note.pk,)))
        note.refresh_from_db()
        self.assertEqual(note.status, Note.Status.RESOLVED)
        self.assertEqual(note.resolved_by, self.user)
        self.assertIsNotNone(note.resolved_at)

        self.client.post(reverse("intake:update-status", args=(note.pk, Note.Status.OPEN)))
        note.refresh_from_db()
        self.assertEqual(note.status, Note.Status.OPEN)
        self.assertIsNone(note.resolved_by)
        self.assertIsNone(note.resolved_at)

    def test_activity_action_items_are_independent_and_surface_when_due(self):
        client_record = create_client(self.company)
        project = create_project(
            company=self.company,
            client=client_record,
            project_data=project_data(number="ACTIONS-1"),
        )
        note = Note.objects.create(
            company=self.company,
            project=project,
            client=client_record,
            title="Client walkout changes",
            body="Several changes and questions from the client.",
            activity_type=Note.ActivityType.CLIENT_CHANGE,
            status=Note.Status.ACTION_REQUIRED,
        )
        due_on = timezone.localdate() - timedelta(days=1)

        added = self.client.post(
            reverse("intake:item-add", args=(note.pk,)),
            {
                "item_type": ActivityItem.ItemType.CHANGE,
                "title": "Replace four windows with a four-panel slider",
                "detail": "Confirm the rough opening before design development.",
                "status": ActivityItem.Status.OPEN,
                "due_on": due_on.isoformat(),
            },
        )
        self.assertRedirects(
            added,
            f"{reverse('intake:detail', args=(note.pk,))}#action-items",
        )
        item = ActivityItem.objects.get(note=note)
        self.assertEqual(item.created_by, self.user)
        self.assertEqual(item.order, 1)

        dashboard = self.client.get(reverse("core:home"))
        self.assertEqual(dashboard.context["activity_followup_count"], 1)
        self.assertEqual(dashboard.context["overdue_activity_followup_count"], 1)
        self.assertContains(dashboard, item.title)

        project_page = self.client.get(reverse("projects:detail", args=(project.pk,)))
        self.assertContains(project_page, "1 open action item")

        resolved = self.client.post(
            reverse(
                "intake:item-status",
                args=(note.pk, item.pk, ActivityItem.Status.RESOLVED),
            )
        )
        self.assertRedirects(
            resolved,
            f"{reverse('intake:detail', args=(note.pk,))}#action-items",
        )
        item.refresh_from_db()
        self.assertEqual(item.resolved_by, self.user)
        self.assertIsNotNone(item.resolved_at)
        dashboard = self.client.get(reverse("core:home"))
        self.assertEqual(dashboard.context["activity_followup_count"], 0)
