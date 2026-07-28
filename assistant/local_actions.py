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


_CLIENT_TEMPLATE_PREFIX = re.compile(r"^\s*create\s+this\s+client\s*:\s*", re.I)
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


def parse_client_template(prompt):
    """Parse the assistant's exact copyable client template.

    The parser is intentionally label-based and conservative. Free-form natural
    language continues through OpenAI; only an explicit ``Create this client:``
    template can use this zero-token path.
    """

    text = str(prompt or "")
    match = _CLIENT_TEMPLATE_PREFIX.match(text)
    if not match:
        return None

    values = dict(_CLIENT_ARGUMENT_DEFAULTS)
    recognized = 0
    for raw_line in text[match.end() :].splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        raw_label, raw_value = line.split(":", 1)
        field = _LABEL_ALIASES.get(_normalized_label(raw_label))
        if not field:
            continue
        values[field] = raw_value.strip()
        recognized += 1

    if recognized == 0:
        return None
    if not values["contact_first_name"] or not values["contact_last_name"]:
        return None
    return LocalAction(tool_name="create_client", arguments=values)


def local_action_for_prompt(prompt, tool_plan):
    """Return a deterministic action only for an already focused server plan."""

    if not tool_plan.focused or tool_plan.tool_names != ("create_client",):
        return None
    return parse_client_template(prompt)
