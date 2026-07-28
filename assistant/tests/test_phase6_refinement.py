from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Company, User
from assistant.insights import command_suggestions, proactive_insights, usage_metrics
from assistant.models import AIActionAttempt, AIEvent, AIInsightDismissal, AIInteraction
from clients.tests.test_clients import create_client
from projects.services import create_project
from projects.tests.test_projects import project_data


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    AI_PROACTIVE_INSIGHTS_ENABLED=True,
    AI_STALE_LEAD_DAYS=14,
    AI_PROACTIVE_MAX_ITEMS=4,
    AI_PROACTIVE_DISMISS_DAYS=7,
)
class Phase6RefinementTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.other_user = User.objects.create_user(
            "other@example.com",
            "Strong-Test-Password-483!",
            company=self.other_company,
        )
        self.client_record = create_client(self.company, company_name="Smith Household")
        self.project = create_project(
            company=self.company,
            client=self.client_record,
            project_data=project_data(number="2607001", name="Smith Addition"),
        )

    def test_stale_lead_insight_is_scoped_and_dismissible(self):
        old = timezone.now() - timedelta(days=20)
        type(self.project).objects.filter(pk=self.project.pk).update(updated_at=old)
        other_client = create_client(self.other_company, company_name="Hidden Household")
        hidden = create_project(
            company=self.other_company,
            client=other_client,
            project_data=project_data(number="HIDDEN", name="Hidden Lead"),
        )
        type(hidden).objects.filter(pk=hidden.pk).update(updated_at=old)

        insights = proactive_insights(self.user)

        self.assertTrue(any("Smith Addition" in item["summary"] for item in insights))
        self.assertFalse(any("Hidden Lead" in item["summary"] for item in insights))
        key = next(item["key"] for item in insights if "Smith Addition" in item["summary"])
        AIInsightDismissal.objects.create(
            company=self.company,
            user=self.user,
            insight_key=key,
            dismissed_until=timezone.now() + timedelta(days=7),
        )
        self.assertFalse(any(item["key"] == key for item in proactive_insights(self.user)))

    def test_completed_tools_personalize_command_suggestions(self):
        interaction = AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="test",
            prompt_summary="timer",
            status=AIInteraction.Status.COMPLETED,
        )
        AIActionAttempt.objects.create(
            interaction=interaction,
            company=self.company,
            user=self.user,
            tool_name="start_timer",
            risk_level=AIActionAttempt.RiskLevel.LOW_WRITE,
            normalized_arguments={},
            preview={},
            status=AIActionAttempt.Status.COMPLETED,
            confirmation_expires_at=timezone.now() + timedelta(minutes=10),
            idempotency_key="a" * 64,
        )

        suggestions = command_suggestions(self.user)

        self.assertEqual(suggestions[0]["id"], "start_timer")

    def test_usage_metrics_do_not_mix_companies(self):
        AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="test",
            prompt_summary="mine",
            status=AIInteraction.Status.COMPLETED,
            estimated_cost_usd=Decimal("0.010000"),
        )
        AIInteraction.objects.create(
            company=self.other_company,
            user=self.other_user,
            provider="openai",
            model="test",
            prompt_summary="hidden",
            status=AIInteraction.Status.COMPLETED,
            estimated_cost_usd=Decimal("9.000000"),
        )

        metrics = usage_metrics(self.user)

        self.assertEqual(metrics["interaction_count"], 1)
        self.assertEqual(metrics["estimated_cost"], Decimal("0.010000"))

    def test_home_data_and_dismiss_endpoints_require_company_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("assistant:home-data"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("suggestions", response.json())

        response = self.client.post(
            reverse("assistant:dismiss-insight"),
            data='{"insight_key":"stale_lead:1"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AIEvent.objects.filter(
                company=self.company,
                user=self.user,
                event_type=AIEvent.Type.INSIGHT_DISMISSED,
            ).exists()
        )

    def test_suggestion_event_endpoint_rejects_unknown_ids(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("assistant:record-event"),
            data='{"event_type":"suggestion_used","suggestion_id":"not_a_tool"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
