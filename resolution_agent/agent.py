"""Agentic tool loop: model -> validated dispatcher -> state -> model -> final."""
from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .contracts import Dispatcher, TOOL_SCHEMAS


SYSTEM_PROMPT = """You are a customer order resolution agent using authorized tools.
You must independently investigate and resolve a reported damaged/defective item.
1. First look up the requested order using lookup_order. If not found, politely ask
   the customer to verify the order ID; never invent an order.
2. Read inventory using inspect_inventory for the item's SKU.
3. If the order is delivered, exchange-eligible, AND stock_count > 0, call
   confirm_exchange. Otherwise call initiate_refund, with a clear reason.
4. ONLY after a successful exchange/refund, call send_notification with the exact
   order email and a helpful message including the reference number.
5. Finally summarize the observed tool results, including a reference, customer
   outcome, and notification status. Never claim success after a failed tool.
If an unrecoverable error occurs, explain it and request human review.
IMPORTANT: All financial, logistics, and email operations are local SIMULATIONS.
They do NOT send real money, create real shipments, or deliver real email.
Make this limitation clear in your final response. Never promise a real transfer.
Don't invent tool outcomes or call unauthorized tools. The tools enforce safety.
"""


class Provider(Protocol):
    def next_message(self, messages: list[dict], tools: list[dict]) -> dict: ...


GEMINI_OPENAI_COMPAT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class OpenAIProvider:
    """LLM function calling through the OpenAI SDK and chat completions protocol."""

    def __init__(self, model: str = "gpt-4o-mini", *, api_key: str | None = None,
                 base_url: str | None = None, allow_parallel_control: bool = True,
                 request_timeout: float | None = None, max_retries: int | None = None):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install OpenAI SDK first: python3 -m pip install -r requirements.txt") from exc
        client_options = {}
        if api_key is not None:
            client_options["api_key"] = api_key
        if base_url is not None:
            client_options["base_url"] = base_url
        if request_timeout is not None:
            client_options["timeout"] = request_timeout
        if max_retries is not None:
            client_options["max_retries"] = max_retries
        self.client = OpenAI(**client_options)
        self.model = model
        self.allow_parallel_control = allow_parallel_control

    def next_message(self, messages: list[dict], tools: list[dict]) -> dict:
        options = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0,
        }
        # Gemini's OpenAI-compatibility endpoint does not reliably support
        # parallel_tool_calls=False. Omit it for Gemini, preserving all tools.
        if self.allow_parallel_control:
            options["parallel_tool_calls"] = False
        response = self.client.chat.completions.create(**options)
        msg = response.choices[0].message
        result = {"role": "assistant", "content": msg.content}
        # Preserve Gemini's opaque reasoning continuation data, if supplied.
        # In particular, Gemini may reject a subsequent function result when
        # its corresponding tool call's thought_signature is dropped.
        msg_extra = (getattr(msg, "model_extra", None) or {}).get("extra_content")
        if msg_extra:
            result["extra_content"] = msg_extra
        if msg.tool_calls:
            result["tool_calls"] = []
            for call in msg.tool_calls:
                tool_call = {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name,
                                 "arguments": call.function.arguments},
                }
                call_extra = (getattr(call, "model_extra", None) or {}).get("extra_content")
                if call_extra:
                    tool_call["extra_content"] = call_extra
                result["tool_calls"].append(tool_call)
        return result


class GeminiProvider(OpenAIProvider):
    """Real Gemini function calling using Google's OpenAI-compatible endpoint.

    The existing validated tool schemas and state loop remain unchanged.
    Requires a Google AI Studio key in GEMINI_API_KEY. No OpenAI credits used.
    """

    def __init__(self, model: str = "gemini-3.8-flash"):
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("For --mode gemini, set GEMINI_API_KEY in your environment.")
        super().__init__(
            model=model,
            api_key=key,
            base_url=GEMINI_OPENAI_COMPAT_BASE_URL,
            allow_parallel_control=False,
            request_timeout=45.0,
            max_retries=0,
        )

    def next_message(self, messages: list[dict], tools: list[dict]) -> dict:
        # Google's OpenAI-compatible tool schema conversion does not consistently
        # support the additionalProperties keyword. Copy first so the canonical
        # tool schemas, used by local validation and OpenAI, stay unchanged.
        compatible_tools = copy.deepcopy(tools)
        for tool in compatible_tools:
            tool["function"]["parameters"].pop("additionalProperties", None)
        return super().next_message(messages, compatible_tools)


class OfflinePlanner:
    """Deterministic demo planner using the same function-call interface.

    This is NOT an LLM. It permits live offline demonstration and repeatable tests.
    Run --mode openai to exercise genuine language-model tool selection.
    """

    @staticmethod
    def _call(name: str, **kwargs: str) -> dict:
        return {
            "role": "assistant", "content": None,
            "tool_calls": [{
                "id": f"offline_{name}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(kwargs)},
            }],
        }

    @staticmethod
    def _final(message: str) -> dict:
        return {"role": "assistant", "content": message}

    def next_message(self, messages: list[dict], tools: list[dict]) -> dict:
        prompt = next((m.get("content", "") for m in messages if m["role"] == "user"), "")
        match = re.search(r"\bORD-[A-Za-z0-9-]+\b", prompt, re.IGNORECASE)
        if not match:
            return self._final("Please provide your order ID (for example, ORD-1001) so I can investigate.")
        order_id = match.group(0).upper()

        results: dict[str, list[dict]] = {}
        for message in messages:
            if message["role"] == "tool":
                try:
                    payload = json.loads(message["content"])
                except (json.JSONDecodeError, TypeError):
                    return self._final("A tool returned an invalid result. Please contact support.")
                results.setdefault(message["name"], []).append(payload)

        if "lookup_order" not in results:
            return self._call("lookup_order", order_id=order_id)
        lookup = results["lookup_order"][-1]
        if not lookup["success"]:
            return self._final(f"I couldn't find {order_id}. Please verify the order ID and try again.")
        order = lookup["data"]
        if order["order_status"] in ("refunded", "exchanged"):
            status = order["order_status"]
            return self._final(f"Order {order_id} was already {status}. No additional transaction was created.")
        if order["order_status"] != "delivered":
            return self._final(f"Order {order_id} has status {order['order_status']}. Please contact support for review.")

        if "inspect_inventory" not in results:
            return self._call("inspect_inventory", item_id=order["item_id"])
        inventory = results["inspect_inventory"][-1]
        if not inventory["success"]:
            return self._final("I couldn't verify replacement stock. Please contact support for a manual review.")

        exchange_possible = order["exchange_eligible"] and inventory["data"]["stock_count"] > 0
        resolution_name = "confirm_exchange" if exchange_possible else "initiate_refund"
        if resolution_name not in results and not any(
            name in results for name in ("confirm_exchange", "initiate_refund")
        ):
            if exchange_possible:
                return self._call("confirm_exchange", order_id=order_id)
            reason = ("Damaged item; replacement unavailable (zero stock)."
                      if order["exchange_eligible"] else
                      "Damaged item; order not eligible for exchange.")
            return self._call("initiate_refund", order_id=order_id, reason=reason)

        prior_name = "confirm_exchange" if "confirm_exchange" in results else "initiate_refund"
        resolution = results[prior_name][-1]
        if not resolution["success"]:
            # Stock may have run out between inspection and exchange reservation.
            if (prior_name == "confirm_exchange"
                    and resolution["error"]["code"] == "OUT_OF_STOCK"
                    and "initiate_refund" not in results):
                return self._call("initiate_refund", order_id=order_id,
                                  reason="Damaged item; replacement sold out during reservation.")
            return self._final("Unable to complete the resolution safely. Please contact support.")
        data = resolution["data"]

        if "send_notification" not in results:
            if prior_name == "confirm_exchange":
                detail = f"a replacement exchange (reference {data['exchange_reference']})"
            else:
                detail = (f"a refund of INR {data['amount_inr']} to your original "
                          f"payment method (reference {data['refund_reference']})")
            message = (f"Hello {order['customer_name']}, we have recorded {detail} for "
                       f"order {order_id}. This is a demonstration; no real refund, "
                       "shipment or email delivery has occurred.")
            return self._call("send_notification", order_id=order_id,
                              customer_email=order["customer_email"], message=message)
        notification = results["send_notification"][-1]
        if not notification["success"]:
            return self._final("Your order resolution was recorded, but the notification failed. Please contact support.")

        if prior_name == "confirm_exchange":
            outcome = (f"a replacement exchange has been recorded (reference "
                       f"{data['exchange_reference']})")
        else:
            outcome = (f"a refund of ₹{data['amount_inr']} to {data['payment_method']} "
                       f"has been recorded (reference {data['refund_reference']})")
        return self._final(
            f"I'm sorry about your {order['item_name']}. For {order_id}, {outcome}. "
            f"A confirmation has been saved to the mock email outbox for "
            f"{order['customer_email']}. This is a simulation: no actual money, "
            "shipment or email was sent."
        )


@dataclass
class AgentResult:
    answer: str
    status: str
    iterations: int
    trace: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    provider_error: str | None = None


def safe_provider_error(exc: Exception) -> str | None:
    """Expose a short API rejection reason for debugging, never credentials."""
    body = getattr(exc, "body", None)
    if isinstance(body, list) and body and isinstance(body[0], dict):
        body = body[0].get("error", body[0])
    if not isinstance(body, dict):
        return None
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return None
    code = body.get("code")
    status = getattr(exc, "status_code", None)
    # Provider errors may sometimes include parts of a supplied request.
    # Redact token-like material before printing to a terminal or screenshot.
    message = re.sub(r"(?i)\b(?:sk-(?:proj-)?|AIza)[A-Za-z0-9_\-]{8,}", "[REDACTED]", message)
    message = re.sub(r"(?i)(key=|api_key=)[^\s,&]+", r"\1[REDACTED]", message)
    prefix = f"HTTP {status} " if status is not None else ""
    if code:
        prefix += f"{code}: "
    return (prefix + message.strip())[:500]


def run_agent(request: str, provider: Provider, dispatcher: Dispatcher,
              *, max_iterations: int = 5,
              progress: Callable[[str], None] | None = None) -> AgentResult:
    """Explicit bounded ReAct-style loop with serialized tool feedback."""
    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": request},
    ]
    trace: list[dict] = []
    for iteration in range(1, max_iterations + 1):
        if progress:
            progress(f"[Agent] Cycle {iteration}/{max_iterations}: contacting model...")
        try:
            assistant = provider.next_message(messages, TOOL_SCHEMAS)
        except Exception as exc:
            # No tracebacks or API secrets in customer output.
            return AgentResult(
                answer=f"Agent model unavailable ({type(exc).__name__}). Please retry or request human support.",
                status="model_error", iterations=iteration, trace=trace, history=messages,
                provider_error=safe_provider_error(exc),
            )
        if not isinstance(assistant, dict) or assistant.get("role") != "assistant":
            return AgentResult("Invalid model response. Please request human support.",
                               "model_error", iteration, trace, messages)
        messages.append(assistant)
        calls = assistant.get("tool_calls") or []
        if not calls:
            final = assistant.get("content") or "No resolution could be completed."
            return AgentResult(str(final), "completed", iteration, trace, messages)

        for call in calls:
            function = call.get("function", {})
            name = function.get("name", "")
            raw_arguments = function.get("arguments", "{}")
            result = dispatcher.dispatch(name, raw_arguments)
            trace.append({"iteration": iteration, "tool": name, "result": result})
            if progress:
                progress(f"[Agent] Tool {name}: {'SUCCESS' if result['success'] else 'ERROR'}")
            messages.append({
                "role": "tool", "tool_call_id": call.get("id", "missing_call_id"),
                "name": name, "content": json.dumps(result),
            })

    return AgentResult(
        answer=("The safety limit was reached before a final answer was produced. "
                "This session has been flagged for human review; please contact support."),
        status="escalated", iterations=max_iterations, trace=trace, history=messages,
    )
