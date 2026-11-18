"""Deterministic, validated tool implementations with defensive business rules."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .db import connect


def ok(action: str, **data: Any) -> dict:
    return {"success": True, "action": action, "data": data}


def err(action: str, code: str, message: str) -> dict:
    return {"success": False, "action": action,
            "error": {"code": code, "message": message}}


def inr(paise: int) -> str:
    return f"{paise // 100}.{paise % 100:02d}"


class ResolutionTools:
    """All financial/logistics/email actions are local simulations, NOT real services."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def lookup_order(self, order_id: str) -> dict:
        action = "lookup_order"
        with connect(self.db_path) as conn:
            order = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
        if order is None:
            return err(action, "ORDER_NOT_FOUND",
                       f"Order {order_id!r} was not found. Please verify the order ID.")
        return ok(action,
                  order_id=order["order_id"], customer_name=order["customer_name"],
                  customer_email=order["customer_email"], item_id=order["item_id"],
                  item_name=order["item_name"], order_status=order["order_status"],
                  exchange_eligible=bool(order["exchange_eligible"]),
                  amount_inr=inr(order["amount_paise"]),
                  payment_method=order["payment_method"])

    def inspect_inventory(self, item_id: str) -> dict:
        action = "inspect_inventory"
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT stock FROM inventory WHERE item_id = ?", (item_id,)
            ).fetchone()
        if row is None:
            return err(action, "INVENTORY_NOT_FOUND",
                       f"Inventory for {item_id!r} is unavailable. Escalate for review.")
        return ok(action, item_id=item_id, stock_count=row["stock"],
                  available=row["stock"] > 0)

    def confirm_exchange(self, order_id: str) -> dict:
        """Atomically reserve one unit. Repeated calls return the same reference."""
        action = "confirm_exchange"
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            if order is None:
                return err(action, "ORDER_NOT_FOUND", "Order not found.")
            if order["order_status"] == "exchanged":
                ref = conn.execute(
                    "SELECT exchange_reference FROM exchanges WHERE order_id = ?",
                    (order_id,)
                ).fetchone()
                if ref:
                    return ok(action, order_id=order_id,
                              exchange_reference=ref["exchange_reference"], already_processed=True)
                return err(action, "DATA_INCONSISTENCY", "Exchange record is missing.")
            if order["order_status"] != "delivered":
                return err(action, "INVALID_ORDER_STATUS",
                           f"Order is {order['order_status']}; exchange not permitted.")
            if not order["exchange_eligible"]:
                return err(action, "NOT_ELIGIBLE", "Order is not eligible for exchange.")
            changed = conn.execute(
                "UPDATE inventory SET stock = stock - 1 WHERE item_id = ? AND stock > 0",
                (order["item_id"],)
            ).rowcount
            if changed != 1:
                return err(action, "OUT_OF_STOCK", "Replacement is no longer available.")
            reference = f"EXC-{order_id}"
            conn.execute(
                "INSERT INTO exchanges (order_id, exchange_reference, item_id) VALUES (?, ?, ?)",
                (order_id, reference, order["item_id"])
            )
            conn.execute(
                "UPDATE orders SET order_status = 'exchanged' WHERE order_id = ?",
                (order_id,)
            )
            return ok(action, order_id=order_id, exchange_reference=reference,
                      item_id=order["item_id"], already_processed=False)

    def initiate_refund(self, order_id: str, reason: str) -> dict:
        """Record a MOCK refund, only if an eligible replacement is unavailable."""
        action = "initiate_refund"
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            if order is None:
                return err(action, "ORDER_NOT_FOUND", "Order not found.")
            if order["order_status"] == "refunded":
                existing = conn.execute(
                    "SELECT * FROM refunds WHERE order_id = ?", (order_id,)
                ).fetchone()
                if existing:
                    return ok(action, order_id=order_id,
                              refund_reference=existing["refund_reference"],
                              amount_inr=inr(existing["amount_paise"]),
                              payment_method=order["payment_method"],
                              already_processed=True, simulated=True)
                return err(action, "DATA_INCONSISTENCY", "Refund record is missing.")
            if order["order_status"] != "delivered":
                return err(action, "INVALID_ORDER_STATUS",
                           f"Order is {order['order_status']}; refund not permitted.")
            stock = conn.execute(
                "SELECT stock FROM inventory WHERE item_id = ?", (order["item_id"],)
            ).fetchone()
            if stock is None:
                return err(action, "INVENTORY_NOT_FOUND", "Cannot validate inventory; escalate.")
            if order["exchange_eligible"] and stock["stock"] > 0:
                return err(action, "EXCHANGE_AVAILABLE",
                           "Exchange is available. Do not refund this order.")
            reference = f"RFD-{order_id}"
            conn.execute(
                "INSERT INTO refunds (order_id, refund_reference, amount_paise, reason) "
                "VALUES (?, ?, ?, ?)",
                (order_id, reference, order["amount_paise"], reason)
            )
            conn.execute(
                "UPDATE orders SET order_status = 'refunded' WHERE order_id = ?",
                (order_id,)
            )
            return ok(action, order_id=order_id, refund_reference=reference,
                      amount_inr=inr(order["amount_paise"]),
                      payment_method=order["payment_method"],
                      already_processed=False, simulated=True)

    def send_notification(self, order_id: str, customer_email: str, message: str) -> dict:
        """Write a MOCK outgoing email into a durable outbox; no network requests."""
        action = "send_notification"
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute(
                "SELECT customer_email, order_status FROM orders WHERE order_id = ?",
                (order_id,)
            ).fetchone()
            if order is None:
                return err(action, "ORDER_NOT_FOUND", "Order not found.")
            if customer_email.lower() != order["customer_email"].lower():
                return err(action, "RECIPIENT_MISMATCH",
                           "Notification email does not match the order's customer.")
            if order["order_status"] not in ("refunded", "exchanged"):
                return err(action, "UNRESOLVED_ORDER",
                           "Cannot confirm an order before an exchange/refund is recorded.")
            previous = conn.execute(
                "SELECT email FROM notifications WHERE order_id = ?", (order_id,)
            ).fetchone()
            if previous:
                return ok(action, order_id=order_id, email=previous["email"],
                          delivery_status="mock_saved", already_processed=True,
                          simulated=True)
            conn.execute(
                "INSERT INTO notifications (order_id, email, message) VALUES (?, ?, ?)",
                (order_id, customer_email, message)
            )
            return ok(action, order_id=order_id, email=customer_email,
                      delivery_status="mock_saved", already_processed=False,
                      simulated=True)
