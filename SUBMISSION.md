# Xebia Submission Checklist — Gemini Edition

1. Extract this ZIP and open the new project folder in VS Code. Use the **updated Gemini version**, not the earlier OpenAI-only folder.
2. From the project root, run `python3 -m pip install -r requirements.txt` inside your activated `.venv`.
3. Run `python3 -m unittest discover -s tests -v` and check all **24** local tests pass.
4. Create a Gemini API key at https://aistudio.google.com/api-keys (eligible free-tier access is subject to quotas). Never paste keys into GitHub or chat.
5. In zsh: `read -rs "GEMINI_API_KEY?Paste your Gemini API key: "` and press Enter after pasting; then run `export GEMINI_API_KEY`.
6. Run `python3 main.py --interactive --mode gemini --reset-db` (default model: `gemini-3.8-flash`) and test:
   - `My order ORD-1001 arrived damaged.` → mock refund
   - `My order ORD-1002 arrived broken.` → mock exchange
   - `My order ORD-9999 has a problem.` → helpful order-ID verification
7. Confirm the real Gemini run shows `Mode: gemini | Status: completed` and a sensible `TOOL EXECUTION TRACE`. If it shows `model_error`, check your Gemini key, model access and Google AI Studio quota.
8. Run `git status --short` and check no secrets or `runtime/` files are staged.
9. Create an empty public GitHub repo, push this folder and submit its HTTPS URL.

**Safety:** Real LLM selection; simulated refunds, shipments and emails. `--mode offline` is deterministic and *not* an AI model. Gemini uses Google's OpenAI-compatible endpoint, so the installed `openai` SDK is used even though no OpenAI credits are needed.

## Gemini API compatibility update

The Gemini provider strips `additionalProperties` from outgoing function declarations, while preserving the original stricter schemas for server-side validation. If Gemini rejects a call with HTTP 400, the terminal shows a short non-secret API error message for diagnosis. The Gemini tool loop is tested using mocked responses; verify a real provider call locally before claiming it succeeded.

## Model update (November 2026)

The prior `gemini-2.5-flash` default returned HTTP 404 for new API projects. The default now uses `gemini-3.8-flash`, as recommended by Google. You can override the selected model with `--model gemini-3.5-flash-lite` if your project supports it. Live tool calling still requires an actual Gemini key and sufficient quota; mocks do not demonstrate a successful external connection.
