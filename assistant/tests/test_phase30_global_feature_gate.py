import json

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Company, User
from assistant.models import AICompanySettings, AIInteraction


class GlobalAssistantFeatureGateTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
            is_staff=True,
        )
        self.client.force_login(self.user)

    @override_settings(AI_ASSISTANT_ENABLED=False)
    def test_direct_json_endpoints_are_hidden_without_creating_ai_rows(self):
        response = self.client.post(
            reverse("assistant:ask"),
            data=json.dumps({"prompt": "What needs my attention?"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(AICompanySettings.objects.exists())
        self.assertFalse(AIInteraction.objects.exists())

    @override_settings(AI_ASSISTANT_ENABLED=False)
    def test_direct_html_endpoints_are_hidden_without_creating_policy(self):
        for name in (
            "assistant:settings",
            "assistant:readiness",
            "assistant:action-center",
            "assistant:usage",
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 404)

        self.assertFalse(AICompanySettings.objects.exists())

    @override_settings(AI_ASSISTANT_ENABLED=True)
    def test_feature_gate_allows_normal_view_security_to_run_when_enabled(self):
        response = self.client.get(reverse("assistant:action-center"))

        # The view may redirect or render depending on company policy defaults,
        # but the platform gate itself must no longer return its disabled 404.
        self.assertNotEqual(response.status_code, 404)
