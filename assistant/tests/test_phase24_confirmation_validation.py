from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Company, User
from assistant.models import AIActionAttempt, AIEvent
from assistant.policies import get_company_policy
from assistant.services import run_assistant
from clients.services import create_client_with_primary_contact


class ProviderThatMustNotRun:
    name = "must-not-run"
    model = "must-not-run"

    def create_response(self, **kwargs):
        del kwargs
        raise AssertionError("The local client template must not call OpenAI.")


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    AI_RATE_LIMIT_REQUESTS=100,
    AI_MONTHLY_COST_LIMIT_USD=Decimal("25.00"),
)
class ConfirmationValidationOutcomeTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.client.force_login(self.user)

    @staticmethod
    def _template():
        return """Create this client:
Company/household: Standring Household
Contact first name: Andrew
Contact last name: Standring
Email: andrew@example.com
Phone: 508-555-0199
Billing address 1: 10 Main Street
Billing address 2:
City: Swansea
State: MA
Postal code: 02777
Country: United States
Internal note:
"""

    def _create_duplicate(self):
        return create_client_with_primary_contact(
            company=self.company,
            client_data={
                "company_name": "Existing Household",
                "billing_address_1": "",
                "billing_address_2": "",
                "billing_city": "",
                "billing_state": "",
                "billing_postal_code": "",
                "billing_country": "",
                "internal_note": "",
            },
            contact_data={
                "first_name": "Existing",
                "last_name": "Client",
                "email": "andrew@example.com",
                "phone": "",
            },
        )

    def test_validation_message_is_clean_without_python_list_formatting(self):
        self._create_duplicate()

        result = run_assistant(
            user=self.user,
            provider=ProviderThatMustNotRun(),
            prompt=self._template(),
        )

        self.assertIn("already exists", result.message.lower())
        self.assertFalse(result.message.startswith("["))
        self.assertFalse(result.message.endswith("]"))

    def test_confirmation_validation_is_needs_correction_not_failure(self):
        policy = get_company_policy(self.company)
        policy.failure_threshold = 1
        policy.auto_pause_on_failures = True
        policy.save(
            update_fields=[
                "failure_threshold",
                "auto_pause_on_failures",
                "updated_at",
            ]
        )
        prepared = run_assistant(
            user=self.user,
            provider=ProviderThatMustNotRun(),
            prompt=self._template(),
        )
        token = prepared.pending_actions[0]["token"]
        self._create_duplicate()

        response = self.client.post(
            reverse("assistant:confirm-action", kwargs={"token": token}),
            data="{}",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertIn("already exists", payload["error"].lower())
        self.assertEqual(payload["action_status"], AIActionAttempt.Status.BLOCKED)
        self.assertTrue(payload["remove_action"])
        attempt = AIActionAttempt.objects.get(confirmation_token=token)
        self.assertEqual(attempt.status, AIActionAttempt.Status.BLOCKED)
        self.assertEqual(attempt.error_code, "domain_validation")
        self.assertFalse(
            AIEvent.objects.filter(
                action_attempt=attempt,
                event_type=AIEvent.Type.TOOL_FAILURE,
            ).exists()
        )
        self.assertTrue(
            AIEvent.objects.filter(
                action_attempt=attempt,
                event_type=AIEvent.Type.CORRECTION_REQUESTED,
            ).exists()
        )
        policy.refresh_from_db()
        self.assertIsNone(policy.suspended_at)
