from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from accounts.models import Company, User
from assistant.models import AIInteraction
from assistant.registry import ActionContext, registry
from assistant.schema import ToolInputError
from clients.models import Client, Contact
from clients.tests.test_clients import create_client
from intake.models import Note
from projects.models import Project
from projects.services import create_project
from projects.tests.test_projects import project_data


@override_settings(AI_ASSISTANT_ENABLED=True)
class AssistantPhaseThreeTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.interaction = AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="test",
            model="test-model",
            prompt_summary="phase three",
        )
        self.context = ActionContext(user=self.user, interaction=self.interaction)

    def _prepare(self, name, arguments):
        return registry.invoke(
            context=self.context,
            name=name,
            arguments=arguments,
        ).pending_action

    def _client_create_arguments(self, **overrides):
        data = {
            "company_name": "Taylor Household",
            "contact_first_name": "Morgan",
            "contact_last_name": "Taylor",
            "contact_email": "morgan@example.com",
            "contact_phone": "555-0144",
            "billing_address_1": "20 Oak Street",
            "billing_address_2": "",
            "billing_city": "Swansea",
            "billing_state": "MA",
            "billing_postal_code": "02777",
            "billing_country": "United States",
            "internal_note": "Referred by Pat.",
        }
        data.update(overrides)
        return data

    def _project_create_arguments(self, client_reference, **overrides):
        data = {
            "client_reference": client_reference,
            "number": None,
            "name": "Oak Street Addition",
            "description": "Residential addition design.",
            "address_1": "20 Oak Street",
            "address_2": "",
            "city": "Swansea",
            "state": "MA",
            "postal_code": "02777",
            "municipality": "Swansea",
            "parcel_id": "",
            "billing_type": "flat_fee",
            "hourly_rate": None,
            "fixed_fee": 4500,
            "estimated_hours": 35,
        }
        data.update(overrides)
        return data

    def _update_client_arguments(self, reference, **changes):
        data = {
            "client_reference": reference,
            "company_name": None,
            "billing_address_1": None,
            "billing_address_2": None,
            "billing_city": None,
            "billing_state": None,
            "billing_postal_code": None,
            "billing_country": None,
            "internal_note": None,
        }
        data.update(changes)
        return data

    def _update_project_arguments(self, reference, **changes):
        data = {
            "project_reference": reference,
            "client_reference": None,
            "number": None,
            "name": None,
            "description": None,
            "address_1": None,
            "address_2": None,
            "city": None,
            "state": None,
            "postal_code": None,
            "municipality": None,
            "parcel_id": None,
            "billing_type": None,
            "hourly_rate": None,
            "fixed_fee": None,
            "estimated_hours": None,
        }
        data.update(changes)
        return data

    def test_create_client_requires_confirmation_and_uses_domain_service(self):
        attempt = self._prepare("create_client", self._client_create_arguments())

        self.assertEqual(Client.objects.count(), 0)
        self.assertEqual(attempt.preview["title"], "Create client")

        result = registry.execute_attempt(attempt=attempt)

        client = Client.objects.get(company=self.company)
        self.assertEqual(client.display_name, "Taylor Household")
        self.assertEqual(client.primary_contact.email, "morgan@example.com")
        self.assertIn("created", result["message"])

    def test_create_client_blocks_exact_email_duplicate(self):
        create_client(self.company, company_name="Existing", last_name="Taylor")

        with self.assertRaisesMessage(ValidationError, "same email or phone"):
            self._prepare(
                "create_client",
                self._client_create_arguments(contact_email="taylor@example.com"),
            )

    def test_update_client_preserves_omitted_fields_and_detects_stale_preview(self):
        client = create_client(self.company, company_name="Taylor Household")
        client.billing_city = "Swansea"
        client.internal_note = "Keep this"
        client.save(update_fields=["billing_city", "internal_note"])
        attempt = self._prepare(
            "update_client",
            self._update_client_arguments("Taylor Household", billing_city="Rehoboth"),
        )

        client.company_name = "Changed elsewhere"
        client.save(update_fields=["company_name"])
        # The preview only locked billing_city, so an unrelated change is safe.
        registry.execute_attempt(attempt=attempt)
        client.refresh_from_db()
        self.assertEqual(client.billing_city, "Rehoboth")
        self.assertEqual(client.company_name, "Changed elsewhere")
        self.assertEqual(client.internal_note, "Keep this")

        stale = self._prepare(
            "update_client",
            self._update_client_arguments(str(client.pk), billing_city="Somerset"),
        )
        client.billing_city = "Seekonk"
        client.save(update_fields=["billing_city"])
        with self.assertRaisesMessage(ValidationError, "changed after the AI preview"):
            registry.execute_attempt(attempt=stale)

    def test_partial_contact_can_be_created_without_email_or_phone(self):
        client = create_client(self.company, company_name="Taylor Household")
        attempt = self._prepare(
            "add_contact",
            {
                "client_reference": str(client.pk),
                "first_name": "Casey",
                "last_name": "Taylor",
                "email": "",
                "phone": "",
                "is_primary": False,
            },
        )

        registry.execute_attempt(attempt=attempt)

        contact = Contact.objects.get(first_name="Casey")
        self.assertEqual(contact.email, "")
        self.assertEqual(contact.phone, "")
        self.assertFalse(contact.is_primary)

    def test_other_company_contact_cannot_be_updated(self):
        hidden_client = create_client(self.other_company, company_name="Hidden")
        hidden_contact = hidden_client.primary_contact

        with self.assertRaisesMessage(ValidationError, "not found in this company"):
            self._prepare(
                "update_contact",
                {
                    "contact_id": hidden_contact.pk,
                    "first_name": "Changed",
                    "last_name": None,
                    "email": None,
                    "phone": None,
                    "is_primary": None,
                },
            )

    def test_create_project_requires_confirmation_and_creates_lead(self):
        client = create_client(self.company, company_name="Taylor Household")
        attempt = self._prepare(
            "create_project",
            self._project_create_arguments(str(client.pk)),
        )

        self.assertEqual(Project.objects.count(), 0)
        registry.execute_attempt(attempt=attempt)

        project = Project.objects.get(company=self.company)
        self.assertEqual(project.status, Project.Status.LEAD)
        self.assertEqual(project.fixed_fee, Decimal("4500"))
        self.assertIsNone(project.hourly_rate)

    def test_project_detail_updates_are_separate_from_status(self):
        client = create_client(self.company, company_name="Taylor Household")
        project = create_project(
            company=self.company,
            client=client,
            project_data=project_data(number="2607009"),
        )

        with self.assertRaises(ToolInputError):
            registry.invoke(
                context=self.context,
                name="update_project_details",
                arguments={
                    **self._update_project_arguments("2607009", name="Updated"),
                    "status": "active",
                },
            )

        details_attempt = self._prepare(
            "update_project_details",
            self._update_project_arguments("2607009", name="Updated project"),
        )
        registry.execute_attempt(attempt=details_attempt)
        project.refresh_from_db()
        self.assertEqual(project.name, "Updated project")
        self.assertEqual(project.status, Project.Status.LEAD)

        status_attempt = self._prepare(
            "change_project_status",
            {"project_reference": "2607009", "status": "active"},
        )
        registry.execute_attempt(attempt=status_attempt)
        project.refresh_from_db()
        self.assertEqual(project.status, Project.Status.ACTIVE)


    def test_primary_contact_change_is_explicit_and_preserves_both_contacts(self):
        client = create_client(self.company, company_name="Taylor Household")
        original = client.primary_contact
        second = Contact.objects.create(
            client=client,
            first_name="Casey",
            last_name="Taylor",
            email="casey@example.com",
            phone="",
            is_primary=False,
        )

        attempt = self._prepare(
            "set_primary_contact",
            {"contact_id": second.pk},
        )
        registry.execute_attempt(attempt=attempt)

        original.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(original.is_primary)
        self.assertTrue(second.is_primary)
        self.assertEqual(client.contacts.count(), 2)

    def test_invalid_project_billing_combination_is_rejected_before_confirmation(self):
        client = create_client(self.company, company_name="Taylor Household")

        with self.assertRaises(ValidationError):
            self._prepare(
                "create_project",
                self._project_create_arguments(
                    str(client.pk),
                    billing_type="flat_fee",
                    hourly_rate=175,
                    fixed_fee=4500,
                ),
            )

    def test_identical_prepared_action_reuses_idempotent_attempt(self):
        arguments = self._client_create_arguments()

        first = self._prepare("create_client", arguments)
        second = self._prepare("create_client", arguments)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.idempotency_key, second.idempotency_key)

    def test_intake_conversion_preserves_original_note(self):
        note = Note.objects.create(
            company=self.company,
            contact_first_name="Morgan",
            contact_last_name="Taylor",
            body="Morgan called about a 20 Oak Street addition.",
        )
        arguments = {
            "note_id": note.pk,
            **self._client_create_arguments(),
            **{
                key: value
                for key, value in self._project_create_arguments("unused").items()
                if key != "client_reference"
            },
            "archive_note": True,
        }
        attempt = self._prepare("create_client_and_project_from_note", arguments)

        registry.execute_attempt(attempt=attempt)

        note.refresh_from_db()
        self.assertEqual(
            note.body,
            "Morgan called about a 20 Oak Street addition.",
        )
        self.assertTrue(note.is_archived)
        self.assertIsNotNone(note.client_id)
        self.assertIsNotNone(note.project_id)
        self.assertEqual(note.project.client_id, note.client_id)
