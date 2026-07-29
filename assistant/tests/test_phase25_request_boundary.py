from decimal import Decimal

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import Company, User
from assistant.local_actions import inspect_client_template
from assistant.providers import ProviderResponse
from assistant.services import AssistantRateLimited, run_assistant


class MessageProvider:
    name = "test"
    model = "test-model"

    def __init__(self):
        self.calls = 0

    def create_response(self, *, input_items, instructions, tools):
        del input_items, instructions, tools
        self.calls += 1
        return ProviderResponse(
            {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "Nothing urgent."}
                        ],
                    }
                ],
                "usage": {"input_tokens": 5, "output_tokens": 3},
            }
        )


class ProviderThatMustNotRun:
    name = "must-not-run"
    model = "must-not-run"

    def create_response(self, **kwargs):
        del kwargs
        raise AssertionError("The deterministic client template must not call OpenAI.")


class LocalTemplateMultilineTests(SimpleTestCase):
    def test_multiline_internal_note_is_preserved(self):
        decision = inspect_client_template(
            """Create this client:
Company/household: Standring Household
Contact first name: Andrew
Contact last name: Standring
Email:
Phone:
Billing address 1:
Billing address 2:
City:
State:
Postal code:
Country:
Internal note: Called about a new addition.
Needs a site visit before pricing.
Follow up next Tuesday.
"""
        )

        self.assertTrue(decision.matched)
        self.assertIsNotNone(decision.action)
        self.assertEqual(
            decision.action.arguments["internal_note"],
            "Called about a new addition.\n"
            "Needs a site visit before pricing.\n"
            "Follow up next Tuesday.",
        )


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    AI_MONTHLY_COST_LIMIT_USD=Decimal("25.00"),
    AI_RATE_LIMIT_REQUESTS=1,
    AI_LOCAL_ACTION_RATE_LIMIT_REQUESTS=2,
    AI_RATE_LIMIT_WINDOW_SECONDS=60,
)
class SeparateRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.template = """Create this client:
Company/household: Standring Household
Contact first name: Andrew
Contact last name: Standring
Email:
Phone:
Billing address 1:
Billing address 2:
City:
State:
Postal code:
Country:
Internal note:
"""

    def tearDown(self):
        cache.clear()

    def test_provider_limit_does_not_block_local_template(self):
        provider = MessageProvider()
        run_assistant(
            user=self.user,
            prompt="What needs attention?",
            provider=provider,
        )
        with self.assertRaises(AssistantRateLimited):
            run_assistant(
                user=self.user,
                prompt="Which invoices are overdue?",
                provider=provider,
            )

        local_result = run_assistant(
            user=self.user,
            prompt=self.template,
            provider=ProviderThatMustNotRun(),
        )

        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(local_result.pending_actions), 1)

    def test_local_template_has_its_own_bounded_rate_limit(self):
        run_assistant(
            user=self.user,
            prompt=self.template,
            provider=ProviderThatMustNotRun(),
        )
        run_assistant(
            user=self.user,
            prompt=self.template,
            provider=ProviderThatMustNotRun(),
        )

        with self.assertRaisesMessage(
            AssistantRateLimited,
            "Too many local assistant actions",
        ):
            run_assistant(
                user=self.user,
                prompt=self.template,
                provider=ProviderThatMustNotRun(),
            )


class StrictJsonBoundaryTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.client.force_login(self.user)

    def test_non_object_json_is_rejected_cleanly(self):
        for body in ("[]", '"prompt"', "null", "true"):
            with self.subTest(body=body):
                response = self.client.post(
                    reverse("assistant:ask"),
                    data=body,
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertIn("JSON object", response.json()["error"])

    def test_invalid_utf8_json_is_rejected_cleanly(self):
        response = self.client.post(
            reverse("assistant:ask"),
            data=b"\xff",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertIn("not valid JSON", response.json()["error"])
