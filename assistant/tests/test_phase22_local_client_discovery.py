from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from assistant.local_actions import CLIENT_TEMPLATE_TEXT, parse_client_template
from assistant.services import FOCUSED_SYSTEM_INSTRUCTIONS


class LocalClientDiscoveryTests(SimpleTestCase):
    def test_server_owned_template_parses_and_is_used_in_focused_instructions(self):
        completed = CLIENT_TEMPLATE_TEXT.replace(
            "Contact first name:\n", "Contact first name: Andrew\n"
        ).replace("Contact last name:\n", "Contact last name: Standring\n")

        action = parse_client_template(completed)

        self.assertIsNotNone(action)
        self.assertEqual(action.tool_name, "create_client")
        self.assertIn(CLIENT_TEMPLATE_TEXT.strip(), FOCUSED_SYSTEM_INSTRUCTIONS)

    def test_drawer_exposes_persistent_local_client_template_control(self):
        template = (
            Path(settings.BASE_DIR) / "templates" / "assistant" / "_drawer.html"
        ).read_text()

        self.assertIn("data-assistant-client-template-source", template)
        self.assertIn("data-assistant-client-template", template)
        self.assertIn("without calling OpenAI", template)

    def test_drawer_javascript_uses_reversed_action_center_base_url(self):
        source = (Path(settings.BASE_DIR) / "static" / "js" / "assistant.js").read_text()

        self.assertIn("drawer.dataset.assistantActionCenterUrl", source)
        self.assertIn("actionUrl(token, mode)", source)
        self.assertNotIn("`/assistant/actions/${token}/${mode}/`", source)

    def test_drawer_supports_keyboard_submit_and_local_template_fill(self):
        source = (Path(settings.BASE_DIR) / "static" / "js" / "assistant.js").read_text()

        self.assertIn('event.key === "Enter"', source)
        self.assertIn("form.requestSubmit()", source)
        self.assertIn("fillClientTemplate", source)
