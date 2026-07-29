from django.test import SimpleTestCase

from assistant.local_actions import CLIENT_TEMPLATE_TEXT, local_action_decision_for_prompt
from assistant.security import matching_write_intents, write_intent_matches
from assistant.tool_routing import select_tool_plan


class LocalClientTemplateRoutingTests(SimpleTestCase):
    def _completed_template(self):
        return CLIENT_TEMPLATE_TEXT.replace(
            "Contact first name:\n", "Contact first name: Andrew\n"
        ).replace("Contact last name:\n", "Contact last name: Standring\n")

    def test_rendered_template_authorizes_create_client_in_current_turn(self):
        prompt = self._completed_template()

        self.assertTrue(write_intent_matches(prompt=prompt, tool_name="create_client"))
        self.assertIn("create_client", matching_write_intents(prompt))

    def test_rendered_template_selects_focused_local_create_client_plan(self):
        prompt = self._completed_template()

        plan = select_tool_plan(prompt)
        decision = local_action_decision_for_prompt(prompt, plan)

        self.assertTrue(plan.focused)
        self.assertEqual(plan.tool_names, ("create_client",))
        self.assertTrue(decision.matched)
        self.assertIsNotNone(decision.action)
        self.assertEqual(decision.action.tool_name, "create_client")

    def test_incomplete_rendered_template_still_selects_local_correction_path(self):
        prompt = CLIENT_TEMPLATE_TEXT.replace(
            "Contact first name:\n", "Contact first name: Andrew\n"
        )

        plan = select_tool_plan(prompt)
        decision = local_action_decision_for_prompt(prompt, plan)

        self.assertEqual(plan.tool_names, ("create_client",))
        self.assertTrue(decision.matched)
        self.assertIsNone(decision.action)
        self.assertIn("Contact last name", decision.error)

    def test_underscore_template_labels_remain_supported(self):
        prompt = (
            "Create client\n"
            "contact_first_name: Andrew\n"
            "contact_last_name: Standring\n"
        )

        self.assertTrue(write_intent_matches(prompt=prompt, tool_name="create_client"))
