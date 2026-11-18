"""Black-box CLI tests for evaluator-style typed customer input."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from resolution_agent.db import get_summary


ROOT = Path(__file__).resolve().parents[1]


class InteractiveDemoTests(unittest.TestCase):
    def test_typed_complaints_run_exchange_refund_and_unknown_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "orders.db"
            customer_input = (
                "My order ORD-1001 arrived damaged.\n"
                "My order ORD-1002 arrived broken.\n"
                "My order ORD-9999 has a problem.\n"
                "exit\n"
            )
            process = subprocess.run(
                [sys.executable, "main.py", "--interactive", "--reset-db", "--db", str(db)],
                input=customer_input, text=True, capture_output=True,
                cwd=ROOT, timeout=15, check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn("initiate_refund -> SUCCESS", process.stdout)
            self.assertIn("confirm_exchange -> SUCCESS", process.stdout)
            self.assertIn("Please verify the order ID", process.stdout)
            summary = get_summary(db)
            self.assertEqual(len(summary["refunds"]), 1)
            self.assertEqual(len(summary["exchanges"]), 1)
            self.assertEqual(len(summary["notifications"]), 2)

    def test_no_order_id_requests_clarification_without_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "orders.db"
            process = subprocess.run(
                [sys.executable, "main.py", "--interactive", "--reset-db", "--db", str(db)],
                input="I got a broken item.\nquit\n", text=True, capture_output=True,
                cwd=ROOT, timeout=15, check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn("Please provide your order ID", process.stdout)
            self.assertEqual(get_summary(db)["refunds"], [])


if __name__ == "__main__":
    unittest.main()
