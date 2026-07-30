from django.test import SimpleTestCase, override_settings

from core.checks import check_production_email_identity


class ProductionConfigurationCheckTests(SimpleTestCase):
    @override_settings(
        DEBUG=False,
        DEFAULT_FROM_EMAIL="Studio <office@example.com>",
        PUBLIC_BASE_URL="http://app.example.com",
        ALLOWED_HOSTS=["app.example.com"],
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
        ALLOWED_HOSTS=["app.example.com"],
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        STRIPE_SECRET_KEY="",
        STRIPE_WEBHOOK_SECRET="",
    )
    def test_complete_production_identity_has_no_ez360pm_warnings(self):
        issues = check_production_email_identity(None)

        self.assertEqual(issues, [])

    @override_settings(
        DEBUG=False,
        DEFAULT_FROM_EMAIL="Studio <notifications@mail.example.com>",
        PUBLIC_BASE_URL="https://app.example.com",
        ALLOWED_HOSTS=["app.example.com"],
        EMAIL_PROVIDER="resend",
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        RESEND_API_KEY="",
        RESEND_WEBHOOK_SECRET="",
        STRIPE_SECRET_KEY="",
        STRIPE_WEBHOOK_SECRET="",
    )
    def test_incomplete_resend_configuration_is_reported(self):
        issues = check_production_email_identity(None)
        ids = {issue.id for issue in issues}

        self.assertTrue({"ez360pm.W008", "ez360pm.W009", "ez360pm.W010"} <= ids)

    @override_settings(
        DEBUG=False,
        DEFAULT_FROM_EMAIL="Studio <notifications@mail.example.com>",
        PUBLIC_BASE_URL="https://app.example.com",
        ALLOWED_HOSTS=["app.example.com"],
        EMAIL_PROVIDER="resend",
        EMAIL_BACKEND="core.email_backends.ResendEmailBackend",
        RESEND_API_KEY="re_configured",
        RESEND_WEBHOOK_SECRET="whsec_configured",
        STRIPE_SECRET_KEY="",
        STRIPE_WEBHOOK_SECRET="",
    )
    def test_complete_resend_configuration_has_no_ez360pm_warnings(self):
        issues = check_production_email_identity(None)

        self.assertEqual(issues, [])

    @override_settings(
        DEBUG=False,
        DEFAULT_FROM_EMAIL="Studio <office@example.com>",
        PUBLIC_BASE_URL="https://www.ez360pm.com/client-links",
        ALLOWED_HOSTS=["www.ez360pm.com"],
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        STRIPE_SECRET_KEY="",
        STRIPE_WEBHOOK_SECRET="",
    )
    def test_public_base_url_must_be_an_origin(self):
        issues = check_production_email_identity(None)

        self.assertIn("ez360pm.E003", {issue.id for issue in issues})

    @override_settings(
        DEBUG=False,
        DEFAULT_FROM_EMAIL="Studio <office@example.com>",
        PUBLIC_BASE_URL="https://www.ez360pm.com",
        ALLOWED_HOSTS=["ez360pm.com", "ez360pm.onrender.com"],
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        STRIPE_SECRET_KEY="",
        STRIPE_WEBHOOK_SECRET="",
    )
    def test_public_base_url_host_must_be_allowed(self):
        issues = check_production_email_identity(None)

        self.assertIn("ez360pm.E004", {issue.id for issue in issues})

    @override_settings(
        DEBUG=False,
        DEFAULT_FROM_EMAIL="Studio <office@example.com>",
        PUBLIC_BASE_URL="https://www.ez360pm.com",
        ALLOWED_HOSTS=[".ez360pm.com"],
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        STRIPE_SECRET_KEY="",
        STRIPE_WEBHOOK_SECRET="",
    )
    def test_public_base_url_accepts_django_subdomain_pattern(self):
        issues = check_production_email_identity(None)

        self.assertEqual(issues, [])
