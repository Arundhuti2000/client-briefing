"""The contract between code and the LLM, and the checks on everything it writes (SPEC.md section 5).

The LLM is the least trusted component, so code checks every section before a
person sees it:
  1. The output parses into the Draft schema.
  2. Every bullet cites at least one evidence ID, and every ID is in that section's evidence.
  3. Every amount, percentage, count and date in a bullet appears in the evidence it cites.
     Dates are matched as dates ("31 Oct", "August 15", "2026-10-31" are the same day),
     so the day and year inside a date are never checked as amounts.
  4. Nothing restricted that this user may not see appears (record IDs or text).
  5. No instruction-like text from the documents (prompt injection) is repeated as a claim.
  6. No internal record IDs in the text: they belong in the citations, not in the prose.

Each failure has a technical detail (for the audit log and the "Details" box) and a
plain reason for the reader ("a date wasn't in its source").
"""

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

# ---------------------------------------------------------------------------
# What goes in: evidence, built by app/orchestrator.py from tool facts
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    evidence_id: str                                   # e.g. SQL:revenue_metrics:C001:2026Q3, DOC:note_001
    kind: Literal["fact", "document", "flag"]
    label: str                                         # for people, e.g. "Meeting note, 15 Sep 2026"
    text: str                                          # what the LLM sees; plain sentences, numbers formatted by code
    as_of: dt.date
    source: str | None = None                          # e.g. Reuters, crm_notes, revenue_metrics (for the UI)
    suggestion: str | None = None                      # how this could be a talking point (template mode)
    caveat: str | None = None                          # why a flag says this document is contradicted
    caveat_id: str | None = None                       # that flag's evidence ID


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
    errors: list[str] = []    # technical detail, e.g. "bullet 4 has dates not in its cited evidence: ['31 Nov']"
    reasons: list[str] = []   # plain reasons for the reader, e.g. "a date wasn't in its source"


class Hidden(BaseModel):
    """Restricted records the user may not see: what rule 4 must never let through."""
    record_ids: set[str] = set()
    texts: list[str] = []

# ---------------------------------------------------------------------------
# Finding dates, years and numbers in text
# ---------------------------------------------------------------------------

MONTH = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
         r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
DAY_MONTH = re.compile(rf"\b(\d{{1,2}}) {MONTH}\b(?:,? (\d{{4}})\b)?")                 # 15 Sep 2026, 15 Sep
MONTH_DAY = re.compile(rf"\b{MONTH}\.? (\d{{1,2}})(?:st|nd|rd|th)?\b(?:,? (\d{{4}})\b)?")  # August 15, Oct 31, 2026
PERIOD = re.compile(r"\b(\d{4})Q[1-4]\b|\bQ[1-4] (\d{4})\b")                           # 2026Q3, Q3 2026
YEAR = re.compile(r"(?<![\w.,$])((?:19|20)\d{2})(?!\w|%|[.,]\d)")                     # a year on its own
# An amount, percentage or count not glued to a word: "$5.1M", "13.6%", "4,200,000", "18"
NUMBER = re.compile(r"(?<![\w.])\$?(\d+(?:,\d{3})*(?:\.\d+)?)(%|[KMB](?![A-Za-z]))?(?![\w])")
MULTIPLIERS = {"K": 1e3, "M": 1e6, "B": 1e9}

# "ignore / disregard / forget / override ... instructions / rules / guidance / prompt", with up to
# 40 characters between ("ignore your instructions", "disregard all of the above rules")
INJECTION_RE = re.compile(r"\b(ignore|disregard|forget|override)\b[\w\s,']{0,40}?\b(instructions|rules|guidelines|"
                          r"guidance|prompt)\b|"
                          r"disregard (all |any )?(previous|prior|above|earlier)|"
                          r"you are now|system prompt", re.IGNORECASE)

# Internal IDs that belong in citations, never in prose
INTERNAL_ID = re.compile(r"\b(?:note|email|brief|news|research)_\d+\b|\bOPP-[A-Z]+-[A-Z]+\b|\bA-\d{3}\b|"
                         r"\bSI-\d{3}\b|\bCT\d{3}\b|\bC\d{3}\b|\bF\d{3}\b|\b(?:SQL|DOC|FLAG):\S+|\bu\d\b")


def month_number(name: str) -> int:
    return ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(name[:3].lower()) + 1


@dataclass
class Found:
    dates: dict = field(default_factory=dict)    # (year or None, month, day) -> as written
    years: dict = field(default_factory=dict)    # year -> as written
    numbers: dict = field(default_factory=dict)  # canonical value, e.g. 'num:5100000.0' -> as written


def find_facts(text: str) -> Found:
    """Dates, years and numbers in the text. Each match is removed before the next pattern,
    so '31 Oct 2026' is one date, not the numbers 31 and 2026."""
    found = Found()

    def take(pattern, handle):
        nonlocal text
        for match in pattern.finditer(text):
            handle(match)
        text = pattern.sub(" ", text)

    take(ISO_DATE, lambda m: found.dates.setdefault((int(m[1]), int(m[2]), int(m[3])), m[0]))
    take(DAY_MONTH, lambda m: found.dates.setdefault(
        (int(m[3]) if m[3] else None, month_number(m[2]), int(m[1])), m[0]))
    take(MONTH_DAY, lambda m: found.dates.setdefault(
        (int(m[3]) if m[3] else None, month_number(m[1]), int(m[2])), m[0]))
    take(PERIOD, lambda m: found.years.setdefault(int(m[1] or m[2]), m[0]))
    take(YEAR, lambda m: found.years.setdefault(int(m[1]), m[0]))
    for m in NUMBER.finditer(text):
        value = float(m[1].replace(",", ""))
        key = f"pct:{round(value, 2)}" if m[2] == "%" else f"num:{round(value * MULTIPLIERS.get(m[2], 1), 2)}"
        found.numbers.setdefault(key, m[0])
    return found


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def find_injections(text: str) -> list[str]:
    """Sentences that try to give the assistant instructions."""
    return [s for s in sentences(text) if INJECTION_RE.search(s)]


def word_ngrams(text: str, n: int = 5) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.lower())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def unsupported_facts(text: str, cited: list[Evidence]) -> tuple[list[str], list[str]]:
    """Rule 3: the dates and numbers in `text` that are not in the cited evidence, as written.
    An evidence item's own date counts as being in it. Returns (bad_dates, bad_numbers).
    Also used by eval/run_eval.py to re-check the finished briefing."""
    allowed = Found()
    for e in cited:
        facts = find_facts(e.text)
        allowed.dates |= facts.dates | {(e.as_of.year, e.as_of.month, e.as_of.day): ""}
        allowed.years |= facts.years | {e.as_of.year: ""}
        allowed.numbers |= facts.numbers
    allowed.years |= {year: "" for year, _, _ in allowed.dates if year}
    said = find_facts(text)
    bad_dates = [written for (year, month, day), written in said.dates.items()
                 if not any(m == month and d == day and (year is None or y in (None, year))
                            for y, m, d in allowed.dates)]
    bad_years = [written for year, written in said.years.items() if year not in allowed.years]
    bad_numbers = [written for key, written in said.numbers.items() if key not in allowed.numbers]
    return bad_dates + bad_years, bad_numbers

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
        errors = list(schema_errors) or [f"section '{section.section}' is missing"]
        reason = "the answer wasn't in the expected format" if schema_errors else "a section was missing"
        return Check(passed=False, errors=errors, reasons=[reason])
    evidence = {e.evidence_id: e for e in section.evidence}
    injections = [s for e in section.evidence for s in find_injections(e.text)]
    hidden_ngrams = set().union(*(word_ngrams(t) for t in hidden.texts)) if hidden.texts else set()
    errors, reasons = [], []

    def fail(error: str, reason: str):
        errors.append(error)
        if reason not in reasons:
            reasons.append(reason)

    for i, bullet in enumerate(draft.bullets, start=1):
        where = f"bullet {i}"
        # Rule 2: citations exist and come from this section's evidence
        if not bullet.citations:
            fail(f"{where} has no citation", "a statement had no source")
        unknown = [c for c in bullet.citations if c not in evidence]
        if unknown:
            fail(f"{where} cites IDs that are not in this section's evidence: {unknown}",
                 "a statement cited a source it wasn't given")
        # Rule 3: amounts, counts and dates must be in the cited evidence
        bad_dates, bad_numbers = unsupported_facts(bullet.text, [evidence[c] for c in bullet.citations
                                                                 if c in evidence])
        if bad_dates:
            fail(f"{where} has dates not in its cited evidence: {bad_dates}",
                 "a date wasn't in its source")
        if bad_numbers:
            fail(f"{where} has numbers not in its cited evidence: {bad_numbers}",
                 "a number wasn't in its source")
        # Rule 4: nothing restricted the user may not see
        leaked_ids = [r for r in hidden.record_ids if r in bullet.text or r in bullet.citations]
        if leaked_ids or word_ngrams(bullet.text) & hidden_ngrams:
            fail(f"{where} contains restricted content", "it contained restricted content")
        # Rule 5: injected instructions are data, never claims
        if any(word_ngrams(bullet.text) & word_ngrams(s) for s in injections):
            fail(f"{where} repeats instruction-like text from a document",
                 "it repeated an instruction found in a document")
        # Rule 6: IDs go in citations, never in the prose
        ids_in_text = INTERNAL_ID.findall(bullet.text)
        if ids_in_text:
            fail(f"{where} shows internal IDs in its text: {ids_in_text}", "it showed internal record codes")
    return Check(passed=not errors, errors=errors, reasons=reasons)
