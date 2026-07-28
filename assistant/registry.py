import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone

from .models import AIActionAttempt
from .schema import validate_arguments


@dataclass(frozen=True)
class ActionContext:
    user: object
    interaction: object
    policy: object | None = None

    @property
    def company(self):
        return self.user.company


@dataclass(frozen=True)
class ToolResult:
    data: dict
    pending_action: AIActionAttempt | None = None


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    input_schema: dict
    handler: object
    risk_level: str = "read"
    executor: object | None = None

    def api_definition(self):
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
            "strict": True,
        }


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, tool):
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def definitions(self, *, policy=None):
        if policy is None:
            return [tool.api_definition() for tool in self._tools.values()]
        from .policies import allowed_risk_levels

        permitted = allowed_risk_levels(policy)
        return [
            tool.api_definition()
            for tool in self._tools.values()
            if tool.risk_level in permitted
        ]

    def all_tools(self):
        return tuple(self._tools.values())

    def get(self, name):
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ValueError("The requested assistant action is not registered.") from exc

    def invoke(self, *, context, name, arguments):
        tool = self.get(name)
        if context.policy is not None:
            from .policies import require_risk_allowed

            require_risk_allowed(context.policy, tool.risk_level, user=context.user)
        normalized = validate_arguments(tool.input_schema, arguments)
        if tool.risk_level == "read":
            return ToolResult(tool.handler(context, normalized))
        return self._prepare_action(context=context, tool=tool, arguments=normalized)

    def _prepare_action(self, *, context, tool, arguments):
        preview = dict(tool.handler(context, arguments))
        execution_arguments = preview.pop("_execution_arguments", arguments)
        canonical = json.dumps(
            execution_arguments,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        key_source = f"{context.interaction.pk}:{tool.name}:{canonical}"
        idempotency_key = hashlib.sha256(key_source.encode()).hexdigest()
        expiry_minutes = (
            3
            if tool.risk_level == AIActionAttempt.RiskLevel.EXTERNAL_COMMIT
            else 10
        )
        defaults = {
            "company": context.company,
            "user": context.user,
            "interaction": context.interaction,
            "tool_name": tool.name,
            "risk_level": tool.risk_level,
            "normalized_arguments": execution_arguments,
            "preview": preview,
            "confirmation_expires_at": timezone.now()
            + timedelta(minutes=expiry_minutes),
        }
        try:
            attempt, _ = AIActionAttempt.objects.get_or_create(
                idempotency_key=idempotency_key,
                defaults=defaults,
            )
        except IntegrityError:
            attempt = AIActionAttempt.objects.get(idempotency_key=idempotency_key)
        return ToolResult(
            {
                "confirmation_required": True,
                "action": preview,
                "confirmation_token": str(attempt.confirmation_token),
            },
            pending_action=attempt,
        )

    def execute_attempt(self, *, attempt, policy=None):
        tool = self.get(attempt.tool_name)
        if policy is not None:
            from .policies import require_risk_allowed

            require_risk_allowed(policy, tool.risk_level, user=attempt.user)
        if tool.executor is None:
            raise ValueError("This assistant action cannot be executed.")
        context = ActionContext(user=attempt.user, interaction=attempt.interaction, policy=policy)
        return tool.executor(context, attempt.normalized_arguments)


registry = ToolRegistry()
