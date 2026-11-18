"""Gemini provider tests using mocked OpenAI-compatible responses: no API key or network."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from resolution_agent.agent import GEMINI_OPENAI_COMPAT_BASE_URL, GeminiProvider, run_agent, safe_provider_error
from resolution_agent.contracts import Dispatcher
from resolution_agent.db import get_summary, initialize_database
from resolution_agent.tools import ResolutionTools


class FakeGeminiClient:
    def __init__(self, **options):
        self.options = options
        self.requests = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create)
        )

    def create(self, **request):
        self.requests.append(request)
        history = request["messages"]
        results = {}
        for message in history:
            if message["role"] == "tool":
                results[message["name"]] = json.loads(message["content"])
        if not results:
            name, args = "lookup_order", {"order_id": "ORD-1001"}
        elif "lookup_order" in results and "inspect_inventory" not in results:
            name, args = "inspect_inventory", {"item_id": "SKU-HEADPHONES"}
        elif "inspect_inventory" in results and "initiate_refund" not in results:
            name, args = "initiate_refund", {
                "order_id": "ORD-1001", "reason": "Damaged headphones; no replacement stock"
            }
        elif "initiate_refund" in results and "send_notification" not in results:
            name, args = "send_notification", {
                "order_id": "ORD-1001", "customer_email": "maya@example.com",
                "message": "Mock refund for damaged item has been recorded."
            }
        else:
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="Your mock refund and confirmation have been recorded.",
                tool_calls=None, model_extra={}
            ))])
        tool = SimpleNamespace(
            id=f"call_{len(self.requests)}", model_extra={
                "extra_content": {"google": {"thought_signature": "MOCK_SIGNATURE"}}
            },
            function=SimpleNamespace(name=name, arguments=json.dumps(args)),
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=None, tool_calls=[tool], model_extra={}
        ))])


class GeminiProviderTests(unittest.TestCase):
    def test_missing_key_is_actionable(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                GeminiProvider()

    def test_gemini_uses_correct_endpoint_model_and_no_openai_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "google-test-key", "OPENAI_API_KEY": "openai-test-key"}):
            with patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=FakeGeminiClient)}):
                provider = GeminiProvider()
        self.assertEqual(provider.model, "gemini-3.8-flash")
        self.assertEqual(provider.client.options["timeout"], 45.0)
        self.assertEqual(provider.client.options["max_retries"], 0)
        self.assertEqual(provider.client.options["api_key"], "google-test-key")
        self.assertEqual(provider.client.options["base_url"], GEMINI_OPENAI_COMPAT_BASE_URL)
        self.assertNotIn("openai-test-key", str(provider.client.options))

    def test_provider_replays_signature_and_completes_refund(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "orders.db"
            initialize_database(db_path)
            with patch.dict(os.environ, {"GEMINI_API_KEY": "google-test-key"}):
                with patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=FakeGeminiClient)}):
                    provider = GeminiProvider()
            result = run_agent(
                "My order ORD-1001 is damaged", provider,
                Dispatcher(ResolutionTools(db_path)), max_iterations=5,
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual([t["tool"] for t in result.trace], [
                "lookup_order", "inspect_inventory", "initiate_refund", "send_notification"
            ])
            self.assertEqual(len(get_summary(db_path)["refunds"]), 1)
            self.assertEqual(len(get_summary(db_path)["notifications"]), 1)
            request = provider.client.requests[-1]
            self.assertEqual(request["model"], "gemini-3.8-flash")
            self.assertEqual(len(request["tools"]), 5)
            self.assertNotIn("parallel_tool_calls", request)
            self.assertTrue(all(
                "additionalProperties" not in t["function"]["parameters"]
                for t in request["tools"]
            ))
            self.assertTrue(any(
                m.get("tool_calls") and m["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "MOCK_SIGNATURE"
                for m in request["messages"] if m["role"] == "assistant"
            ))

    def test_gemini_schema_cleanup_keeps_original_tool_contracts(self):
        from resolution_agent.contracts import TOOL_SCHEMAS
        with patch.dict(os.environ, {"GEMINI_API_KEY": "google-test-key"}):
            with patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=FakeGeminiClient)}):
                provider = GeminiProvider()
        provider.next_message([{"role": "user", "content": "Hi"}], TOOL_SCHEMAS)
        sent_tools = provider.client.requests[0]["tools"]
        self.assertTrue(all(
            "additionalProperties" not in tool["function"]["parameters"]
            for tool in sent_tools
        ))
        self.assertTrue(all(
            tool["function"]["parameters"]["additionalProperties"] is False
            for tool in TOOL_SCHEMAS
        ))

    def test_provider_error_shows_google_message_without_exposing_keys(self):
        class FakeBadRequest(Exception):
            body = {"message": 'Unknown name "additionalProperties" in tool schema',
                    "code": "INVALID_ARGUMENT"}
            status_code = 400
        self.assertIn('Unknown name "additionalProperties"', safe_provider_error(FakeBadRequest()))
        class FakeSecretError(Exception):
            body = {"message": "Authentication failed for sk-proj-EXAMPLESECRET123456789 key=verysecret"}
            status_code = 400
        summary = safe_provider_error(FakeSecretError())
        self.assertNotIn("EXAMPLESECRET", summary)
        self.assertNotIn("verysecret", summary)

    def test_cli_requires_gemini_key_before_running(self):
        import subprocess
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            completed = subprocess.run(
                [sys.executable, "main.py", "--interactive", "--mode", "gemini", "--db", ":memory:"],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True, text=True,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("GEMINI_API_KEY", completed.stderr)


if __name__ == "__main__":
    unittest.main()


class ProgressTests(unittest.TestCase):
    def test_agent_reports_model_cycles_and_tool_calls(self):
        from resolution_agent.agent import OfflinePlanner
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "orders.db"
            initialize_database(db_path)
            updates = []
            result = run_agent(
                "My order ORD-1001 arrived damaged", OfflinePlanner(),
                Dispatcher(ResolutionTools(db_path)), progress=updates.append,
            )
            self.assertEqual(result.status, "completed")
            self.assertTrue(any("contacting model" in line for line in updates))
            self.assertTrue(any("Tool initiate_refund: SUCCESS" in line for line in updates))
