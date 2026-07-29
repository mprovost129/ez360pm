"""Deterministic assistant fast paths for explicit structured commands.

These parsers never save data directly. They only produce arguments for an existing
registered tool, which still performs normal validation, duplicate detection, and
confirmation before execution.
"""

import re
from dataclasses import dataclass

CLIENT_TEMPLATE_TEXT = """Create this client:
Company/household:
Contact first name:
Contact last name:
Email:
Phone:
Billing address 1:
Billing address 2:
City:
State:
Postal code:
Country:
Internal note:
"""


@dataclass(frozen=True)
class LocalAction:
    tool_name: str
    arguments: dict


@dataclass(frozen=True)
class LocalActionDecision:
    """Describe whether a prompt belongs to a deterministic local workflow.

    ``matched`` stays true even when the template needs correction. This lets the
    assistant return a local validation message without sending partially completed
    customer data to OpenAI.
    """

    matched: bool
    tool_name: str = ""
    action: LocalAction | None = None
    error: str = ""


CLIENT_TEMPLATE_PREFIX_PATTERN = r"^\s*create\s+this\s+client\s*:\s*"
_CLIENT_TEMPLATE_PREFIX = re.compile(CLIENT_TEMPLATE_PREFIX_PATTERN, re.I)


def is_client_template_prompt(prompt):
    """Return True when the current message explicitly uses the local client template.

    The template prefix is a server-owned routing boundary. Once present, values in
    later fields (especially ``Internal note``) must be treated as client data rather
    than as additional assistant commands.
    """

    return bool(_CLIENT_TEMPLATE_PREFIX.match(str(prompt or "")))


_LABEL_ALIASES = {
    "company": "company_name",
    "company name": "company_name",
    "company/household": "company_name",
    "company or household": "company_name",
    "company or household name": "company_name",
    "household": "company_name",
    "household name": "company_name",
    "contact first name": "contact_first_name",
    "first name": "contact_first_name",
    "contact last name": "contact_last_name",
    "last name": "contact_last_name",
    "contact email": "contact_email",
    "email": "contact_email",
    "contact phone": "contact_phone",
    "phone": "contact_phone",
    "billing address": "billing_address_1",
    "billing address 1": "billing_address_1",
    "address": "billing_address_1",
    "address 1": "billing_address_1",
    "billing address 2": "billing_address_2",
    "address 2": "billing_address_2",
    "billing city": "billing_city",
    "city": "billing_city",
    "billing state": "billing_state",
    "state": "billing_state",
    "state/region": "billing_state",
    "billing postal code": "billing_postal_code",
    "postal code": "billing_postal_code",
    "zip": "billing_postal_code",
    "zip code": "billing_postal_code",
    "billing country": "billing_country",
    "country": "billing_country",
    "internal note": "internal_note",
    "note": "internal_note",
}
_CLIENT_ARGUMENT_DEFAULTS = {
    "company_name": "",
    "contact_first_name": "",
    "contact_last_name": "",
    "contact_email": "",
    "contact_phone": "",
    "billing_address_1": "",
    "billing_address_2": "",
    "billing_city": "",
    "billing_state": "",
    "billing_postal_code": "",
    "billing_country": "",
    "internal_note": "",
}


def _normalized_label(value):
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def inspect_client_template(prompt):
    """Inspect the exact copyable client template without calling OpenAI.

    A prompt beginning with ``Create this client:`` is always treated as a local
    workflow. Complete templates return a ``LocalAction``. Incomplete templates
    return a concise local validation error so they cannot fall through to the
    provider and consume tokens.
    """

    text = str(prompt or "")
    match = _CLIENT_TEMPLATE_PREFIX.match(text)
    if not match:
        return LocalActionDecision(matched=False)

    values = dict(_CLIENT_ARGUMENT_DEFAULTS)
    recognized = 0
    current_field = ""
    for raw_line in text[match.end() :].splitlines():
        line = raw_line.strip()
        if not line:
            if current_field == "internal_note" and values[current_field]:
                values[current_field] += "\n"
            continue
        if ":" in line:
            raw_label, raw_value = line.split(":", 1)
            field = _LABEL_ALIASES.get(_normalized_label(raw_label))
            if field:
                values[field] = raw_value.strip()
                current_field = field
                recognized += 1
                continue
        # The note is the only intentionally free-form multiline template field.
        # Preserve its continuation lines while ignoring unrecognized prose elsewhere.
        if current_field == "internal_note":
            separator = "\n" if values[current_field] else ""
            values[current_field] += separator + raw_line.rstrip()

    if recognized == 0:
        return LocalActionDecision(
            matched=True,
            tool_name="create_client",
            error=(
                "Use the Client template fields shown in the assistant. "
                "Contact first name and Contact last name are required."
            ),
        )

    missing = []
    if not values["contact_first_name"]:
        missing.append("Contact first name")
    if not values["contact_last_name"]:
        missing.append("Contact last name")
    if missing:
        return LocalActionDecision(
            matched=True,
            tool_name="create_client",
            error=(
                "Complete the required client template field"
                + ("s" if len(missing) > 1 else "")
                + ": "
                + ", ".join(missing)
                + ". The other fields are optional."
            ),
        )

    return LocalActionDecision(
        matched=True,
        tool_name="create_client",
        action=LocalAction(tool_name="create_client", arguments=values),
    )


def parse_client_template(prompt):
    """Return a complete local client action, preserving the original API."""

    return inspect_client_template(prompt).action


def local_action_decision_for_prompt(prompt, tool_plan):
    """Return a deterministic decision only for an approved focused plan."""

    if not tool_plan.focused or tool_plan.tool_names != ("create_client",):
        return LocalActionDecision(matched=False)
    return inspect_client_template(prompt)


def local_action_for_prompt(prompt, tool_plan):
    """Backward-compatible helper returning only a complete local action."""

    return local_action_decision_for_prompt(prompt, tool_plan).action
