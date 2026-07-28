from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Company, User
from assistant.services import AssistantResult


class AssistantViewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )

    def test_ask_requires_login(self):
        response = self.client.post(
            reverse("assistant:ask"),
            data='{"prompt":"hello"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 302)

    @override_settings(
        AI_ASSISTANT_ENABLED=True,
        AI_MONTHLY_COST_LIMIT_USD=Decimal("25.00"),
    )
    @patch("assistant.views.run_assistant")
    def test_ask_returns_structured_response(self, mocked_run):
        mocked_run.return_value = AssistantResult(
            message="Nothing urgent.",
            links=[{"label": "Dashboard", "url": "/"}],
            pending_actions=[],
            interaction_id=4,
            conversation_id="11111111-1111-4111-8111-111111111111",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assistant:ask"),
            data='{"prompt":"What needs attention?","conversation_id":"11111111-1111-4111-8111-111111111111","page_path":"/projects/"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["message"], "Nothing urgent.")
        self.assertEqual(
            response.json()["conversation_id"],
            "11111111-1111-4111-8111-111111111111",
        )
        mocked_run.assert_called_once_with(
            user=self.user,
            prompt="What needs attention?",
            conversation_id="11111111-1111-4111-8111-111111111111",
            page_path="/projects/",
        )
