"""One minimal Gemini API request to distinguish connectivity from agent-loop delays."""
import os
import sys

from openai import OpenAI


def main():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("GEMINI_API_KEY is missing. Set it in this terminal.")
        return 2
    client = OpenAI(
        api_key=key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        timeout=25.0,
        max_retries=0,
    )
    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    print(f"Checking {model} with one short request (timeout: 25s)...", flush=True)
    try:
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "Reply with the single word OK."}],
            max_tokens=64,
        )
    except Exception as exc:
        print(f"Request failed: {type(exc).__name__}")
        print(f"HTTP status: {getattr(exc, 'status_code', 'not available')}")
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            print("API error code:", body.get("code", "unknown"))
            # Avoid printing provider responses in case they echo request metadata.
        else:
            print("No structured error body available.")
        return 1
    print("Gemini API replied successfully:", (response.choices[0].message.content or "").strip()[:80])
    return 0


if __name__ == "__main__":
    sys.exit(main())
