"""LLM client chosen by LLM_PROVIDER: mock (default), gemini, or ollama (SPEC.md section 5).

One call per briefing, responses cached under .cache/llm/, rate-limited with a
fallback to GEMINI_FALLBACK_MODEL and then mock. Every provider returns the same
JSON bullets-with-citations schema. Built in Phase 4.
"""
