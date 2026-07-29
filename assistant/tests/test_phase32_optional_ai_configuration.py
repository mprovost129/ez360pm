from decimal import Decimal

from django.core.checks import Error, Warning
from django.test import SimpleTestCase, override_settings

from assistant.checks import assistant_settings_check
from config.ai_env import AIEnvironment


class AIEnvironmentParserTests(SimpleTestCase):
    def test_invalid_optional_values_fall_back_without_raising(self):
        parser = AIEnvironment(
            {
                "AI_PROVIDER_TIMEOUT_SECONDS": "not-a-number",
                "AI_MONTHLY_COST_LIMIT_USD": "not-money",
                "AI_MODEL_PRICING_JSON": "[not-json",
                "AI_COMPANY_DEFAULT_ENABLED": "sometimes",
            }
        )

        self.assertEqual(parser.integer("AI_PROVIDER_TIMEOUT_SECONDS", 30), 30)
        self.assertEqual(
            parser.decimal("AI_MONTHLY_COST_LIMIT_USD", "25.00"),
            Decimal("25.00"),
        )
        self.assertEqual(parser.json_object("AI_MODEL_PRICING_JSON", {}), {})
        self.assertIsNone(
            parser.boolean("AI_COMPANY_DEFAULT_ENABLED", optional=True)
        )
        self.assertEqual(len(parser.errors), 4)

    def test_valid_values_preserve_expected_types(self):
        parser = AIEnvironment(
            {
                "AI_ASSISTANT_ENABLED": "yes",
                "AI_MAX_TOOL_CALLS": "3",
                "AI_MONTHLY_COST_LIMIT_USD": "12.50",
                "AI_MODEL_PRICING_JSON": '{"gpt-test":{"input":1,"output":2}}',
            }
        )

        self.assertTrue(parser.boolean("AI_ASSISTANT_ENABLED"))
        self.assertEqual(parser.integer("AI_MAX_TOOL_CALLS", 4), 3)
        self.assertEqual(
            parser.decimal("AI_MONTHLY_COST_LIMIT_USD", "25.00"),
            Decimal("12.50"),
        )
        self.assertEqual(
            parser.json_object("AI_MODEL_PRICING_JSON", {}),
            {"gpt-test": {"input": 1, "output": 2}},
        )
        self.assertEqual(parser.errors, [])


class OptionalAIConfigurationCheckTests(SimpleTestCase):
    @override_settings(
        AI_ASSISTANT_ENABLED=False,
        AI_CONFIGURATION_ERRORS=("AI_MAX_TOOL_CALLS must be a whole number.",),
        AI_MAX_TOOL_CALLS=0,
        AI_ALLOWED_MODELS=[],
        AI_PROACTIVE_MAX_ITEMS=0,
    )
    def test_disabled_ai_reports_parse_problem_as_warning_only(self):
        messages = assistant_settings_check(None)

        self.assertEqual([message.id for message in messages], ["assistant.W007"])
        self.assertIsInstance(messages[0], Warning)

    @override_settings(
        AI_ASSISTANT_ENABLED=True,
        AI_CONFIGURATION_ERRORS=("AI_MAX_TOOL_CALLS must be a whole number.",),
        AI_PROVIDER="openai",
        OPENAI_API_KEY="test-key",
    )
    def test_enabled_ai_reports_parse_problem_as_error(self):
        messages = assistant_settings_check(None)
        matching = [message for message in messages if message.id == "assistant.E028"]

        self.assertEqual(len(matching), 1)
        self.assertIsInstance(matching[0], Error)

    @override_settings(
        AI_ASSISTANT_ENABLED=True,
        AI_CONFIGURATION_ERRORS=(),
        AI_PROVIDER="unsupported",
        OPENAI_API_KEY="test-key",
    )
    def test_unsupported_provider_is_rejected_by_deployment_check(self):
        messages = assistant_settings_check(None)

        self.assertIn("assistant.E029", {message.id for message in messages})
