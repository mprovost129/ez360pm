from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Company, User
from assistant.evaluations import evaluation_fingerprint, run_connection_evaluation
from assistant.models import (
    AIEvaluationCaseResult,
    AIEvaluationRun,
    AIInteraction,
)
from assistant.policies import get_company_policy
from assistant.providers import ProviderResponse
from assistant.readiness import build_readiness_report


class ConnectionProvider:
    name = "openai"
    model = "allowed-model"

    def __init__(self, text="EZ360PM_OPENAI_READY"):
        self.text = text
        self.requests = []

    def create_response(self, *, input_items, instructions, tools):
        self.requests.append(
            {"input_items": input_items, "instructions": instructions, "tools": tools}
        )
        return ProviderResponse(
            {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": self.text}],
                    }
                ],
                "usage": {"input_tokens": 8, "output_tokens": 4},
                "_request_id": "req_connection_123",
            }
        )


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    OPENAI_API_KEY="test-key",
    AI_MODEL="allowed-model",
    AI_ALLOWED_MODELS=["allowed-model"],
    AI_MONTHLY_COST_LIMIT_USD=Decimal("25.00"),
    AI_INPUT_COST_PER_MILLION_USD=Decimal("1.00"),
    AI_OUTPUT_COST_PER_MILLION_USD=Decimal("2.00"),
    AI_MODEL_PRICING={},
    AI_READINESS_MAX_EVALUATION_AGE_DAYS=30,
)
class AIReadinessTests(TestCase):
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
        policy = get_company_policy(self.company)
        policy.enabled = True
        policy.privacy_notice_acknowledged_at = timezone.now()
        policy.privacy_notice_version = "2026-07-27"
        policy.monthly_request_limit = 500
        policy.monthly_cost_limit_usd = Decimal("25.00")
        policy.save()

    def _evaluation(self, *, company, user, suite, status="passed", model="allowed-model"):
        return AIEvaluationRun.objects.create(
            company=company,
            user=user,
            mode=AIEvaluationRun.Mode.LIVE,
            suite=suite,
            model=model,
            status=status,
            total_cases=1,
            passed_cases=1 if status == "passed" else 0,
            failed_cases=0 if status == "passed" else 1,
            completed_at=timezone.now(),
            configuration_fingerprint=evaluation_fingerprint(model),
        )

    def test_connection_evaluation_uses_no_tools_and_records_usage(self):
        provider = ConnectionProvider()

        run = run_connection_evaluation(user=self.user, provider=provider)

        self.assertEqual(run.status, AIEvaluationRun.Status.PASSED)
        self.assertEqual(provider.requests[0]["tools"], [])
        interaction = AIInteraction.objects.get(company=self.company)
        self.assertEqual(interaction.provider_request_ids, ["req_connection_123"])
        self.assertEqual(interaction.total_tokens, 12)
        case = AIEvaluationCaseResult.objects.get(run=run)
        self.assertEqual(case.status, AIEvaluationCaseResult.Status.PASSED)

    def test_exact_connection_contract_fails_closed(self):
        run = run_connection_evaluation(
            user=self.user,
            provider=ConnectionProvider("Ready, everything looks good."),
        )

        self.assertEqual(run.status, AIEvaluationRun.Status.FAILED)
        self.assertEqual(run.passed_cases, 0)

    def test_readiness_is_company_scoped_and_requires_this_company_live_baseline(self):
        AIEvaluationRun.objects.create(
            mode=AIEvaluationRun.Mode.CONTRACT,
            suite="contract",
            model="allowed-model",
            status=AIEvaluationRun.Status.PASSED,
            total_cases=1,
            passed_cases=1,
            completed_at=timezone.now(),
            configuration_fingerprint=evaluation_fingerprint("allowed-model"),
        )
        self._evaluation(company=self.company, user=self.user, suite="connection")
        self._evaluation(company=self.other_company, user=self.other_user, suite="all")
        AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="allowed-model",
            prompt_summary="recent",
            status=AIInteraction.Status.COMPLETED,
            completed_at=timezone.now(),
        )

        report = build_readiness_report(self.user)

        self.assertFalse(report.ready)
        live_check = next(item for item in report.checks if item.key == "live-evaluation")
        self.assertEqual(live_check.status, "fail")

    def test_readiness_rejects_an_evaluation_from_a_different_configuration(self):
        AIEvaluationRun.objects.create(
            mode=AIEvaluationRun.Mode.CONTRACT,
            suite="contract",
            model="allowed-model",
            status=AIEvaluationRun.Status.PASSED,
            total_cases=1,
            passed_cases=1,
            completed_at=timezone.now(),
            configuration_fingerprint="0" * 64,
        )
        self._evaluation(company=self.company, user=self.user, suite="connection")
        self._evaluation(company=self.company, user=self.user, suite="all")

        report = build_readiness_report(self.user)

        self.assertFalse(report.ready)
        check = next(item for item in report.checks if item.key == "contract-evaluation")
        self.assertEqual(check.status, "fail")
        self.assertIn("different model/tool/provider configuration", check.detail)

    def test_readiness_passes_after_contract_connection_and_full_live_baseline(self):
        AIEvaluationRun.objects.create(
            mode=AIEvaluationRun.Mode.CONTRACT,
            suite="contract",
            model="allowed-model",
            status=AIEvaluationRun.Status.PASSED,
            total_cases=1,
            passed_cases=1,
            completed_at=timezone.now(),
            configuration_fingerprint=evaluation_fingerprint("allowed-model"),
        )
        self._evaluation(company=self.company, user=self.user, suite="connection")
        self._evaluation(company=self.company, user=self.user, suite="all")
        AIInteraction.objects.create(
            company=self.company,
            user=self.user,
            provider="openai",
            model="allowed-model",
            prompt_summary="recent",
            status=AIInteraction.Status.COMPLETED,
            completed_at=timezone.now(),
        )

        report = build_readiness_report(self.user)

        self.assertTrue(report.ready)
        self.assertEqual(report.failed_count, 0)

    def test_readiness_page_is_company_scoped(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("assistant:readiness"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["readiness"].model, "allowed-model")

    @patch("assistant.evaluations.run_connection_evaluation")
    def test_connection_endpoint_redirects_and_reports_success(self, mocked_run):
        mocked_run.return_value = AIEvaluationRun(
            status=AIEvaluationRun.Status.PASSED,
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("assistant:connection-test"))

        self.assertRedirects(response, reverse("assistant:readiness"))
        mocked_run.assert_called_once_with(user=self.user)
