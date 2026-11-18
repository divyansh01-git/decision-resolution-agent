"""Command-line and interactive entry point for the Resolution Agent."""
from __future__ import annotations

import argparse
import json
import os

from resolution_agent.agent import GeminiProvider, OfflinePlanner, OpenAIProvider, run_agent
from resolution_agent.contracts import Dispatcher
from resolution_agent.db import get_summary, initialize_database
from resolution_agent.tools import ResolutionTools


def print_result(result, *, mode: str, db: str, show_state: bool) -> None:
    """Display the auditable tool trace and customer-facing outcome."""
    print("\nDECISION-MAKING RESOLUTION AGENT")
    print(f"Mode: {mode} | Status: {result.status}")
    print("\nTOOL EXECUTION TRACE")
    if not result.trace:
        print("  No tools executed.")
    for item in result.trace:
        outcome = item["result"]
        state = "SUCCESS" if outcome["success"] else "ERROR"
        print(f"  Cycle {item['iteration']}: {item['tool']} -> {state}")
        print("    " + json.dumps(outcome, ensure_ascii=False))
    print("\nCUSTOMER RESPONSE")
    print(result.answer)
    if result.provider_error:
        print("\nAPI ERROR DETAILS (no credentials)")
        print(result.provider_error)
    if show_state:
        print("\nPERSISTED SQLITE STATE")
        print(json.dumps(get_summary(db), indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Xebia automated order resolution agent")
    parser.add_argument("--order", default="ORD-1001", help="Order ID (e.g. ORD-1001)")
    parser.add_argument("--issue", default="The product arrived damaged.",
                        help="Customer-reported issue")
    parser.add_argument("--interactive", action="store_true",
                        help="Type customer requests directly into a terminal prompt")
    parser.add_argument("--mode", choices=("offline", "gemini", "openai"), default="offline",
                        help="offline=deterministic demo; gemini/openai=real LLM tool calling")
    parser.add_argument("--model", default=None,
                        help="Model override (default: gemini-3.5-flash-lite for Gemini, gpt-4o-mini for OpenAI)")
    parser.add_argument("--db", default="runtime/orders.db", help="SQLite database path")
    parser.add_argument("--reset-db", action="store_true", help="Recreate seeded demo database")
    parser.add_argument("--show-state", action="store_true", help="Print DB state after execution")
    parser.add_argument("--max-iterations", type=int, default=5)
    args = parser.parse_args()
    if args.max_iterations < 1:
        parser.error("--max-iterations must be at least 1")

    initialize_database(args.db, reset=args.reset_db)
    if args.mode == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            parser.error("For --mode openai, set OPENAI_API_KEY in your environment.")
        try:
            provider = OpenAIProvider(model=args.model or "gpt-4o-mini")
        except RuntimeError as exc:
            parser.error(str(exc))
    elif args.mode == "gemini":
        if not os.environ.get("GEMINI_API_KEY"):
            parser.error("For --mode gemini, set GEMINI_API_KEY in your environment.")
        try:
            provider = GeminiProvider(model=args.model or "gemini-3.5-flash-lite")
        except RuntimeError as exc:
            parser.error(str(exc))
    else:
        provider = OfflinePlanner()
    dispatcher = Dispatcher(ResolutionTools(args.db))

    if args.interactive:
        print("\nDECISION-MAKING RESOLUTION AGENT | INTERACTIVE DEMO")
        print("Enter a customer complaint with an order ID, such as:")
        print('  My order ORD-1001 arrived damaged. Can you resolve it?')
        print("Sample IDs: ORD-1001 (refund), ORD-1002 (exchange), ORD-1003 (refund)")
        print("Type 'exit' or 'quit' to finish. All actions are local simulations.\n")
        while True:
            try:
                request = input("Customer> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nDemo ended.")
                break
            if request.lower() in ("exit", "quit"):
                print("Demo ended.")
                break
            if not request:
                continue
            result = run_agent(
                request, provider, dispatcher, max_iterations=args.max_iterations,
                progress=print if args.mode in ("gemini", "openai") else None,
            )
            print_result(result, mode=args.mode, db=args.db, show_state=args.show_state)
            print("\nEnter another complaint, or type 'exit'.\n")
    else:
        request = f"My order {args.order} has a problem: {args.issue} Please resolve it."
        result = run_agent(
            request, provider, dispatcher, max_iterations=args.max_iterations,
            progress=print if args.mode in ("gemini", "openai") else None,
        )
        print_result(result, mode=args.mode, db=args.db, show_state=args.show_state)


if __name__ == "__main__":
    main()
