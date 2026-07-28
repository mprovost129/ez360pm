from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.models import Company, User
from assistant.local_actions import parse_client_template
from assistant.models import AIActionAttempt, AIInteraction
from assistant.policies import current_month_usage, get_company_policy
from assistant.registry import ActionContext, registry
from assistant.services import AssistantUnavailable, run_assistant
from clients.models import Client


class ClientTemplateParserTests(SimpleTestCase):
    def test_filled_client_template_parses_without_openai(self):
        action = parse_client_template(
            """Create this client:
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
Internal note: Referred by Mike.
"""
        )

        self.assertIsNotNone(action)
        self.assertEqual(action.tool_name, "create_client")
        self.assertEqual(action.arguments["contact_first_name"], "Andrew")
        self.assertEqual(action.arguments["contact_last_name"], "Standring")
        self.assertEqual(action.arguments["billing_city"], "Swansea")

    def test_incomplete_template_returns_none(self):
        self.assertIsNone(
            parse_client_template(
                """Create this client:
Contact first name: Andrew
Contact last name:
"""
            )
        )

    def test_free_form_request_is_not_parsed_locally(self):
        self.assertIsNone(parse_client_template("Add Andrew Standring as a client."))


class ProviderThatMustNotRun:
    name = "must-not-run"
    model = "must-not-run"

    def __init__(self):
        self.calls = 0

    def create_response(self, **kwargs):
        del kwargs
        self.calls += 1
        raise AssertionError("The structured client template must not call OpenAI.")


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    AI_RATE_LIMIT_REQUESTS=100,
    AI_MONTHLY_COST_LIMIT_USD=Decimal("25.00"),
    AI_INPUT_COST_PER_MILLION_USD=Decimal("1.00"),
    AI_OUTPUT_COST_PER_MILLION_USD=Decimal("2.00"),
)
class AssistantRetryAndLocalFastPathTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )


    def _filled_template(self):
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

    def _interaction(self, summary):
        return AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="test",
            model="test-model",
            prompt_summary=summary,
        )

    @staticmethod
    def _client_arguments():
        return {
            "company_name": "Standring Household",
            "contact_first_name": "Andrew",
            "contact_last_name": "Standring",
            "contact_email": "andrew@example.com",
            "contact_phone": "508-555-0199",
            "billing_address_1": "10 Main Street",
            "billing_address_2": "",
            "billing_city": "Swansea",
            "billing_state": "MA",
            "billing_postal_code": "02777",
            "billing_country": "United States",
            "internal_note": "",
        }

    def test_structured_template_prepares_confirmation_without_provider_call(self):
        provider = ProviderThatMustNotRun()

        result = run_assistant(
            user=self.user,
            provider=provider,
            prompt=self._filled_template(),
        )

        self.assertEqual(provider.calls, 0)
        self.assertEqual(Client.objects.count(), 0)
        self.assertEqual(len(result.pending_actions), 1)
        interaction = AIInteraction.objects.get()
        self.assertEqual(interaction.total_tokens, 0)
        self.assertEqual(interaction.estimated_cost_usd, Decimal("0"))
        self.assertEqual(current_month_usage(self.company)["requests"], 0)

    def test_identical_pending_action_is_reused_across_request_retries(self):
        first_context = ActionContext(
            user=self.user,
            interaction=self._interaction("first request"),
        )
        second_context = ActionContext(
            user=self.user,
            interaction=self._interaction("retry request"),
        )

        first = registry.invoke(
            context=first_context,
            name="create_client",
            arguments=self._client_arguments(),
        ).pending_action
        second_result = registry.invoke(
            context=second_context,
            name="create_client",
            arguments=self._client_arguments(),
        )

        self.assertEqual(second_result.pending_action.pk, first.pk)
        self.assertTrue(second_result.data["reused_pending_action"])
        self.assertEqual(AIActionAttempt.objects.count(), 1)

    def test_expired_pending_action_is_not_reused(self):
        first_context = ActionContext(
            user=self.user,
            interaction=self._interaction("first request"),
        )
        first = registry.invoke(
            context=first_context,
            name="create_client",
            arguments=self._client_arguments(),
        ).pending_action
        AIActionAttempt.objects.filter(pk=first.pk).update(
            confirmation_expires_at=timezone.now() - timedelta(seconds=1)
        )

        second = registry.invoke(
            context=ActionContext(
                user=self.user,
                interaction=self._interaction("retry after expiry"),
            ),
            name="create_client",
            arguments=self._client_arguments(),
        ).pending_action

        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(AIActionAttempt.objects.count(), 2)

    def test_local_template_remains_available_after_openai_request_limit(self):
        policy = get_company_policy(self.company)
        policy.monthly_request_limit = 1
        policy.save(update_fields=["monthly_request_limit", "updated_at"])
        AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="test-model",
            prompt_summary="provider-backed request",
            status=AIInteraction.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        provider = ProviderThatMustNotRun()

        result = run_assistant(
            user=self.user,
            provider=provider,
            prompt=self._filled_template(),
        )

        self.assertEqual(provider.calls, 0)
        self.assertEqual(len(result.pending_actions), 1)
        self.assertEqual(current_month_usage(self.company)["requests"], 1)

    def test_local_template_remains_available_after_openai_cost_limit(self):
        policy = get_company_policy(self.company)
        policy.monthly_cost_limit_usd = Decimal("0.01")
        policy.save(update_fields=["monthly_cost_limit_usd", "updated_at"])
        AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="test-model",
            prompt_summary="provider-backed request",
            status=AIInteraction.Status.COMPLETED,
            estimated_cost_usd=Decimal("0.01"),
            completed_at=timezone.now(),
        )
        provider = ProviderThatMustNotRun()

        result = run_assistant(
            user=self.user,
            provider=provider,
            prompt=self._filled_template(),
        )

        self.assertEqual(provider.calls, 0)
        self.assertEqual(len(result.pending_actions), 1)

    @override_settings(AI_MODEL="approved-model", AI_ALLOWED_MODELS=["approved-model"])
    def test_local_template_does_not_depend_on_provider_model_configuration(self):
        policy = get_company_policy(self.company)
        policy.model_override = "model-that-is-not-allowlisted"
        policy.save(update_fields=["model_override", "updated_at"])
        provider = ProviderThatMustNotRun()

        result = run_assistant(
            user=self.user,
            provider=provider,
            prompt=self._filled_template(),
        )

        self.assertEqual(provider.calls, 0)
        self.assertEqual(len(result.pending_actions), 1)

    def test_provider_backed_request_is_still_blocked_at_openai_request_limit(self):
        policy = get_company_policy(self.company)
        policy.monthly_request_limit = 1
        policy.save(update_fields=["monthly_request_limit", "updated_at"])
        AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="test-model",
            prompt_summary="provider-backed request",
            status=AIInteraction.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        provider = ProviderThatMustNotRun()

        with self.assertRaisesMessage(
            AssistantUnavailable,
            "monthly AI request allowance has been reached",
        ):
            run_assistant(
                user=self.user,
                provider=provider,
                prompt="Add Andrew Standring as a client.",
            )

        self.assertEqual(provider.calls, 0)

