"""Persistent SQLite demo database. Monetary amounts are stored as integer paise."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def connect(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database(db_path: str | Path, *, reset: bool = False) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if reset and path.exists():
        path.unlink()

    with connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                customer_name TEXT NOT NULL,
                customer_email TEXT NOT NULL,
                item_id TEXT NOT NULL,
                item_name TEXT NOT NULL,
                amount_paise INTEGER NOT NULL CHECK(amount_paise >= 0),
                exchange_eligible INTEGER NOT NULL CHECK(exchange_eligible IN (0, 1)),
                payment_method TEXT NOT NULL,
                order_status TEXT NOT NULL DEFAULT 'delivered'
            );
            CREATE TABLE IF NOT EXISTS inventory (
                item_id TEXT PRIMARY KEY,
                stock INTEGER NOT NULL CHECK(stock >= 0)
            );
            CREATE TABLE IF NOT EXISTS refunds (
                order_id TEXT PRIMARY KEY REFERENCES orders(order_id),
                refund_reference TEXT NOT NULL UNIQUE,
                amount_paise INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS exchanges (
                order_id TEXT PRIMARY KEY REFERENCES orders(order_id),
                exchange_reference TEXT NOT NULL UNIQUE,
                item_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS notifications (
                order_id TEXT PRIMARY KEY REFERENCES orders(order_id),
                email TEXT NOT NULL,
                message TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.executemany(
            "INSERT OR IGNORE INTO inventory (item_id, stock) VALUES (?, ?)",
            [
                ("SKU-HEADPHONES", 0),
                ("SKU-SPEAKER", 4),
                ("SKU-SLEEVE", 2),
            ],
        )
        conn.executemany(
            """INSERT OR IGNORE INTO orders
               (order_id, customer_name, customer_email, item_id, item_name,
                amount_paise, exchange_eligible, payment_method, order_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'delivered')""",
            [
                ("ORD-1001", "Maya Sharma", "maya@example.com", "SKU-HEADPHONES",
                 "Wireless Headphones", 349900, 1, "Card ending 1234"),
                ("ORD-1002", "Aarav Mehta", "aarav@example.com", "SKU-SPEAKER",
                 "Bluetooth Speaker", 249900, 1, "UPI ending 5678"),
                ("ORD-1003", "Neha Kapoor", "neha@example.com", "SKU-SLEEVE",
                 "Laptop Sleeve", 89900, 0, "Card ending 9012"),
            ],
        )


def get_summary(db_path: str | Path) -> dict:
    """Return observable results to demonstrate persisted side effects."""
    with connect(db_path) as conn:
        return {
            "orders": [dict(row) for row in conn.execute(
                "SELECT order_id, order_status FROM orders ORDER BY order_id")],
            "inventory": [dict(row) for row in conn.execute(
                "SELECT item_id, stock FROM inventory ORDER BY item_id")],
            "refunds": [dict(row) for row in conn.execute(
                "SELECT order_id, refund_reference, amount_paise FROM refunds ORDER BY order_id")],
            "exchanges": [dict(row) for row in conn.execute(
                "SELECT order_id, exchange_reference FROM exchanges ORDER BY order_id")],
            "notifications": [dict(row) for row in conn.execute(
                "SELECT order_id, email, message FROM notifications ORDER BY order_id")],
        }
