"""Ping every LLM provider and print which ones work.

Sends one tiny request to each configured provider (never the cache), so it spends one
request of each provider's quota. For Gemini it pings GEMINI_MODEL only; for OpenRouter, one
request with the whole OPENROUTER_MODELS list, and it shows which model answered.
API keys are never printed.

Run:  make llm-check   (or: python -m app.llm_check)
"""

import os
import sys
import time

from app import llm

PROVIDERS = ["gemini", "openrouter", "ollama", "mock"]
PING = 'Health check. Reply with JSON only: {"sections": []}'


def check(provider: str) -> tuple[str, str, str]:
    """(status, model, detail). Status is OK, FAIL or SKIP (not configured)."""
    if provider == "mock":
        return "OK", "template", "no key or network needed"
    key = llm.API_KEYS.get(provider)
    if key and not os.getenv(key):
        return "SKIP", "", f"no {key} in .env"
    models = llm.models_for(provider)
    if not models:
        return "SKIP", "", "no models configured"
    request = models if provider == "openrouter" else models[:1]
    started = time.perf_counter()
    try:
        reply = llm.PROVIDERS[provider](request, PING)
    except Exception as e:
        return "FAIL", ", ".join(request), llm.describe_error(e)
    shape = "valid JSON" if llm.parse_json(reply.text) is not None else "answered, but not JSON"
    return "OK", reply.model, f"{shape}, {time.perf_counter() - started:.1f} s"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    chain = llm.llm_chain()
    print(f"LLM_CHAIN: {' -> '.join(chain)}\n")
    results = {provider: check(provider) for provider in PROVIDERS}
    for provider, (status, model, detail) in results.items():
        where = "in chain" if provider in chain else "not in chain"
        print(f"  {provider:<11}{status:<6}{model:<42}{detail}  [{where}]")
    working = [p for p in chain if results[p][0] == "OK"]
    print(f"\nBriefings will be written by: {working[0] if working else 'nobody (the evidence is shown as-is)'}")


if __name__ == "__main__":
    main()
