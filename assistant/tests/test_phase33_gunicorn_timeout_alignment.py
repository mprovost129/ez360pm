from pathlib import Path

from django.core.checks import Error, Warning
from django.test import SimpleTestCase, override_settings

from config.ai_env import AIEnvironment
from core.checks import check_runtime_server_configuration


class RuntimeTimeoutParserTests(SimpleTestCase):
    def test_invalid_gunicorn_timeout_uses_safe_fallback(self):
        parser = AIEnvironment({"GUNICORN_TIMEOUT_SECONDS": "not-a-number"})

        self.assertEqual(parser.integer("GUNICORN_TIMEOUT_SECONDS", 180), 180)
        self.assertEqual(
            parser.errors,
            ["GUNICORN_TIMEOUT_SECONDS must be a whole number."],
        )


class RuntimeServerConfigurationCheckTests(SimpleTestCase):
    @override_settings(
        RUNTIME_CONFIGURATION_ERRORS=(
            "GUNICORN_TIMEOUT_SECONDS must be a whole number.",
        ),
        GUNICORN_TIMEOUT_SECONDS=180,
    )
    def test_invalid_runtime_value_is_reported_with_safe_fallback(self):
        messages = check_runtime_server_configuration(None)

        self.assertEqual([message.id for message in messages], ["ez360pm.W006"])
        self.assertIsInstance(messages[0], Warning)

    @override_settings(
        RUNTIME_CONFIGURATION_ERRORS=(),
        GUNICORN_TIMEOUT_SECONDS=29,
    )
    def test_too_short_worker_timeout_is_rejected(self):
        messages = check_runtime_server_configuration(None)

        matching = [message for message in messages if message.id == "ez360pm.E002"]
        self.assertEqual(len(matching), 1)
        self.assertIsInstance(matching[0], Error)

    @override_settings(
        RUNTIME_CONFIGURATION_ERRORS=(),
        GUNICORN_TIMEOUT_SECONDS=180,
    )
    def test_valid_worker_timeout_has_no_runtime_issues(self):
        self.assertEqual(check_runtime_server_configuration(None), [])


class GunicornStartCommandContractTests(SimpleTestCase):
    def test_start_script_passes_resolved_timeout_to_gunicorn(self):
        project_root = Path(__file__).resolve().parents[2]
        script = (project_root / "bin" / "start.sh").read_text()

        self.assertIn('GUNICORN_TIMEOUT_RESOLVED="$(python - <<\'PY\'', script)
        self.assertIn('print(settings.GUNICORN_TIMEOUT_SECONDS)', script)
        self.assertIn('--timeout "${GUNICORN_TIMEOUT_RESOLVED}"', script)

    def test_deploy_warnings_are_visible_but_not_blocking_by_default(self):
        project_root = Path(__file__).resolve().parents[2]
        script = (project_root / "bin" / "start.sh").read_text()

        self.assertIn(
            '--fail-level "${DJANGO_DEPLOY_CHECK_FAIL_LEVEL:-ERROR}"',
            script,
        )
