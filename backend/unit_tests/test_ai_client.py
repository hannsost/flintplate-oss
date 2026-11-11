"""Offline client contract tests; no app/database imports or provider network calls."""

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class ClientTests(unittest.TestCase):
    def build(self, *, mock=False, key=None, base=None):
        spec = importlib.util.spec_from_file_location(
            "ai_client_under_test", Path(__file__).parents[1] / "app/ai/client.py"
        )
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        settings = SimpleNamespace(
            ai_mock_mode=mock,
            ai_requests_per_min=0,
            openai_api_key=key,
            openai_base_url=base,
            openai_model="test-model",
            ai_max_tokens=123,
        )
        constructor = Mock()
        modules = {
            "app.config": SimpleNamespace(get_settings=lambda: settings),
            "langchain_openai": SimpleNamespace(ChatOpenAI=constructor),
        }
        with patch.dict(sys.modules, modules):
            result = asyncio.run(client.get_llm())
        return result, constructor

    def test_mock_never_constructs_remote_client(self):
        result, ctor = self.build(
            mock=True, key="test-placeholder", base="http://localhost:11434/v1"
        )
        self.assertIsNone(result)
        ctor.assert_not_called()

    def test_custom_url_is_passed_through(self):
        result, ctor = self.build(key="test-placeholder", base="https://provider.example/v1")
        self.assertIs(result, ctor.return_value)
        self.assertEqual(ctor.call_args.kwargs["base_url"], "https://provider.example/v1")
        self.assertEqual(ctor.call_args.kwargs["api_key"], "test-placeholder")
        self.assertEqual(ctor.call_args.kwargs["model"], "test-model")

    def test_no_key_or_url_does_not_call_vendor(self):
        result, ctor = self.build()
        self.assertIsNone(result)
        ctor.assert_not_called()

    def test_local_provider_without_key_builds_client(self):
        result, ctor = self.build(base="http://localhost:11434/v1")
        self.assertIs(result, ctor.return_value)
        self.assertEqual(ctor.call_args.kwargs["api_key"], "ollama")
        self.assertEqual(ctor.call_args.kwargs["base_url"], "http://localhost:11434/v1")


if __name__ == "__main__":
    unittest.main()
