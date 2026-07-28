from django.test import SimpleTestCase, override_settings

from assistant.checks import assistant_settings_check


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    OPENAI_API_KEY="test-key",
    AI_PROVIDER_TIMEOUT_SECONDS=30,
    AI_MAX_TOOL_ROUNDS=4,
)
class AssistantDeploymentCheckTests(SimpleTestCase):
    @override_settings(GUNICORN_TIMEOUT_SECONDS=180)
    def test_worker_timeout_covers_all_tool_rounds(self):
        errors = assistant_settings_check(None)

        self.assertNotIn("assistant.E020", {message.id for message in errors})

    @override_settings(GUNICORN_TIMEOUT_SECONDS=30)
    def test_short_worker_timeout_is_rejected(self):
        errors = assistant_settings_check(None)

        timeout_error = next(
            message for message in errors if message.id == "assistant.E020"
        )
        self.assertIn("at least 135 seconds", timeout_error.msg)
