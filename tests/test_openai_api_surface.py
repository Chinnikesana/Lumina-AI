"""Regression test guarding the OpenAI API surface used by ``call_llm``.

The OpenAI spec removed the ``/assistants``, ``/conversations``,
``/audio/translations`` and ``/evals`` endpoints, and removed the ``auto``
value from the Assistants API response-format and chunking-strategy enums.
``call_llm`` only talks to chat completions, so it must keep targeting that
resource with a documented request shape and must never reach for any of the
removed resources (or send the removed ``auto`` response-format value).

Only standard-library test tooling (unittest + unittest.mock) is used;
synthetic prompts and completions are used throughout.
"""

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest import mock

# Synthetic settings so importing the application config never needs real
# secrets (src/core/config.py requires these at import time).
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/synthetic")
os.environ.setdefault("SUPABASE_URL", "https://synthetic.example.supabase.co")
os.environ.setdefault("ANON_KEY", "synthetic-anon-key")
os.environ.setdefault("SERVICE_ROLE_KEY", "synthetic-service-role-key")
os.environ.setdefault("JWT_SECRET", "synthetic-jwt-secret")
os.environ.setdefault("GROQ_API_KEY", "synthetic-groq-key")

from src.core import llm_client  # noqa: E402  (import after env setup)


class _StrictChatCompletions:
    """Stands in for the documented chat-completions create endpoint."""

    DOCUMENTED_REQUEST_PROPERTIES = {
        "model",
        "messages",
        "temperature",
        "max_tokens",
        "response_format",
    }
    REMOVED_RESPONSE_FORMAT_TYPES = {"auto"}

    def __init__(self, content: str = "synthetic completion"):
        self._content = content
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)

        unexpected = set(kwargs) - self.DOCUMENTED_REQUEST_PROPERTIES
        if unexpected:
            raise TypeError(f"unexpected request properties: {sorted(unexpected)}")

        response_format = kwargs.get("response_format")
        if isinstance(response_format, dict):
            # ``auto`` was removed from the Assistants API response-format
            # enum; the chat-completions path must not send it.
            if response_format.get("type") in self.REMOVED_RESPONSE_FORMAT_TYPES:
                raise ValueError(f"removed response_format type: {response_format}")

        message = mock.Mock()
        message.content = self._content
        return mock.Mock(choices=[mock.Mock(message=message)])


class _ChatOnlyClient:
    """Exposes only ``chat.completions`` and rejects removed resources."""

    REMOVED_NAMESPACES = ("assistants", "conversations", "evals", "audio")

    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)

    def __getattr__(self, name):
        if name in self.REMOVED_NAMESPACES:
            raise AssertionError(f"call_llm used removed OpenAI resource: {name}")
        raise AttributeError(name)


class OpenAIApiSurfaceTest(unittest.TestCase):
    """``call_llm`` must only use the still-supported chat-completions API."""

    def test_call_llm_uses_only_chat_completions(self):
        completions = _StrictChatCompletions(content="synthetic completion")
        client = _ChatOnlyClient(completions)

        with mock.patch.object(llm_client, "groq_client", client), \
                mock.patch.object(llm_client, "groq_client_2", None):
            content = asyncio.run(
                llm_client.call_llm(
                    prompt="synthetic prompt",
                    system_message="synthetic system message",
                    json_mode=True,
                )
            )

        self.assertEqual(content, "synthetic completion")
        self.assertEqual(len(completions.requests), 1)
        request = completions.requests[0]

        # JSON mode keeps using the still-supported ``json_object`` value.
        self.assertEqual(request["response_format"], {"type": "json_object"})

        # ``auto`` was removed from the Assistants API enums, not chat
        # completions; it must never be sent on this path.
        self.assertNotEqual(request["response_format"].get("type"), "auto")

        # The documented chat-completions request shape is preserved.
        self.assertEqual(request["model"], llm_client.GROQ_PRIMARY_MODEL)
        self.assertEqual(
            request["messages"],
            [
                {"role": "system", "content": "synthetic system message"},
                {"role": "user", "content": "synthetic prompt"},
            ],
        )
        self.assertIsInstance(request["max_tokens"], int)
        self.assertGreater(request["max_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
