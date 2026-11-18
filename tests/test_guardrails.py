"""Invalid tools, invalid JSON, business invariants and maximum iterations."""
import tempfile
import unittest
from pathlib import Path

from resolution_agent.agent import run_agent
from resolution_agent.contracts import Dispatcher
from resolution_agent.db import get_summary, initialize_database
from resolution_agent.tools import ResolutionTools


class EndlessProvider:
    def next_message(self, messages, tools):
        return {
            "role": "assistant", "content": None,
            "tool_calls": [{
                "id": "bad_call", "type": "function",
                "function": {"name": "hack_server", "arguments": "{}"},
            }],
        }


class GuardrailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "test.db"
        initialize_database(self.db)
        self.tools = ResolutionTools(self.db)
        self.dispatcher = Dispatcher(self.tools)

    def test_unknown_tool_is_rejected(self):
        result = self.dispatcher.dispatch("delete_all_orders", "{}")
        self.assertEqual(result["error"]["code"], "UNKNOWN_TOOL")

    def test_bad_json_is_safe(self):
        result = self.dispatcher.dispatch("lookup_order", "{oops")
        self.assertEqual(result["error"]["code"], "MALFORMED_JSON")

    def test_missing_and_wrong_type_arguments(self):
        self.assertEqual(self.dispatcher.dispatch("lookup_order", "{}")["error"]["code"],
                         "MISSING_ARGUMENTS")
        self.assertEqual(self.dispatcher.dispatch("lookup_order", '{"order_id": 42}')["error"]["code"],
                         "INVALID_ARGUMENTS")
        self.assertEqual(self.dispatcher.dispatch(
            "lookup_order", '{"order_id":"ORD-1001","extra":"oops"}'
        )["error"]["code"], "UNEXPECTED_ARGUMENTS")

    def test_refund_blocked_if_exchange_possible(self):
        result = self.tools.initiate_refund("ORD-1002", "Damaged product")
        self.assertEqual(result["error"]["code"], "EXCHANGE_AVAILABLE")
        self.assertEqual(get_summary(self.db)["refunds"], [])

    def test_exchange_blocked_if_no_stock(self):
        result = self.tools.confirm_exchange("ORD-1001")
        self.assertEqual(result["error"]["code"], "OUT_OF_STOCK")
        self.assertEqual(get_summary(self.db)["exchanges"], [])

    def test_notification_blocked_before_resolution(self):
        result = self.tools.send_notification("ORD-1002", "aarav@example.com", "Exchange done")
        self.assertEqual(result["error"]["code"], "UNRESOLVED_ORDER")

    def test_cannot_send_to_wrong_customer(self):
        self.tools.initiate_refund("ORD-1001", "Damaged product")
        result = self.tools.send_notification("ORD-1001", "attacker@example.com", "Refund done")
        self.assertEqual(result["error"]["code"], "RECIPIENT_MISMATCH")
        self.assertEqual(get_summary(self.db)["notifications"], [])

    def test_idempotent_exchange_no_double_stock_decrement(self):
        first = self.tools.confirm_exchange("ORD-1002")
        second = self.tools.confirm_exchange("ORD-1002")
        self.assertTrue(first["success"])
        self.assertTrue(second["data"]["already_processed"])
        stock = next(row["stock"] for row in get_summary(self.db)["inventory"]
                     if row["item_id"] == "SKU-SPEAKER")
        self.assertEqual(stock, 3)

    def test_iteration_ceiling_escalates(self):
        result = run_agent("Damaged ORD-1001", EndlessProvider(), self.dispatcher,
                           max_iterations=3)
        self.assertEqual(result.status, "escalated")
        self.assertEqual(result.iterations, 3)
        self.assertEqual(len(result.trace), 3)
        self.assertIn("human review", result.answer)


if __name__ == "__main__":
    unittest.main()
