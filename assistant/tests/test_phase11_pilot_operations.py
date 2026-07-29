import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Company, User
from assistant.models import (
    AIActionAttempt,
    AICompanySettings,
    AIEvent,
    AIFeedback,
    AIIncident,
    AIInteraction,
    AIUserAccess,
)
from assistant.providers import ProviderError, ProviderResponse
from assistant.policies import get_company_policy
from assistant.services import AssistantUnavailable, run_assistant


class MessageProvider:
    name = "test"
    model = "allowed-model"

    def __init__(self, text="Ready."):
        self.text = text
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
                        "content": [{"type": "output_text", "text": self.text}],
                    }
                ],
                "usage": {"input_tokens": 5, "output_tokens": 3},
            }
        )


class FailingProvider:
    name = "test"
    model = "allowed-model"

    def __init__(self):
        self.calls = 0

    def create_response(self, *, input_items, instructions, tools):
        del input_items, instructions, tools
        self.calls += 1
        raise ProviderError("Provider unavailable.", code="provider_unavailable")


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    OPENAI_API_KEY="test-key",
    AI_MODEL="allowed-model",
    AI_ALLOWED_MODELS=["allowed-model"],
    AI_RATE_LIMIT_REQUESTS=100,
    AI_MONTHLY_COST_LIMIT_USD=Decimal("25.00"),
    AI_INPUT_COST_PER_MILLION_USD=Decimal("1.00"),
    AI_OUTPUT_COST_PER_MILLION_USD=Decimal("2.00"),
    AI_MODEL_PRICING={},
)
class AIPilotOperationsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
            is_staff=True,
        )
        self.other_user = User.objects.create_user(
            "other@example.com",
            "Strong-Test-Password-483!",
            company=self.other_company,
            is_staff=True,
        )
        policy = get_company_policy(self.company)
        AIUserAccess.objects.create(
            company=self.company,
            user=self.user,
            enabled=True,
            granted_by=self.user,
        )
        policy.enabled = True
        policy.privacy_notice_acknowledged_at = timezone.now()
        policy.privacy_notice_version = "2026-07-27"
        policy.save()

    def test_selected_user_access_blocks_before_provider_call(self):
        policy = self.company.ai_settings
        policy.access_mode = AICompanySettings.AccessMode.SELECTED_USERS
        policy.save(update_fields=["access_mode"])
        AIUserAccess.objects.filter(user=self.user).update(enabled=False)
        provider = MessageProvider()

        with self.assertRaises(AssistantUnavailable):
            run_assistant(user=self.user, prompt="What needs attention?", provider=provider)

        self.assertEqual(provider.calls, 0)
        self.assertEqual(AIInteraction.objects.count(), 0)

    def test_selected_user_access_allows_enabled_user(self):
        policy = self.company.ai_settings
        policy.access_mode = AICompanySettings.AccessMode.SELECTED_USERS
        policy.save(update_fields=["access_mode"])
        AIUserAccess.objects.filter(user=self.user).update(enabled=True)
        provider = MessageProvider("Nothing urgent.")

        result = run_assistant(
            user=self.user,
            prompt="What needs attention?",
            provider=provider,
        )

        self.assertEqual(result.message, "Nothing urgent.")
        self.assertEqual(provider.calls, 1)

    def test_repeated_failures_trip_company_circuit_breaker(self):
        policy = self.company.ai_settings
        policy.auto_pause_on_failures = True
        policy.failure_threshold = 2
        policy.failure_window_minutes = 60
        policy.save()
        provider = FailingProvider()

        run_assistant(user=self.user, prompt="First request", provider=provider)
        self.company.ai_settings.refresh_from_db()
        self.assertIsNone(self.company.ai_settings.suspended_at)

        run_assistant(user=self.user, prompt="Second request", provider=provider)
        self.company.ai_settings.refresh_from_db()
        self.assertIsNotNone(self.company.ai_settings.suspended_at)
        self.assertTrue(
            AIEvent.objects.filter(
                company=self.company,
                event_type=AIEvent.Type.CIRCUIT_BREAKER_TRIPPED,
            ).exists()
        )

        with self.assertRaises(AssistantUnavailable):
            run_assistant(user=self.user, prompt="Third request", provider=provider)
        self.assertEqual(provider.calls, 2)

    def test_feedback_is_scoped_to_the_interaction_user_and_company(self):
        interaction = AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="allowed-model",
            prompt_summary="attention",
            status=AIInteraction.Status.COMPLETED,
        )
        hidden = AIInteraction.objects.create(
            company=self.other_company,
            user=self.other_user,
            provider="openai",
            model="allowed-model",
            prompt_summary="hidden",
            status=AIInteraction.Status.COMPLETED,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assistant:feedback"),
            data=json.dumps(
                {
                    "interaction_id": interaction.pk,
                    "rating": "helpful",
                    "category": "answer",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AIFeedback.objects.filter(
                company=self.company,
                interaction=interaction,
                rating=AIFeedback.Rating.HELPFUL,
            ).exists()
        )

        hidden_response = self.client.post(
            reverse("assistant:feedback"),
            data=json.dumps(
                {
                    "interaction_id": hidden.pk,
                    "rating": "not_helpful",
                    "category": "answer",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(hidden_response.status_code, 404)

    def test_critical_incident_suspends_company_ai(self):
        interaction = AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="allowed-model",
            prompt_summary="send",
            status=AIInteraction.Status.COMPLETED,
        )
        pending = AIActionAttempt.objects.create(
            interaction=interaction,
            company=self.company,
            user=self.user,
            tool_name="create_note",
            risk_level=AIActionAttempt.RiskLevel.LOW_WRITE,
            normalized_arguments={"body": "test"},
            preview={"title": "Create note"},
            confirmation_expires_at=timezone.now() + timedelta(minutes=10),
            idempotency_key="b" * 64,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assistant:report-incident"),
            data=json.dumps(
                {
                    "interaction_id": interaction.pk,
                    "severity": "critical",
                    "category": "unsafe_action",
                    "summary": "The assistant prepared the wrong client action.",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["assistant_suspended"])
        self.company.ai_settings.refresh_from_db()
        self.assertIsNotNone(self.company.ai_settings.suspended_at)
        pending.refresh_from_db()
        self.assertEqual(pending.status, AIActionAttempt.Status.CANCELED)
        self.assertEqual(pending.error_code, "company_ai_suspended")
        self.assertTrue(
            AIIncident.objects.filter(
                company=self.company,
                severity=AIIncident.Severity.CRITICAL,
                status=AIIncident.Status.OPEN,
            ).exists()
        )

    def test_pilot_access_updates_cannot_cross_company_boundary(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assistant:pilot-user-access"),
            data={"user_id": self.other_user.pk, "enabled": "on"},
        )

        self.assertRedirects(response, reverse("assistant:pilot-operations"))
        self.assertFalse(
            AIUserAccess.objects.filter(
                company=self.company,
                user=self.other_user,
            ).exists()
        )

    def test_nonstaff_user_cannot_open_pilot_operations(self):
        nonstaff = User.objects.create_user(
            "designer@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.client.force_login(nonstaff)

        response = self.client.get(reverse("assistant:pilot-operations"))

        self.assertEqual(response.status_code, 403)
