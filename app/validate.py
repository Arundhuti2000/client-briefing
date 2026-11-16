"""The contract between code and the LLM, and the checks on everything it writes (SPEC.md section 5).

The LLM is the least trusted component, so code checks every section before a
person sees it:
  1. The output parses into the Draft schema.
  2. Every bullet cites at least one evidence ID, and every ID is in that section's evidence.
  3. Every number in a bullet appears in the evidence that bullet cites.
  4. Nothing restricted that this user may not see appears (record IDs or text).
  5. No instruction-like text from the documents (prompt injection) is repeated as a claim.

Numbers are compared by value, so "$5.1M" and "$5,100,000" match, but "$6M" never
matches evidence that says $5.1M.
"""

import datetime as dt
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

# ---------------------------------------------------------------------------
# What goes in: evidence, built by app/orchestrator.py from tool facts
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    evidence_id: str                                   # e.g. SQL:revenue_metrics:C001:2026Q3, DOC:note_001
    kind: Literal["fact", "document", "flag"]
    label: str
    text: str                                          # what the LLM sees; numbers already formatted by code
    as_of: dt.date
    source: str | None = None                          # e.g. Reuters, crm_notes, revenue_metrics (for the UI)


class SectionEvidence(BaseModel):
    section: str
    question: str
    evidence: list[Evidence]

# ---------------------------------------------------------------------------
# What must come out: the draft, in the same JSON shape from every provider
# ---------------------------------------------------------------------------


class Bullet(BaseModel):
    text: str = Field(min_length=1)
    citations: list[str]


class SectionDraft(BaseModel):
    section: str
    bullets: list[Bullet]


class Draft(BaseModel):
    sections: list[SectionDraft]


class Check(BaseModel):
    passed: bool
    errors: list[str] = []


class Hidden(BaseModel):
    """Restricted records the user may not see: what rule 4 must never let through."""
    record_ids: set[str] = set()
    texts: list[str] = []

# ---------------------------------------------------------------------------
# Helpers: numbers, injections, overlapping text
# ---------------------------------------------------------------------------

DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# A number not glued to a word: "$5.1M", "13.6%", "4,200,000", "15". Skips "2026Q3", "C001", "note_001".
NUMBER_RE = re.compile(r"(?<![\w.])\$?(\d+(?:,\d{3})*(?:\.\d+)?)(%|[KMB](?![A-Za-z]))?(?![\w])")
MULTIPLIERS = {"K": 1e3, "M": 1e6, "B": 1e9}

INJECTION_RE = re.compile(r"ignore (all |any )?(previous|prior|above|earlier) instructions|"
                          r"disregard (all |any )?(previous|prior|above|earlier)|"
                          r"forget (all |any )?(previous|prior|earlier) instructions|"
                          r"you are now|system prompt", re.IGNORECASE)


def numbers_in(text: str) -> set[str]:
    """Canonical values of every date and number in the text: '$5.1M' -> 'num:5100000.0'."""
    found = {f"date:{d}" for d in DATE_RE.findall(text)}
    for digits, suffix in NUMBER_RE.findall(DATE_RE.sub(" ", text)):
        value = float(digits.replace(",", ""))
        if suffix == "%":
            found.add(f"pct:{round(value, 2)}")
        else:
            found.add(f"num:{round(value * MULTIPLIERS.get(suffix, 1), 2)}")
    return found


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def find_injections(text: str) -> list[str]:
    """Sentences that try to give the assistant instructions."""
    return [s for s in sentences(text) if INJECTION_RE.search(s)]


def word_ngrams(text: str, n: int = 5) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.lower())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}

# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def parse_draft(raw: dict | None) -> tuple[dict[str, SectionDraft], list[str]]:
    """Rule 1: the output must parse into the schema. Returns {section: draft} and errors."""
    if raw is None:
        return {}, ["the answer was not valid JSON"]
    try:
        draft = Draft.model_validate(raw)
    except ValidationError as e:
        return {}, [f"the answer does not match the schema: {e.errors()[0]['msg']}"]
    return {s.section: s for s in draft.sections}, []


def check_section(draft: SectionDraft | None, section: SectionEvidence, hidden: Hidden,
                  schema_errors: list[str] = ()) -> Check:
    if draft is None:
        return Check(passed=False, errors=list(schema_errors) or [f"section '{section.section}' is missing"])
    evidence = {e.evidence_id: e for e in section.evidence}
    injections = [s for e in section.evidence for s in find_injections(e.text)]
    hidden_ngrams = set().union(*(word_ngrams(t) for t in hidden.texts)) if hidden.texts else set()
    errors = []
    for i, bullet in enumerate(draft.bullets, start=1):
        where = f"bullet {i}"
        # Rule 2: citations exist and come from this section's evidence
        if not bullet.citations:
            errors.append(f"{where} has no citation")
        unknown = [c for c in bullet.citations if c not in evidence]
        if unknown:
            errors.append(f"{where} cites IDs that are not in this section's evidence: {unknown}")
        # Rule 3: every number is in the cited evidence
        cited = [evidence[c] for c in bullet.citations if c in evidence]
        allowed = set().union(*(numbers_in(e.text) | {f"date:{e.as_of}"} for e in cited)) if cited else set()
        invented = sorted(numbers_in(bullet.text) - allowed)
        if invented:
            errors.append(f"{where} has numbers or dates not in its cited evidence: {invented}")
        # Rule 4: nothing restricted the user may not see
        leaked_ids = [r for r in hidden.record_ids if r in bullet.text or r in bullet.citations]
        if leaked_ids or word_ngrams(bullet.text) & hidden_ngrams:
            errors.append(f"{where} contains restricted content")
        # Rule 5: injected instructions are data, never claims
        if any(word_ngrams(bullet.text) & word_ngrams(s) for s in injections):
            errors.append(f"{where} repeats instruction-like text from a document")
    return Check(passed=not errors, errors=errors)
