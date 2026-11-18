"""End-to-end acceptance tests: refund, exchange, eligibility, invalid order."""
import tempfile
import unittest
from pathlib import Path

from resolution_agent.agent import OfflinePlanner, run_agent
from resolution_agent.contracts import Dispatcher
from resolution_agent.db import connect, get_summary, initialize_database
from resolution_agent.tools import ResolutionTools


class AgentAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "test.db"
        initialize_database(self.db)
        self.tools = ResolutionTools(self.db)
        self.dispatcher = Dispatcher(self.tools)

    def resolve(self, order_id: str):
        return run_agent(
            f"My order {order_id} arrived damaged. Please resolve it.",
            OfflinePlanner(), self.dispatcher, max_iterations=5,
        )

    def test_out_of_stock_triggers_refund_and_email(self):
        result = self.resolve("ORD-1001")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.iterations, 5)
        self.assertEqual([entry["tool"] for entry in result.trace], [
            "lookup_order", "inspect_inventory", "initiate_refund", "send_notification",
        ])
        self.assertIn("₹3499.00", result.answer)
        db = get_summary(self.db)
        self.assertIn({"order_id": "ORD-1001", "order_status": "refunded"}, db["orders"])
        self.assertEqual(len(db["refunds"]), 1)
        self.assertEqual(len(db["exchanges"]), 0)
        self.assertEqual(db["notifications"][0]["email"], "maya@example.com")

    def test_in_stock_triggers_exchange_not_refund(self):
        result = self.resolve("ORD-1002")
        self.assertEqual(result.status, "completed")
        self.assertEqual([entry["tool"] for entry in result.trace], [
            "lookup_order", "inspect_inventory", "confirm_exchange", "send_notification",
        ])
        db = get_summary(self.db)
        self.assertEqual(len(db["refunds"]), 0)
        self.assertEqual(len(db["exchanges"]), 1)
        stock = next(row["stock"] for row in db["inventory"] if row["item_id"] == "SKU-SPEAKER")
        self.assertEqual(stock, 3)
        self.assertEqual(db["notifications"][0]["email"], "aarav@example.com")

    def test_ineligible_order_refunded_even_with_stock(self):
        result = self.resolve("ORD-1003")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.trace[2]["tool"], "initiate_refund")
        self.assertEqual(len(get_summary(self.db)["refunds"]), 1)
        self.assertEqual(next(row["stock"] for row in get_summary(self.db)["inventory"]
                              if row["item_id"] == "SKU-SLEEVE"), 2)

    def test_unknown_order_gracefully_requests_verification(self):
        result = self.resolve("ORD-9999")
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.trace), 1)
        self.assertFalse(result.trace[0]["result"]["success"])
        self.assertIn("verify", result.answer.lower())
        self.assertEqual(get_summary(self.db)["notifications"], [])

    def test_idempotent_repeat_no_second_refund_or_email(self):
        self.resolve("ORD-1001")
        second = self.resolve("ORD-1001")
        self.assertIn("already refunded", second.answer)
        db = get_summary(self.db)
        self.assertEqual(len(db["refunds"]), 1)
        self.assertEqual(len(db["notifications"]), 1)

    def test_already_refunded_tool_returns_same_reference(self):
        first = self.tools.initiate_refund("ORD-1001", "Damaged item")
        second = self.tools.initiate_refund("ORD-1001", "Damaged item again")
        self.assertTrue(first["success"])
        self.assertTrue(second["data"]["already_processed"])
        self.assertEqual(first["data"]["refund_reference"],
                         second["data"]["refund_reference"])

    def test_model_conversation_history_keeps_tool_call_ids(self):
        result = self.resolve("ORD-1002")
        tool_messages = [message for message in result.history if message["role"] == "tool"]
        self.assertEqual(len(tool_messages), 4)
        self.assertTrue(all(message.get("tool_call_id") for message in tool_messages))


if __name__ == "__main__":
    unittest.main()
