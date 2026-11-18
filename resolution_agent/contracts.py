"""Declarative schemas and registry-based, validated tool dispatch."""
from __future__ import annotations

import json
from typing import Any

from .tools import ResolutionTools, err


def schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def field(description: str) -> dict:
    return {"type": "string", "description": description}


TOOL_SCHEMAS = [
    schema(
        "lookup_order", "Look up a customer's order and exchange policy eligibility. Call first.",
        {"order_id": field("Customer's exact order ID, e.g. ORD-1001")},
        ["order_id"],
    ),
    schema(
        "inspect_inventory", "Read current warehouse stock for the ordered item. Call after lookup.",
        {"item_id": field("Item SKU obtained from lookup_order")},
        ["item_id"],
    ),
    schema(
        "confirm_exchange", "Reserve a replacement and record an exchange only if eligible and in stock.",
        {"order_id": field("Verified order ID")},
        ["order_id"],
    ),
    schema(
        "initiate_refund", "Create a MOCK refund when the order cannot be exchanged (zero stock or ineligible). Do not call if an eligible replacement is available.",
        {
            "order_id": field("Verified order ID"),
            "reason": field("Reason for refund, e.g. damaged item and replacement out of stock"),
        },
        ["order_id", "reason"],
    ),
    schema(
        "send_notification", "Record a MOCK confirmation email after an exchange or refund succeeded.",
        {
            "order_id": field("Resolved order ID"),
            "customer_email": field("Verified email from lookup_order"),
            "message": field("Clear, polite confirmation specifying exchange/refund reference and amount if refunded"),
        },
        ["order_id", "customer_email", "message"],
    ),
]


class Dispatcher:
    def __init__(self, tools: ResolutionTools):
        # Explicit whitelist: never getattr() on arbitrary model-generated names.
        self.registry = {
            "lookup_order": tools.lookup_order,
            "inspect_inventory": tools.inspect_inventory,
            "confirm_exchange": tools.confirm_exchange,
            "initiate_refund": tools.initiate_refund,
            "send_notification": tools.send_notification,
        }
        self.parameters = {
            item["function"]["name"]: item["function"]["parameters"]
            for item in TOOL_SCHEMAS
        }

    def dispatch(self, name: str, raw_arguments: str | dict) -> dict[str, Any]:
        if name not in self.registry:
            return err("dispatch", "UNKNOWN_TOOL", f"Tool {name!r} is not authorized.")
        try:
            args = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        except (json.JSONDecodeError, ValueError, TypeError):
            return err(name, "MALFORMED_JSON", "Tool arguments must be valid JSON.")
        if not isinstance(args, dict):
            return err(name, "INVALID_ARGUMENTS", "Tool arguments must be a JSON object.")

        params = self.parameters[name]
        allowed = params["properties"]
        missing = set(params["required"]) - args.keys()
        unexpected = args.keys() - allowed.keys()
        if missing:
            return err(name, "MISSING_ARGUMENTS", f"Missing required arguments: {sorted(missing)}")
        if unexpected:
            return err(name, "UNEXPECTED_ARGUMENTS", f"Unexpected arguments: {sorted(unexpected)}")
        for key, value in args.items():
            if not isinstance(value, str) or not value.strip() or len(value) > 2000:
                return err(name, "INVALID_ARGUMENTS",
                           f"Argument {key!r} must be a non-empty string of at most 2000 characters.")
        try:
            return self.registry[name](**args)
        except Exception:
            # Don't reveal traceback/secrets to model or customer. Log externally in production.
            return err(name, "INTERNAL_ERROR", "Tool failed safely. Escalate for human review.")
