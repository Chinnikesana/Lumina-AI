"""Regression tests for the LLM client against the current OpenAI API surface.

The OpenAI API removed the request property ``spend_control`` and the
``/agents/sessions`` endpoints. The OpenAI-compatible (Groq) requests built by
``call_llm`` must therefore never carry removed request properties, never
target removed endpoints, and keep using the documented chat-completions
request shape so the existing fallback chain keeps working.

Only standard-library test tooling is used (unittest + unittest.mock) because
the repository has no third-party test framework. Synthetic values are used
throughout; no real keys, prompts or endpoints are exercised.
"""

import asyncio
import os
import unittest
from unittest import mock

# Synthetic settings so importing the application config never needs real
# secrets (src/core/config.py requires these at import time).
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/synthetic")
os.environ.setdefault("SUPABASE_URL", "https://synthetic.example.supabase.co")
os.environ.setdefault("ANON_KEY", "synthetic-anon-key")
os.environ.setdefault("SERVICE_ROLE_KEY", "synthetic-service-role-key")
os.environ.setdefault("JWT_SECRET", "synthetic-jwt-secret")
# The current OpenAI SDK refuses to construct a client with an empty api_key,
# so give the module-level Groq clients a synthetic key for the tests.
os.environ.setdefault("GROQ_API_KEY", "synthetic-groq-key")

from src.core import llm_client  # noqa: E402  (import after env setup)


class _StrictChatCompletions:
    """Stands in for the updated OpenAI-compatible chat completions API.

    It rejects any request that carries a property removed from the OpenAI API
    (e.g. ``spend_control``) and only accepts the documented chat-completions
    parameters that ``call_llm`` is allowed to send.
    """

    REMOVED_REQUEST_PROPERTIES = ("spend_control",)
    DOCUMENTED_REQUEST_PROPERTIES = {
        "model",
        "messages",
        "temperature",
        "max_tokens",
        "response_format",
    }

    def __init__(self, content: str = "synthetic completion"):
        self._content = content
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        removed = [p for p in self.REMOVED_REQUEST_PROPERTIES if p in kwargs]
        if removed:
            # Mirrors the API rejecting a removed request property.
            raise TypeError(f"unknown request property: {', '.join(removed)}")
        unexpected = set(kwargs) - self.DOCUMENTED_REQUEST_PROPERTIES
        if unexpected:
            raise TypeError(f"unexpected request properties: {sorted(unexpected)}")

        message = mock.Mock()
        message.content = self._content
        return mock.Mock(choices=[mock.Mock(message=message)])


class CallLlmRequestCompatibilityTest(unittest.TestCase):
    """``call_llm`` must keep working against the updated OpenAI API surface."""

    def test_chat_completions_requests_exclude_removed_api_surface(self):
        completions = _StrictChatCompletions(content="synthetic completion")
        fake_client = mock.Mock()
        fake_client.chat.completions = completions

        with mock.patch.object(llm_client, "groq_client", fake_client), \
                mock.patch.object(llm_client, "groq_client_2", None):
            content = asyncio.run(
                llm_client.call_llm(
                    prompt="synthetic prompt",
                    system_message="synthetic system message",
                    json_mode=True,
                )
            )

        # The primary Groq attempt succeeds end-to-end.
        self.assertEqual(content, "synthetic completion")
        self.assertEqual(len(completions.requests), 1)
        request = completions.requests[0]

        # Request properties removed from the OpenAI API are never sent.
        for removed_property in _StrictChatCompletions.REMOVED_REQUEST_PROPERTIES:
            self.assertNotIn(removed_property, request)

        # The removed /agents/sessions endpoints are never targeted.
        self.assertNotIn("/agents/sessions", str(request))

        # The documented chat-completions request shape is preserved.
        self.assertEqual(request["model"], llm_client.GROQ_PRIMARY_MODEL)
        self.assertEqual(
            request["messages"],
            [
                {"role": "system", "content": "synthetic system message"},
                {"role": "user", "content": "synthetic prompt"},
            ],
        )
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertIsInstance(request["max_tokens"], int)
        self.assertGreater(request["max_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
