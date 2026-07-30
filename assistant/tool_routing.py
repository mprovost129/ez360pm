import re
from dataclasses import dataclass

from .local_actions import is_client_template_prompt
from .security import matching_write_intents


@dataclass(frozen=True)
class ToolPlan:
    """A server-selected, minimal tool catalog for one assistant request."""

    tool_names: tuple[str, ...] | None = None
    focus_instruction: str = ""
    max_tool_calls: int | None = None
    max_tool_rounds: int | None = None
    include_conversation_context: bool = True
    include_page_context: bool = True
    force_tool_name: str = ""

    @property
    def focused(self):
        return self.tool_names is not None


_DIRECT_WRITE_TOOLS = {
    "create_project_activity",
    "create_note",
    "start_timer",
    "pause_timer",
    "resume_timer",
    "stop_timer",
    "create_client",
    "update_client",
    "add_contact",
    "update_contact",
    "set_primary_contact",
    "create_project",
    "update_project_details",
    "change_project_status",
    "attach_note_to_client",
    "attach_note_to_project",
}


def _create_client_identity_is_present(prompt):
    """Return True only when the current message appears to contain a usable name.

    This is intentionally conservative. A false result leaves tool choice on auto so
    the model can ask one concise question. A true result lets the server force the
    one exposed create-client tool and avoid a text-only detour.
    """

    text = str(prompt or "").strip()
    if re.search(
        r"\bcontact(?:_|\s+)first(?:_|\s+)name\s*:\s*\S+.{0,1200}"
        r"\bcontact(?:_|\s+)last(?:_|\s+)name\s*:\s*\S+",
        text,
        flags=re.I | re.S,
    ):
        return True

    name_token = r"[A-Za-z][A-Za-z'’-]*"
    patterns = (
        rf"\b(?:add|create|make|prepare)\s+({name_token})\s+({name_token})\s+as\s+(?:a\s+|new\s+)?(?:client|customer)\b",
        rf"\b(?:create|add|make|prepare)\s+(?:a\s+|new\s+)?(?:client|customer)\s+(?:(?:for|named)\s+)?({name_token})\s+({name_token})\b",
    )
    return any(re.search(pattern, text, flags=re.I) for pattern in patterns)


def _single_action_plan(tool_name, *, prompt=""):
    instructions = {
        "create_client": (
            "This is a focused create-client request. Use create_client directly once. "
            "Do not search clients or contacts first; the server confirmation preview "
            "performs the company-scoped duplicate check. Only contact first and last "
            "name require non-empty values. Use empty strings for omitted optional fields."
        ),
        "change_project_status": (
            "This is a focused project-status request. Use change_project_status once. "
            "Do not edit unrelated project fields."
        ),
    }.get(
        tool_name,
        (
            f"This is a focused {tool_name.replace('_', ' ')} request. Use only the "
            "provided tool and call it at most once. If required information is missing, "
            "ask one concise question instead of searching broadly."
        ),
    )
    force_tool_name = ""
    if tool_name == "create_client" and _create_client_identity_is_present(prompt):
        force_tool_name = tool_name
    return ToolPlan(
        tool_names=(tool_name,),
        focus_instruction=instructions,
        max_tool_calls=1,
        max_tool_rounds=1,
        include_conversation_context=False,
        # Current-page context remains useful for commands such as "update this project."
        include_page_context=tool_name != "create_client",
        force_tool_name=force_tool_name,
    )


def select_tool_plan(prompt):
    """Narrow obvious single-action writes to one server-approved tool.

    Ambiguous or multi-part prompts deliberately keep the normal catalog so the model
    can ask a question or select the correct workflow. The plan never expands company
    permissions; registry policy filtering still applies afterwards.
    """

    # The explicit, server-owned client template is a routing boundary. Values in
    # later fields are business data, not additional commands. Give the template
    # precedence so an internal note such as "send the invoice next week" cannot
    # expand the request into unrelated AI tools or send customer data to OpenAI.
    if is_client_template_prompt(prompt):
        return _single_action_plan("create_client", prompt=prompt)

    matches = set(matching_write_intents(prompt))
    if not matches:
        return ToolPlan()

    # Prefer the purpose-built combined workflow over separate client/project actions.
    if "create_client_and_project_from_note" in matches:
        return ToolPlan(
            tool_names=("create_client_and_project_from_note",),
            focus_instruction=(
                "This is a focused intake-note conversion. Use "
                "create_client_and_project_from_note once; do not prepare separate "
                "client and project actions."
            ),
            max_tool_calls=1,
            max_tool_rounds=1,
            include_conversation_context=False,
        )

    # Status language can also match the generic project-update pattern. Keep only the
    # dedicated workflow so status rules cannot be bypassed through ordinary editing.
    if "change_project_status" in matches and matches.issubset(
        {"change_project_status", "update_project_details"}
    ):
        return _single_action_plan("change_project_status", prompt=prompt)

    if len(matches) == 1:
        tool_name = next(iter(matches))
        if tool_name in _DIRECT_WRITE_TOOLS:
            return _single_action_plan(tool_name, prompt=prompt)

    return ToolPlan()
