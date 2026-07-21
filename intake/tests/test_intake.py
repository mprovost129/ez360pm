from django.test import TestCase
from django.urls import reverse

from accounts.models import Company, User
from clients.models import Client
from clients.tests.test_clients import create_client
from intake.forms import NoteForm
from intake.models import Note
from projects.services import create_project
from projects.tests.test_projects import project_data


class NoteWorkflowTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.client.force_login(self.user)

    def test_quick_add_requires_only_body_and_preserves_text(self):
        response = self.client.post(
            reverse("intake:quick-add"),
            {"body": "Call from Morgan about a porch addition.", "next": "/"},
        )

        self.assertRedirects(response, reverse("core:home"))
        note = Note.objects.get()
        self.assertEqual(note.company, self.company)
        self.assertEqual(note.body, "Call from Morgan about a porch addition.")
        self.assertFalse(note.is_archived)

    def test_quick_add_rejects_external_next_url(self):
        response = self.client.post(
            reverse("intake:quick-add"),
            {"body": "Safe redirect", "next": "https://malicious.example/"},
        )

        self.assertRedirects(response, reverse("intake:list"))

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

    def test_other_company_note_is_not_visible_or_editable(self):
        Note.objects.create(company=self.company, body="Visible note")
        hidden = Note.objects.create(company=self.other_company, body="Hidden note")

        list_response = self.client.get(reverse("intake:list"))
        edit_response = self.client.get(reverse("intake:update", args=(hidden.pk,)))

        self.assertContains(list_response, "Visible note")
        self.assertNotContains(list_response, "Hidden note")
        self.assertEqual(edit_response.status_code, 404)

