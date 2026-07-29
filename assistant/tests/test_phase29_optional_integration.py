from django.test import RequestFactory, TestCase, override_settings

from accounts.models import Company, User
from assistant.context_processors import assistant_status
from assistant.models import AICompanySettings


class OptionalAssistantIntegrationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.request = RequestFactory().get("/projects/")
        self.request.user = self.user

    @override_settings(AI_ASSISTANT_ENABLED=False)
    def test_disabled_assistant_does_not_query_or_create_company_policy(self):
        with self.assertNumQueries(0):
            context = assistant_status(self.request)

        self.assertFalse(context["ai_assistant_enabled"])
        self.assertFalse(AICompanySettings.objects.exists())

    @override_settings(
        AI_ASSISTANT_ENABLED=True,
        AI_COMPANY_DEFAULT_ENABLED=True,
        AI_COMPANY_DEFAULT_PRIVACY_ACKNOWLEDGED=True,
        AI_COMPANY_DEFAULT_EXTERNAL_COMMITS=False,
        AI_COMPANY_DEFAULT_ACCESS_MODE="all_users",
    )
    def test_page_render_uses_unsaved_defaults_without_creating_policy(self):
        context = assistant_status(self.request)

        self.assertTrue(context["ai_assistant_enabled"])
        self.assertTrue(context["ai_client_template_enabled"])
        self.assertIsNone(context["ai_company_settings"].pk)
        self.assertFalse(AICompanySettings.objects.exists())

    @override_settings(
        AI_ASSISTANT_ENABLED=True,
        AI_COMPANY_DEFAULT_ENABLED=False,
        AI_COMPANY_DEFAULT_PRIVACY_ACKNOWLEDGED=False,
    )
    def test_disabled_company_defaults_hide_drawer_without_creating_policy(self):
        context = assistant_status(self.request)

        self.assertFalse(context["ai_assistant_enabled"])
        self.assertFalse(context["ai_client_template_enabled"])
        self.assertFalse(AICompanySettings.objects.exists())
