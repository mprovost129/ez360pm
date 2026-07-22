from django.test import SimpleTestCase, override_settings

from core.checks import check_production_email_identity


class ProductionConfigurationCheckTests(SimpleTestCase):
    @override_settings(
        DEBUG=False,
        DEFAULT_FROM_EMAIL="Studio <office@example.com>",
        PUBLIC_BASE_URL="http://app.example.com",
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
        STRIPE_SECRET_KEY="",
        STRIPE_WEBHOOK_SECRET="",
    )
    def test_insecure_url_and_console_email_are_reported(self):
        issues = check_production_email_identity(None)

        self.assertIn("ez360pm.W004", {issue.id for issue in issues})
        self.assertIn("ez360pm.W005", {issue.id for issue in issues})

    @override_settings(
        DEBUG=False,
        DEFAULT_FROM_EMAIL="Studio <office@example.com>",
        PUBLIC_BASE_URL="https://app.example.com",
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        STRIPE_SECRET_KEY="",
        STRIPE_WEBHOOK_SECRET="",
    )
    def test_complete_production_identity_has_no_ez360pm_warnings(self):
        issues = check_production_email_identity(None)

        self.assertEqual(issues, [])
