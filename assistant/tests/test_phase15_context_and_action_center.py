import json
import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Company, User
from assistant.models import AIActionAttempt, AIInteraction
from assistant.providers import ProviderResponse
from assistant.services import run_assistant
from clients.tests.test_clients import create_client
from projects.services import create_project
from projects.tests.test_projects import project_data


class QueueProvider:
    name = "test"
    model = "test-model"

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
        "usage": {"input_tokens": 8, "output_tokens": 4},
    }


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    AI_RATE_LIMIT_REQUESTS=100,
    AI_MONTHLY_COST_LIMIT_USD=Decimal("25.00"),
    AI_INPUT_COST_PER_MILLION_USD=Decimal("0"),
    AI_OUTPUT_COST_PER_MILLION_USD=Decimal("0"),
    AI_CONVERSATION_CONTEXT_TURNS=4,
    AI_CONVERSATION_CONTEXT_MINUTES=60,
)
class ConversationAndPageContextTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other Company")
        self.user = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        client = create_client(self.company, company_name="Smith Household")
        self.project = create_project(
            company=self.company,
            client=client,
            project_data=project_data(number="2607001", name="Smith Addition"),
        )
        hidden_client = create_client(self.other_company, company_name="Hidden")
        self.hidden_project = create_project(
            company=self.other_company,
            client=hidden_client,
            project_data=project_data(number="HIDDEN-1", name="Hidden Addition"),
        )

    def test_recent_redacted_summaries_are_reused_only_inside_same_conversation(self):
        conversation_id = uuid.uuid4()
        run_assistant(
            user=self.user,
            prompt="Find the Smith project.",
            provider=QueueProvider(message("I found project 2607001.")),
            conversation_id=conversation_id,
        )

        provider = QueueProvider(message("It is the Smith Addition."))
        result = run_assistant(
            user=self.user,
            prompt="What is its name?",
            provider=provider,
            conversation_id=conversation_id,
        )

        joined = json.dumps(provider.requests[0]["input_items"])
        self.assertIn("Earlier user request summary", joined)
        self.assertIn("Find the Smith project", joined)
        self.assertIn("I found project 2607001", joined)
        interaction = AIInteraction.objects.order_by("-pk").first()
        self.assertEqual(interaction.context_turn_count, 1)
        self.assertEqual(str(interaction.conversation_id), str(conversation_id))
        self.assertEqual(result.conversation_id, str(conversation_id))

        unrelated_provider = QueueProvider(message("No prior context used."))
        run_assistant(
            user=self.user,
            prompt="Start fresh.",
            provider=unrelated_provider,
            conversation_id=uuid.uuid4(),
        )
        unrelated = json.dumps(unrelated_provider.requests[0]["input_items"])
        self.assertNotIn("Earlier user request summary", unrelated)

    def test_page_context_is_company_scoped_and_minimal(self):
        provider = QueueProvider(message("This is the Smith Addition page."))
        run_assistant(
            user=self.user,
            prompt="What project is this?",
            provider=provider,
            page_path=reverse("projects:detail", args=(self.project.pk,)),
        )
        instructions = provider.requests[0]["instructions"]
        self.assertIn("Server-verified current-page context", instructions)
        self.assertIn("2607001", instructions)
        self.assertNotIn(self.project.description, instructions)
        interaction = AIInteraction.objects.get()
        self.assertEqual(interaction.page_context_type, "project")
        self.assertEqual(interaction.page_context_object_id, self.project.pk)

        hidden_provider = QueueProvider(message("No page context."))
        run_assistant(
            user=self.user,
            prompt="What is this?",
            provider=hidden_provider,
            page_path=reverse("projects:detail", args=(self.hidden_project.pk,)),
        )
        self.assertNotIn("HIDDEN-1", hidden_provider.requests[0]["instructions"])


@override_settings(
    AI_ASSISTANT_ENABLED=True,
    AI_MONTHLY_COST_LIMIT_USD=Decimal("25.00"),
)
class ActionCenterTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other")
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
        self.client.force_login(self.user)

    def create_attempt(self, *, user=None, expires=None, title="Create note"):
        user = user or self.user
        interaction = AIInteraction.objects.create(
            company=user.company,
            user=user,
            provider="test",
            model="test",
            prompt_summary="prepare action",
        )
        return AIActionAttempt.objects.create(
            interaction=interaction,
            company=user.company,
            user=user,
            tool_name="create_note",
            risk_level=AIActionAttempt.RiskLevel.LOW_WRITE,
            preview={"title": title, "summary": "Review the note."},
            normalized_arguments={"body": "Call client"},
            confirmation_expires_at=expires or timezone.now() + timedelta(minutes=10),
            idempotency_key=uuid.uuid4().hex,
        )

    def test_action_center_restores_only_current_users_pending_actions(self):
        visible = self.create_attempt(title="Visible action")
        self.create_attempt(user=self.other_user, title="Hidden action")
        response = self.client.get(reverse("assistant:action-center"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visible action")
        self.assertNotContains(response, "Hidden action")
        self.assertContains(response, str(visible.confirmation_token))

    def test_expired_actions_are_closed_and_not_returned_by_home_data(self):
        expired = self.create_attempt(expires=timezone.now() - timedelta(seconds=1))
        active = self.create_attempt(title="Still active")
        response = self.client.get(reverse("assistant:home-data"))
        self.assertEqual(response.status_code, 200)
        tokens = {item["token"] for item in response.json()["pending_actions"]}
        self.assertIn(str(active.confirmation_token), tokens)
        self.assertNotIn(str(expired.confirmation_token), tokens)
        expired.refresh_from_db()
        self.assertEqual(expired.status, AIActionAttempt.Status.EXPIRED)
