import logging
from dataclasses import dataclass

import openai
from django.conf import settings
from openai import OpenAI

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    def __init__(
        self,
        message,
        *,
        code="provider_error",
        provider_request_id="",
        client_request_id="",
        status_code=None,
    ):
        self.code = code
        self.provider_request_id = provider_request_id or ""
        self.client_request_id = client_request_id or ""
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class ProviderResponse:
    raw: dict

    @property
    def output(self):
        return self.raw.get("output", [])

    @property
    def usage(self):
        return self.raw.get("usage") or {}

    @property
    def text(self):
        parts = []
        for item in self.output:
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    parts.append(content["text"])
        return "\n".join(parts).strip()

    @property
    def function_calls(self):
        return [item for item in self.output if item.get("type") == "function_call"]

    @property
    def request_id(self):
        return self.raw.get("_request_id", "")

    @property
    def client_request_id(self):
        return self.raw.get("_client_request_id", "")


class BaseProvider:
    name = "base"
    supports_client_request_id = False

    def create_response(
        self, *, input_items, instructions, tools, client_request_id=None
    ):
        raise NotImplementedError


class OpenAIResponsesProvider(BaseProvider):
    """OpenAI Responses API adapter using the official OpenAI Python SDK."""

    name = "openai"
    supports_client_request_id = True

    def __init__(self, *, api_key=None, model=None, timeout=None, client=None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.AI_MODEL
        self.timeout = timeout or settings.AI_PROVIDER_TIMEOUT_SECONDS
        self.client = client or OpenAI(
            api_key=self.api_key,
            organization=getattr(settings, "OPENAI_ORG_ID", "") or None,
            project=getattr(settings, "OPENAI_PROJECT_ID", "") or None,
            timeout=self.timeout,
            max_retries=1,
        )

    def create_response(
        self, *, input_items, instructions, tools, client_request_id=None
    ):
        request_kwargs = {
            "model": self.model,
            "input": input_items,
            "instructions": instructions,
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "store": False,
            "max_output_tokens": settings.AI_MAX_OUTPUT_TOKENS,
        }
        if client_request_id:
            request_kwargs["extra_headers"] = {
                "X-Client-Request-Id": str(client_request_id)
            }
        try:
            response = self.client.responses.create(**request_kwargs)
        except openai.APITimeoutError as exc:
            raise ProviderError(
                "The OpenAI API timed out. No EZ360PM action was performed.",
                code="provider_timeout",
                client_request_id=client_request_id,
            ) from exc
        except openai.RateLimitError as exc:
            raise ProviderError(
                "The OpenAI API rate limit was reached. No EZ360PM action was performed.",
                code="provider_rate_limit",
                provider_request_id=getattr(exc, "request_id", "") or "",
                client_request_id=client_request_id,
                status_code=getattr(exc, "status_code", None),
            ) from exc
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise ProviderError(
                "The OpenAI API credentials or permissions were rejected.",
                code="provider_authentication",
                provider_request_id=getattr(exc, "request_id", "") or "",
                client_request_id=client_request_id,
                status_code=getattr(exc, "status_code", None),
            ) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError(
                "The OpenAI API could not be reached. No EZ360PM action was performed.",
                code="provider_unavailable",
                client_request_id=client_request_id,
            ) from exc
        except openai.APIStatusError as exc:
            logger.warning(
                "OpenAI Responses API returned HTTP %s (request_id=%s).",
                exc.status_code,
                exc.request_id,
            )
            raise ProviderError(
                "The OpenAI API rejected the request. No EZ360PM action was performed.",
                code="provider_rejected_request",
                provider_request_id=getattr(exc, "request_id", "") or "",
                client_request_id=client_request_id,
                status_code=getattr(exc, "status_code", None),
            ) from exc
        except openai.OpenAIError as exc:
            raise ProviderError(
                "The OpenAI API failed safely. No EZ360PM action was performed.",
                code="provider_error",
                provider_request_id=getattr(exc, "request_id", "") or "",
                client_request_id=client_request_id,
                status_code=getattr(exc, "status_code", None),
            ) from exc

        raw = response.model_dump(mode="json")
        raw["_request_id"] = getattr(response, "_request_id", "") or ""
        raw["_client_request_id"] = str(client_request_id or "")
        return ProviderResponse(raw)


def get_provider(*, model=None):
    provider_name = settings.AI_PROVIDER.lower().strip()
    if provider_name != "openai":
        raise ProviderError(
            "The configured AI provider is not supported.",
            code="unsupported_provider",
        )
    if not settings.OPENAI_API_KEY:
        raise ProviderError(
            "The OpenAI API key is not configured.",
            code="provider_not_configured",
        )
    return OpenAIResponsesProvider(model=model)
