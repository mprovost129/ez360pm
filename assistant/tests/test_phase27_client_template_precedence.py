from django.test import SimpleTestCase

from assistant.local_actions import (
    CLIENT_TEMPLATE_TEXT,
    local_action_decision_for_prompt,
)
from assistant.security import matching_write_intents
from assistant.tool_routing import select_tool_plan


class LocalClientTemplatePrecedenceTests(SimpleTestCase):
    def _completed_template(self, internal_note):
        return (
            CLIENT_TEMPLATE_TEXT.replace(
                "Contact first name:\n", "Contact first name: Andrew\n"
            )
            .replace("Contact last name:\n", "Contact last name: Standring\n")
            .replace("Internal note:\n", f"Internal note: {internal_note}\n")
        )

    def test_template_prefix_wins_when_note_mentions_other_assistant_actions(self):
        prompt = self._completed_template(
            "Send the invoice next week and start the timer after the client approves."
        )

        # The broad intent matcher can legitimately see words that resemble other
        # commands. The routing layer must still treat template field values as data.
        self.assertIn("create_client", matching_write_intents(prompt))
        self.assertIn("send_document", matching_write_intents(prompt))
        self.assertIn("start_timer", matching_write_intents(prompt))

        plan = select_tool_plan(prompt)
        decision = local_action_decision_for_prompt(prompt, plan)

        self.assertTrue(plan.focused)
        self.assertEqual(plan.tool_names, ("create_client",))
        self.assertEqual(plan.max_tool_calls, 1)
        self.assertEqual(plan.max_tool_rounds, 1)
        self.assertFalse(plan.include_conversation_context)
        self.assertFalse(plan.include_page_context)
        self.assertTrue(decision.matched)
        self.assertIsNotNone(decision.action)
        self.assertEqual(
            decision.action.arguments["internal_note"],
            "Send the invoice next week and start the timer after the client approves.",
        )

    def test_incomplete_template_with_command_like_note_stays_local(self):
        prompt = CLIENT_TEMPLATE_TEXT.replace(
            "Contact first name:\n", "Contact first name: Andrew\n"
        ).replace(
            "Internal note:\n", "Internal note: Send invoice when ready.\n"
        )

        plan = select_tool_plan(prompt)
        decision = local_action_decision_for_prompt(prompt, plan)

        self.assertEqual(plan.tool_names, ("create_client",))
        self.assertTrue(decision.matched)
        self.assertIsNone(decision.action)
        self.assertIn("Contact last name", decision.error)
