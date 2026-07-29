from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import Company, User
from assistant.evaluations import (
    CORE_CASES,
    contract_check_results,
    score_live_case,
)
from assistant.models import AIEvaluationCaseResult, AIEvaluationRun, AIInteraction


@override_settings(AI_MODEL="gpt-5", AI_ALLOWED_MODELS=["gpt-5"])
class EvaluationContractTests(SimpleTestCase):
    def test_all_static_contract_checks_pass(self):
        failures = [item for item in contract_check_results() if not item["passed"]]
        self.assertEqual(failures, [])

    def test_live_case_scoring_rejects_any_prepared_write(self):
        case = CORE_CASES[0]
        result = SimpleNamespace(
            tool_trace=(
                {"name": "get_attention_summary", "risk_level": "read"},
                {"name": "create_note", "risk_level": "low_write"},
            ),
            pending_actions=[{"token": "example"}],
        )
        interaction = SimpleNamespace(
            status=AIInteraction.Status.COMPLETED,
            error_code="",
        )

        passed, tools, reasons = score_live_case(case, result, interaction)

        self.assertFalse(passed)
        self.assertIn("create_note", tools)
        self.assertTrue(any("Forbidden write risk" in reason for reason in reasons))
        self.assertTrue(any("Prepared 1 action" in reason for reason in reasons))


@override_settings(AI_ASSISTANT_ENABLED=True)
class EvaluationHistoryViewTests(TestCase):
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
        self.run = AIEvaluationRun.objects.create(
            company=self.company,
            user=self.user,
            mode=AIEvaluationRun.Mode.LIVE,
            suite="core",
            model="gpt-5",
            status=AIEvaluationRun.Status.PASSED,
            total_cases=1,
            passed_cases=1,
        )
        AIEvaluationCaseResult.objects.create(
            run=self.run,
            case_id="attention-summary",
            title="Attention summary",
            category="read_accuracy",
            status=AIEvaluationCaseResult.Status.PASSED,
            actual_tools=["get_attention_summary"],
        )
        self.hidden_run = AIEvaluationRun.objects.create(
            company=self.other_company,
            user=self.other_user,
            mode=AIEvaluationRun.Mode.LIVE,
            suite="security",
            model="gpt-5",
            status=AIEvaluationRun.Status.FAILED,
        )
        self.client.force_login(self.user)

    def test_evaluation_history_is_company_scoped(self):
        response = self.client.get(reverse("assistant:evaluations"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Attention summary")
        visible_ids = {run.pk for run in response.context["runs"]}
        self.assertIn(self.run.pk, visible_ids)
        self.assertNotIn(self.hidden_run.pk, visible_ids)
