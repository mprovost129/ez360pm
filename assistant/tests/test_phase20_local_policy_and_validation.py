from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Company, User
from assistant.models import AIInteraction
from assistant.policies import evaluate_failure_circuit_breaker, get_company_policy
from assistant.services import run_assistant
from clients.services import create_client_with_primary_contact


class ProviderThatMustNotRun:
    name = "must-not-run"
    model = "must-not-run"

    def __init__(self):
        self.calls = 0

    def create_response(self, **kwargs):
        del kwargs
        self.calls += 1
        raise AssertionError("The local client template must not call OpenAI.")


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    AI_RATE_LIMIT_REQUESTS=100,
    AI_MONTHLY_COST_LIMIT_USD=Decimal("25.00"),
)
class LocalPolicyAndValidationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )

    @staticmethod
    def _template(email="andrew@example.com"):
        return f"""Create this client:
Company/household: Standring Household
Contact first name: Andrew
Contact last name: Standring
Email: {email}
Phone: 508-555-0199
Billing address 1: 10 Main Street
Billing address 2:
City: Swansea
State: MA
Postal code: 02777
Country: United States
Internal note:
"""


    def test_local_template_omits_customer_fields_from_interaction_summaries(self):
        provider = ProviderThatMustNotRun()

        result = run_assistant(
            user=self.user,
            provider=provider,
            prompt=self._template(),
        )

        interaction = AIInteraction.objects.get(pk=result.interaction_id)
        combined = f"{interaction.prompt_summary} {interaction.response_summary}".lower()
        self.assertEqual(provider.calls, 0)
        self.assertIn("field values omitted", combined)
        for sensitive_value in (
            "andrew",
            "standring",
            "andrew@example.com",
            "508-555-0199",
            "10 main street",
            "swansea",
            "02777",
        ):
            self.assertNotIn(sensitive_value, combined)

    def test_domain_validation_is_blocked_not_failed(self):
        create_client_with_primary_contact(
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
        provider = ProviderThatMustNotRun()

        result = run_assistant(
            user=self.user,
            provider=provider,
            prompt=self._template(),
        )

        interaction = AIInteraction.objects.get(pk=result.interaction_id)
        self.assertEqual(provider.calls, 0)
        self.assertEqual(interaction.status, AIInteraction.Status.BLOCKED)
        self.assertEqual(interaction.error_code, "domain_validation")
        self.assertIn("already exists", result.message.lower())

    def test_repeated_domain_validation_does_not_trip_circuit_breaker(self):
        policy = get_company_policy(self.company)
        policy.failure_threshold = 2
        policy.auto_pause_on_failures = True
        policy.save(update_fields=["failure_threshold", "auto_pause_on_failures", "updated_at"])
        for index in range(2):
            AIInteraction.objects.create(
                company=self.company,
                user=self.user,
                provider="local",
                model="deterministic-client-template-v1",
                prompt_summary=f"validation {index}",
                response_summary="Duplicate client.",
                status=AIInteraction.Status.FAILED,
                error_code="domain_validation",
                completed_at=timezone.now(),
            )

        self.assertFalse(evaluate_failure_circuit_breaker(policy))
        policy.refresh_from_db()
        self.assertIsNone(policy.suspended_at)

    def test_operational_failures_still_trip_circuit_breaker(self):
        policy = get_company_policy(self.company)
        policy.failure_threshold = 2
        policy.auto_pause_on_failures = True
        policy.save(update_fields=["failure_threshold", "auto_pause_on_failures", "updated_at"])
        for index in range(2):
            AIInteraction.objects.create(
                company=self.company,
                user=self.user,
                provider="openai",
                model="test-model",
                prompt_summary=f"failure {index}",
                response_summary="Provider failure.",
                status=AIInteraction.Status.FAILED,
                error_code="provider_timeout",
                completed_at=timezone.now(),
            )

        self.assertTrue(evaluate_failure_circuit_breaker(policy))
        policy.refresh_from_db()
        self.assertIsNotNone(policy.suspended_at)
