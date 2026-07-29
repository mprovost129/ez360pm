import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Company, User
from assistant.models import AIActionAttempt, AIInteraction
from assistant.policies import get_company_policy
from assistant.providers import ProviderResponse
from assistant.services import AssistantUnavailable, run_assistant


class QueueProvider:
    name = "test"
    model = "allowed-model"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def create_response(self, *, input_items, instructions, tools):
        self.requests.append(
            {"input_items": input_items, "instructions": instructions, "tools": tools}
        )
        return ProviderResponse(self.responses.pop(0))


def message(text):
    return {
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    AI_COMPANY_DEFAULT_ENABLED=None,
    AI_COMPANY_DEFAULT_EXTERNAL_COMMITS=None,
    AI_COMPANY_DEFAULT_PRIVACY_ACKNOWLEDGED=None,
    AI_ALLOWED_MODELS=["allowed-model"],
    AI_MODEL="allowed-model",
    AI_RATE_LIMIT_REQUESTS=100,
    AI_MONTHLY_COST_LIMIT_USD=Decimal("25.00"),
)
class AICompanyControlTests(TestCase):
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
        self.policy = get_company_policy(self.company)
        self.other_policy = get_company_policy(self.other_company)

    def test_first_explicit_policy_provision_uses_personal_mode_defaults(self):
        policy = self.policy
        self.assertTrue(policy.enabled)
        self.assertTrue(policy.allow_external_commits)
        self.assertIsNotNone(policy.privacy_notice_acknowledged_at)

    def test_disabled_company_is_blocked_before_provider_call(self):
        policy = self.company.ai_settings
        policy.enabled = False
        policy.save(update_fields=["enabled"])
        provider = QueueProvider(message("Should not run."))

        with self.assertRaises(AssistantUnavailable):
            run_assistant(user=self.user, prompt="What needs attention?", provider=provider)

        self.assertEqual(provider.requests, [])
        self.assertEqual(AIInteraction.objects.count(), 0)

    def test_monthly_request_limit_is_company_scoped_and_fail_closed(self):
        policy = self.company.ai_settings
        policy.monthly_request_limit = 1
        policy.save(update_fields=["monthly_request_limit"])
        AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="allowed-model",
            prompt_summary="used",
            status=AIInteraction.Status.COMPLETED,
        )
        AIInteraction.objects.create(
            company=self.other_company,
            user=self.other_user,
            provider="openai",
            model="allowed-model",
            prompt_summary="other",
            status=AIInteraction.Status.COMPLETED,
        )

        with self.assertRaises(AssistantUnavailable):
            run_assistant(
                user=self.user,
                prompt="What needs attention?",
                provider=QueueProvider(message("Should not run.")),
            )


    def test_summary_retention_can_be_disabled_without_disabling_audit_metadata(self):
        policy = self.company.ai_settings
        policy.retain_interaction_summaries = False
        policy.save(update_fields=["retain_interaction_summaries"])

        run_assistant(
            user=self.user,
            prompt="What needs my attention today?",
            provider=QueueProvider(message("Nothing urgent.")),
        )

        interaction = AIInteraction.objects.get(company=self.company)
        self.assertEqual(interaction.prompt_summary, "[summary retention disabled]")
        self.assertEqual(interaction.response_summary, "[summary retention disabled]")
        self.assertGreater(interaction.total_tokens, 0)

    def test_company_cost_limit_is_lower_than_platform_limit(self):
        policy = self.company.ai_settings
        policy.monthly_cost_limit_usd = Decimal("0.01")
        policy.save(update_fields=["monthly_cost_limit_usd"])
        AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="allowed-model",
            prompt_summary="used",
            status=AIInteraction.Status.COMPLETED,
            estimated_cost_usd=Decimal("0.010000"),
        )

        with self.assertRaises(AssistantUnavailable):
            run_assistant(
                user=self.user,
                prompt="What needs attention?",
                provider=QueueProvider(message("Should not run.")),
            )

    def test_disabled_action_category_is_removed_from_openai_tools(self):
        policy = self.company.ai_settings
        policy.allow_external_commits = False
        policy.allow_financial_drafts = False
        policy.save(update_fields=["allow_external_commits", "allow_financial_drafts"])
        provider = QueueProvider(message("Ready."))

        run_assistant(user=self.user, prompt="What needs attention?", provider=provider)

        tool_names = {tool["name"] for tool in provider.requests[0]["tools"]}
        self.assertNotIn("issue_and_send_document", tool_names)
        self.assertNotIn("prepare_final_invoice_draft", tool_names)
        self.assertIn("search_projects", tool_names)

    def test_confirmation_rechecks_current_company_policy(self):
        interaction = AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="allowed-model",
            prompt_summary="send",
            status=AIInteraction.Status.COMPLETED,
        )
        attempt = AIActionAttempt.objects.create(
            interaction=interaction,
            company=self.company,
            user=self.user,
            tool_name="issue_document",
            risk_level=AIActionAttempt.RiskLevel.EXTERNAL_COMMIT,
            normalized_arguments={},
            preview={},
            confirmation_expires_at=timezone.now() + timedelta(minutes=3),
            idempotency_key="8" * 64,
        )
        policy = self.company.ai_settings
        policy.allow_external_commits = False
        policy.save(update_fields=["allow_external_commits"])
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assistant:confirm-action", kwargs={"token": attempt.confirmation_token}),
            data=json.dumps({"final_review_acknowledged": True}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, AIActionAttempt.Status.PENDING)

    def test_ai_settings_and_audit_export_are_company_scoped(self):
        AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="allowed-model",
            prompt_summary="mine",
            status=AIInteraction.Status.COMPLETED,
            provider_request_ids=["req_mine"],
            provider_client_request_ids=["client_mine"],
        )
        AIInteraction.objects.create(
            company=self.other_company,
            user=self.other_user,
            provider="openai",
            model="allowed-model",
            prompt_summary="hidden",
            status=AIInteraction.Status.COMPLETED,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assistant:settings"),
            data={
                "enabled": "on",
                "model_override": "allowed-model",
                "allow_low_risk_writes": "on",
                "allow_structured_writes": "on",
                "allow_financial_drafts": "on",
                "proactive_insights_enabled": "on",
                "monthly_cost_limit_usd": "12.50",
                "monthly_request_limit": "250",
                "interaction_retention_days": "60",
                "retain_interaction_summaries": "on",
                "acknowledge_privacy_notice": "on",
            },
        )
        self.assertRedirects(response, reverse("assistant:settings"))
        self.company.ai_settings.refresh_from_db()
        self.assertEqual(self.company.ai_settings.monthly_request_limit, 250)
        self.assertEqual(self.other_company.ai_settings.monthly_request_limit, 500)

        export = self.client.get(reverse("assistant:usage-export"), {"days": 30})
        body = export.content.decode()
        self.assertEqual(export.status_code, 200)
        self.assertIn("owner@example.com", body)
        self.assertIn("provider_request_ids", body)
        self.assertIn("client_request_ids", body)
        self.assertIn("req_mine", body)
        self.assertIn("client_mine", body)
        self.assertNotIn("other@example.com", body)
