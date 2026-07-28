from types import SimpleNamespace

import httpx
import openai
from django.test import SimpleTestCase, override_settings

from assistant.providers import OpenAIResponsesProvider, ProviderError


class FakeResponse:
    _request_id = "req_test_123"

    def model_dump(self, *, mode):
        assert mode == "json"
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Ready."},
                    ],
                }
            ],
            "usage": {"input_tokens": 12, "output_tokens": 3},
        }


class FakeResponses:
    def __init__(self):
        self.payload = None

    def create(self, **kwargs):
        self.payload = kwargs
        return FakeResponse()


class RejectingResponses:
    def create(self, **kwargs):
        del kwargs
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        response = httpx.Response(
            400,
            request=request,
            headers={"x-request-id": "req_bad_123"},
        )
        raise openai.BadRequestError(
            "Invalid request",
            response=response,
            body={
                "message": (
                    "Invalid input for test@example.com or 774-555-0199 using "
                    "sk-testsecretreplaceme."
                ),
                "type": "invalid_request_error",
                "param": "input[3]",
                "code": "invalid_value",
            },
        )


@override_settings(AI_MAX_OUTPUT_TOKENS=900)
class OpenAIResponsesProviderTests(SimpleTestCase):
    def test_official_sdk_request_uses_guarded_responses_api_options(self):
        responses = FakeResponses()
        client = SimpleNamespace(responses=responses)
        provider = OpenAIResponsesProvider(
            api_key="test-key",
            model="test-model",
            timeout=15,
            client=client,
        )
        tools = [
            {
                "type": "function",
                "name": "find_projects",
                "description": "Find projects.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        ]

        result = provider.create_response(
            input_items=[{"role": "user", "content": "Show active projects."}],
            instructions="Use registered tools.",
            tools=tools,
            client_request_id="client-test-123",
        )

        self.assertEqual(responses.payload["model"], "test-model")
        self.assertEqual(responses.payload["tools"], tools)
        self.assertFalse(responses.payload["store"])
        self.assertFalse(responses.payload["parallel_tool_calls"])
        self.assertEqual(responses.payload["tool_choice"], "auto")
        self.assertEqual(responses.payload["max_output_tokens"], 900)
        self.assertEqual(
            responses.payload["extra_headers"]["X-Client-Request-Id"],
            "client-test-123",
        )
        self.assertEqual(result.text, "Ready.")
        self.assertEqual(result.request_id, "req_test_123")
        self.assertEqual(result.client_request_id, "client-test-123")

    def test_bad_request_logs_safe_provider_details_and_request_shape(self):
        provider = OpenAIResponsesProvider(
            api_key="test-key",
            model="test-model",
            timeout=15,
            client=SimpleNamespace(responses=RejectingResponses()),
        )

        with self.assertLogs("assistant.providers", level="WARNING") as captured:
            with self.assertRaises(ProviderError) as raised:
                provider.create_response(
                    input_items=[
                        {"role": "user", "content": "private prompt"},
                        {
                            "type": "function_call_output",
                            "call_id": "call-1",
                            "output": "private output",
                        },
                    ],
                    instructions="Use registered tools.",
                    tools=[],
                    client_request_id="client-test-400",
                )

        message = captured.output[0]
        self.assertIn("error_type=invalid_request_error", message)
        self.assertIn("error_code=invalid_value", message)
        self.assertIn("error_param=input[3]", message)
        self.assertIn("input_items=function_call_output:1,user:1", message)
        self.assertIn("[email]", message)
        self.assertIn("[phone]", message)
        self.assertIn("[api-key]", message)
        self.assertNotIn("test@example.com", message)
        self.assertNotIn("774-555-0199", message)
        self.assertNotIn("sk-testsecretreplaceme", message)
        self.assertEqual(raised.exception.code, "provider_rejected_request")
        self.assertEqual(raised.exception.provider_request_id, "req_bad_123")
