from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from assistant.providers import OpenAIResponsesProvider


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
