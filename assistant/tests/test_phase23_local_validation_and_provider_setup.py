from decimal import Decimal

from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import Company, User
from assistant.local_actions import inspect_client_template
from assistant.models import AIInteraction
from assistant.policies import current_month_usage
from assistant.services import run_assistant


class LocalTemplateDecisionTests(SimpleTestCase):
    def test_incomplete_template_is_recognized_as_local_correction(self):
        decision = inspect_client_template(
            """Create this client:
Company/household: Standring Household
Contact first name: Andrew
Contact last name:
Email: andrew@example.com
"""
        )

        self.assertTrue(decision.matched)
        self.assertEqual(decision.tool_name, "create_client")
        self.assertIsNone(decision.action)
        self.assertIn("Contact last name", decision.error)

    def test_free_form_prompt_is_not_claimed_by_local_parser(self):
        decision = inspect_client_template("Add Andrew Standring as a client.")

        self.assertFalse(decision.matched)
        self.assertIsNone(decision.action)
        self.assertEqual(decision.error, "")


class ProviderThatMustNotRun:
    name = "must-not-run"
    model = "must-not-run"

    def __init__(self):
        self.calls = 0

    def create_response(self, **kwargs):
        del kwargs
        self.calls += 1
        raise AssertionError("Incomplete local templates must not call OpenAI.")


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    AI_RATE_LIMIT_REQUESTS=100,
    AI_MONTHLY_COST_LIMIT_USD=Decimal("25.00"),
)
class LocalValidationAndProviderSetupTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )

    def test_incomplete_template_returns_local_correction_without_provider_usage(self):
        provider = ProviderThatMustNotRun()
        prompt = """Create this client:
Company/household: Standring Household
Contact first name: Andrew
Contact last name:
Email: andrew@example.com
Phone: 508-555-0199
Billing address 1: 10 Main Street
City: Swansea
State: MA
Postal code: 02777
"""

        result = run_assistant(user=self.user, provider=provider, prompt=prompt)

        interaction = AIInteraction.objects.get(pk=result.interaction_id)
        self.assertEqual(provider.calls, 0)
        self.assertEqual(result.pending_actions, [])
        self.assertIn("Contact last name", result.message)
        self.assertEqual(interaction.provider, "local")
        self.assertEqual(interaction.status, AIInteraction.Status.BLOCKED)
        self.assertEqual(interaction.total_tokens, 0)
        self.assertEqual(current_month_usage(self.company)["requests"], 0)
        combined = f"{interaction.prompt_summary} {interaction.response_summary}".lower()
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

    @override_settings(OPENAI_API_KEY="", AI_PROVIDER="openai")
    def test_missing_provider_configuration_fails_safely_inside_interaction(self):
        result = run_assistant(
            user=self.user,
            prompt="Which invoices are overdue?",
        )

        interaction = AIInteraction.objects.get(pk=result.interaction_id)
        self.assertEqual(interaction.status, AIInteraction.Status.FAILED)
        self.assertEqual(interaction.error_code, "provider_not_configured")
        self.assertIn("not configured", result.message.lower())
        self.assertEqual(result.pending_actions, [])

    @override_settings(
        AI_MODEL="approved-model",
        AI_ALLOWED_MODELS=["approved-model"],
    )
    def test_invalid_model_configuration_returns_assistant_unavailable_not_server_error(self):
        from assistant.policies import get_company_policy
        from assistant.services import AssistantUnavailable

        policy = get_company_policy(self.company)
        policy.model_override = "not-allowlisted"
        policy.save(update_fields=["model_override", "updated_at"])

        with self.assertRaisesMessage(AssistantUnavailable, "not in the platform allowlist"):
            run_assistant(
                user=self.user,
                prompt="Which invoices are overdue?",
            )
