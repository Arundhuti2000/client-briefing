"""Builds one client briefing with a fixed plan (SPEC.md section 5).

  1. Call the tools: read-only, filtered by the user's entitlements, audited.
  2. Build an evidence bundle per section. Every number and date is formatted here,
     in code, as plain sentences a banker can scan (app/wording.py).
  3. Code writes the purely numeric and rule-based parts: the metrics section, the
     "uncertain, conflicting, or unavailable" section, and the "what changed" strip.
     ONE LLM call writes the other sections (app/llm.py).
  4. Validate every section (app/validate.py). Failed sections are retried once with
     the errors; if a section fails again, it shows its evidence as plain bullets.

Run:  make briefing CLIENT=NWC USER_ID=u2   (or: python -m app.orchestrator --client NWC --user u2)
"""

import argparse
import contextlib
import datetime as dt
import sys
import time
from collections import Counter
from contextlib import closing
from typing import Literal

from pydantic import BaseModel

from app import audit, db, llm, tools, validate
from app.tools import Fact, UserContext
from app.validate import Bullet, Check, Evidence, Hidden, SectionDraft, SectionEvidence
from app.wording import (AS_OF_DATE, DOC_NAMES, article, capitalize, change_words, clean_note, day_month,
                         days_before, first_lower, format_usd, full_names, join_words, long_date, month_of,
                         period_text, plain_words, signed_change, value_text)

# The fixed plan: seven questions, then talking points. (id, title, question)
PLAN = [
    ("client_overview", "Who the client is",
     "Who is the client, who covers them, and who are the key contacts?"),
    ("metrics", "Material metrics",
     "What are the material metrics and performance, and how have they changed since the last interaction?"),
    ("client_said", "What the client asked, said, or committed",
     "What did the client ask for, say, or commit to in prior conversations?"),
    ("opportunities", "Opportunities to discuss",
     "Which opportunities should we discuss, and why now?"),
    ("open_items", "Open actions and service issues",
     "What open actions, overdue items, and service issues need follow-up?"),
    ("news", "Recent news",
     "What recent approved news about the client matters for this meeting?"),
    ("uncertain", "Uncertain, conflicting, or unavailable",
     "What is uncertain, conflicting, or unavailable in the data?"),
    ("talking_points", "Talking points",
     "What are three to five suggested talking points for the meeting?"),
]
QUESTIONS = {name: question for name, _, question in PLAN}
CODE_SECTIONS = {"metrics", "uncertain"}  # never sent to the LLM

ASKS_QUERY = "client asked requested wants would like committed next steps"
NEWS_WINDOW_DAYS = 90
STAGE_PROBABILITY = {"Discovery": 0.2, "Proposal": 0.5, "Negotiation": 0.8}  # live stages only
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
# Flags that are data clean-up, not something to raise at the meeting: shown collapsed,
# under "Data housekeeping". Conflicts, stale statements and overdue actions stay on top.
HOUSEKEEPING = {"duplicate_client", "duplicate_contact", "stale", "excluded_source", "unresolved_reference"}
AI_PROVIDERS = {"gemini", "openrouter", "ollama"}  # only these count as "AI written"; mock is a template

# ---------------------------------------------------------------------------
# Output shape (also the API response)
# ---------------------------------------------------------------------------


class Section(BaseModel):
    id: str
    title: str
    question: str
    bullets: list[Bullet] = []
    written_by: str = "code"            # code, mock, the model that answered, or "evidence (fallback)"
    provider: str | None = None         # gemini, openrouter, ollama, mock; None when code wrote it
    author: Literal["ai", "template", "code", "evidence"] = "code"  # for the label people see
    status: str = "ok"                  # ok, empty, unavailable, fallback
    check: Check = Check(passed=True)
    retry_note: str | None = None       # plain: "First draft rejected: a date wasn't in its source. ..."
    retry_errors: list[str] = []        # technical detail of that rejection (also in the audit log)
    note: str | None = None


class Change(BaseModel):
    text: str
    evidence_ids: list[str]


class MetricRow(BaseModel):
    label: str
    value: str
    change: str | None
    period: str | None                  # "Q3 2026"
    as_of: dt.date
    evidence_id: str


class OpportunityRow(BaseModel):
    opp_id: str
    product: str
    stage: str
    value: str
    owner: str
    next_step: str                      # "" when nothing is recorded
    updated: dt.date
    live: bool
    rank: int | None                    # 1 = discuss first; None for Lost or Won
    evidence_id: str


class ActionRow(BaseModel):
    action_id: str
    description: str
    owner: str
    due_date: dt.date
    status: str
    overdue: bool
    evidence_id: str


class FlagRow(BaseModel):
    flag_id: str
    flag_type: str
    title: str                          # e.g. "Who is the CFO?"
    severity: str
    housekeeping: bool                  # data clean-up, shown collapsed (see HOUSEKEEPING)
    detail: str
    source_ids: list[str]
    evidence_id: str


class LLMRun(BaseModel):
    provider: str
    model: str
    cached: bool
    notes: list[str]
    seconds: float = 0.0                # how long it took, fallbacks included (0 when cached)


class Briefing(BaseModel):
    client_id: str
    client_name: str
    segment: str
    region: str
    user_id: str
    prepared_for: str                   # "Sam Rivera (Analyst)"
    meeting_date: dt.date
    last_interaction: dt.date | None
    coverage: list[str]
    contacts: list[str]                 # key contacts, e.g. "Raj Patel, CFO"
    aliases: list[str]                  # names the data uses for this client (resolved by unify)
    what_changed: list[Change]
    sections: list[Section]
    metrics: list[MetricRow]
    opportunities: list[OpportunityRow]
    actions: list[ActionRow]
    flags: list[FlagRow]
    evidence: dict[str, Evidence]       # every citable item, for the citation chips
    llm_runs: list[LLMRun]
    generated_ms: int


class BriefingError(Exception):
    """The briefing can't start, e.g. the client doesn't exist."""

# ---------------------------------------------------------------------------
# Facts as plain sentences: all wording and number formatting happens here, in code
# ---------------------------------------------------------------------------


def metric_sentence(f: Fact) -> str:
    d, unit = f.details, f.details["unit"]
    label, value = f.label.removesuffix(" at last interaction"), value_text(f.value, unit)
    period = f"{period_text(d['period'])}, " if d["period"] else ""
    if d["role"] == "baseline":
        return f"{label} was {value} at the last meeting ({period}as of {day_month(f.as_of)})."
    when = f"in {period_text(d['period'])} (as of {day_month(f.as_of)})" if d["period"] else f"as of {day_month(f.as_of)}"
    change = f", {change_words(d['change'], unit)} since the last meeting" if "change" in d else ""
    return f"{label} was {value} {when}{change}."


def opportunity_sentence(f: Fact) -> str:
    d, note = f.details, clean_note(f.details["next_step"])
    if d["stage"] not in STAGE_PROBABILITY:  # Lost or Won
        return f"{f.label} was marked {d['stage']} on {day_month(f.as_of)}" + (f": {note}." if note else ".")
    text = f"{f.label} is at the {d['stage']} stage, estimated at {format_usd(f.value)} (owner {d['owner']})."
    return f"{text} Next step: {first_lower(note)}." if note else text


def action_sentence(f: Fact) -> str:
    d, due = f.details, day_month(f.details["due_date"])
    if d["status"] == "Done":
        return f"Done: {f.value} (owner {d['owner']}, was due on {due})."
    if d["overdue"]:
        return f"Overdue: {f.value} (owner {d['owner']}, due on {due}, {days_before(d['due_date'])} days ago)."
    return f"{f.value} (owner {d['owner']}, due on {due})."


def describe(f: Fact) -> str:
    """One fact as a plain sentence for the evidence bundle: who, what, when. No IDs."""
    d = f.details
    match f.source:
        case "clients":
            status = d["status"].lower()
            return f"{f.value} is {article(status)} {status} {d['segment']} client in {d['region']}."
        case "coverage":
            return f"{f.value} is the {d['coverage_role']} coverage banker (since {month_of(f.as_of)})."
        case "contacts":
            last = f"; last contact on {day_month(d['last_contact_date'])}" if d.get("last_contact_date") else ""
            return f"{f.value} is the {f.label} ({d['relationship_role'].lower()}){last}."
        case "revenue_metrics" | "holdings" | "performance":
            return metric_sentence(f)
        case "opportunities":
            return opportunity_sentence(f)
        case "open_actions":
            return action_sentence(f)
        case "service_issues":
            if d["status"] == "Open":
                return (f"Open service issue ({d['severity'].lower()} severity), opened on "
                        f"{day_month(d['opened'])}: {f.value}.")
            closed = f", closed {day_month(d['closed'])}" if d.get("closed") else ""
            return f"Resolved service issue: {f.value} (opened {day_month(d['opened'])}{closed})."
        case "data_quality_flags":
            title = d["title"]
            return f"{title}{'' if title.endswith('?') else '.'} {f.value}"
        case _:
            return str(f.value)  # document text, as written


def evidence_label(f: Fact) -> str:
    """What a source is, for people (the source panel and the Markdown footnotes). No IDs."""
    d = f.details
    match f.source:
        case "clients":
            return f"Client record: {f.value}"
        case "coverage":
            return f"Coverage: {f.value}"
        case "contacts":
            return f"Contact: {f.value}"
        case "revenue_metrics" | "holdings" | "performance":
            return f"{f.label.removesuffix(' at last interaction')}, {period_text(d['period']) or long_date(f.as_of)}"
        case "opportunities":
            return f"Opportunity: {f.label}"
        case "open_actions":
            return f"Action: {f.value}"
        case "service_issues":
            return f"Service issue: {f.value}"
        case "data_quality_flags":
            return f"Data-quality flag: {d['title']}"
        case _:
            kind = f.source if d.get("doc_type") == "news" else DOC_NAMES[d["doc_type"]]
            return f"{capitalize(kind)}, {long_date(f.as_of)}"


def suggestion(f: Fact) -> str | None:
    """How a fact reads as a talking point (an action), used when no AI writes them."""
    d = f.details
    if f.source == "data_quality_flags":
        return d.get("action")  # conflicts: what to clarify
    if f.source == "open_actions" and d.get("overdue"):
        return (f"Follow up on the overdue item: {first_lower(f.value)} (due {day_month(d['due_date'])}, "
                f"{days_before(d['due_date'])} days ago).")
    if f.source == "opportunities" and d["stage"] in STAGE_PROBABILITY:
        note = clean_note(d["next_step"])
        lead = f"Discuss {plain_words(f.label)} ({d['stage']}, estimated {format_usd(f.value)})"
        return f"{lead}: {first_lower(note)}." if note else f"{lead}."
    if f.source == "revenue_metrics" and f.label == "Revenue" and "change" in d:
        return (f"Note that revenue is {value_text(f.value, d['unit'])}, "
                f"{change_words(d['change'], d['unit'])} since the last meeting.")
    if d.get("doc_type") == "news":
        return f"Mention the news: {str(f.value).splitlines()[0]}."
    return None


def to_evidence(f: Fact, caveats: dict[str, tuple[str, str]]) -> Evidence:
    kind = "document" if f.evidence_id.startswith("DOC:") else "flag" if f.evidence_id.startswith("FLAG:") else "fact"
    caveat, caveat_id = caveats.get(f.evidence_id, (None, None))
    return Evidence(evidence_id=f.evidence_id, kind=kind, label=evidence_label(f), text=describe(f), as_of=f.as_of,
                    source=f.source, suggestion=suggestion(f), caveat=caveat, caveat_id=caveat_id)


def merge(items: list[Evidence]) -> list[Evidence]:
    """One evidence item per ID. Facts from the same row (revenue and wallet share) are joined."""
    merged = {}
    for e in items:
        old = merged.get(e.evidence_id)
        if old is None:
            merged[e.evidence_id] = e
        elif e.text not in old.text:
            merged[e.evidence_id] = old.model_copy(update={"text": f"{old.text} {e.text}"})
    return list(merged.values())

# ---------------------------------------------------------------------------
# Code-only pieces
# ---------------------------------------------------------------------------


def last_interaction(user: UserContext, client_id: str) -> dt.date | None:
    """The latest meeting note or prior briefing this user may see."""
    result = tools.search_documents(user, client_id=client_id, query="",
                                    doc_types=["meeting_note", "prior_briefing"], top_k=1)
    return result.facts[0].as_of if result.ok and result.facts else None


def metric_pairs(metric_facts: list[Fact]) -> list[tuple[Fact, Fact | None]]:
    """(latest, value at last interaction) for every metric series, revenue first."""
    by_id = {(f.evidence_id, f.label.removesuffix(" at last interaction")): f
             for f in metric_facts if f.details["role"] == "baseline"}
    pairs = [(f, by_id.get((f.details.get("baseline_evidence_id"), f.label)))
             for f in metric_facts if f.details["role"] == "latest"]
    return sorted(pairs, key=lambda pair: (pair[0].label != "Revenue", pair[0].label != "Wallet share"))


def rank_opportunities(opp_facts: list[Fact]) -> list[Fact]:
    """Live opportunities by expected value (estimate x stage probability), then the most recent."""
    live = [f for f in opp_facts if f.details["stage"] in STAGE_PROBABILITY]
    return sorted(live, key=lambda f: (f.value * STAGE_PROBABILITY[f.details["stage"]], f.as_of), reverse=True)


def what_changed(last: dt.date | None, metric_facts, opp_facts, action_facts, recent_docs) -> list[Change]:
    if last is None:
        return []
    since = day_month(last)
    changes = []
    for latest, baseline in metric_pairs(metric_facts):
        if baseline is not None and latest.details["change"] != 0:
            unit = latest.details["unit"]
            changes.append(Change(
                text=f"{latest.label} is {value_text(latest.value, unit)}, "
                     f"{change_words(latest.details['change'], unit)} since {since}.",
                evidence_ids=[latest.evidence_id, baseline.evidence_id]))
    for f in opp_facts:
        if f.as_of > last:
            stage = f.details["stage"]
            text = (f"{f.label} opportunity marked {stage} on {day_month(f.as_of)}." if stage not in STAGE_PROBABILITY
                    else f"{f.label} opportunity updated on {day_month(f.as_of)}; now at the {stage} stage.")
            changes.append(Change(text=text, evidence_ids=[f.evidence_id]))
    if recent_docs:
        counts = Counter(DOC_NAMES[f.details["doc_type"]] for f in recent_docs)
        listed = join_words([f"{n} {name}{'s' if n > 1 else ''}" for name, n in sorted(counts.items())])
        changes.append(Change(text=f"{capitalize(listed)} since {since}.",
                              evidence_ids=[f.evidence_id for f in recent_docs]))
    new_doc_ids = {f.details["doc_id"] for f in recent_docs}
    for f in action_facts:
        if f.source == "open_actions" and f.details["source_doc_id"] in new_doc_ids and f.details["status"] == "Open":
            changes.append(Change(text=f"New action for {f.details['owner']}: {first_lower(f.value)}, "
                                       f"due {day_month(f.details['due_date'])}.",
                                  evidence_ids=[f.evidence_id]))
    return changes


def metric_bullets(metric_facts: list[Fact]) -> list[Bullet]:
    bullets = []
    for latest, baseline in metric_pairs(metric_facts):
        text, citations = describe(latest), [latest.evidence_id]
        if baseline is not None:
            text = f"{text[:-1]} (was {value_text(baseline.value, baseline.details['unit'])})."
            citations.append(baseline.evidence_id)
        bullets.append(Bullet(text=text, citations=citations))
    return bullets


def hidden_content(user: UserContext) -> Hidden:
    """What this user may not see, so the validator can catch it if it ever appears."""
    with closing(db.connect()) as conn:
        rows = db.hidden_restricted_content(conn, user.entitlements)
    return Hidden(record_ids={r["record_id"] for r in rows}, texts=[r["text"] for r in rows])


def client_aliases(client_id: str) -> list[str]:
    """The names the source data uses for this client (not restricted), for the unification panel."""
    with closing(db.connect()) as conn:
        return db.aliases(conn, client_id)


def prepared_for(user: UserContext) -> str:
    with closing(db.connect()) as conn:
        row = db.user(conn, user.user_id)
    return f"{row['name']} ({row['role']})" if row else "you"


def retry_note(reasons: list[str], passed: bool) -> str:
    """The validator's verdict for a reader: what was wrong, and what happened next."""
    because = join_words(reasons) or "it failed a check"
    if passed:
        return f"First draft rejected: {because}. Regenerated and verified."
    return f"First draft rejected: {because}. The second draft failed too, so this shows the source facts directly."


def log_rejection(user: UserContext, section: str, draft: int, check: Check) -> None:
    """Keep the technical detail of every rejected draft in the audit log."""
    with contextlib.suppress(Exception):  # logging a rejection must never break the briefing
        audit.log_tool_call(user.user_id, "validator", {"section": section, "draft": draft}, [],
                            "; ".join(check.errors))

# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def build_briefing(user: UserContext, client_id: str, meeting_date: dt.date | None = None) -> Briefing:
    started = time.perf_counter()
    meeting_date = meeting_date or AS_OF_DATE

    # 1. Tools
    profile = tools.get_client_profile(user, client_id=client_id)
    if not profile.ok:
        raise BriefingError(profile.error)
    client = profile.facts[0]
    client_id = client.details["client_id"]
    last = last_interaction(user, client_id)
    results = {
        "client_overview": profile,
        "metrics": tools.get_metrics(user, client_id=client_id,
                                     since=last or meeting_date - dt.timedelta(days=NEWS_WINDOW_DAYS)),
        "client_said": tools.search_documents(user, client_id=client_id, query=ASKS_QUERY, top_k=4,
                                              doc_types=["meeting_note", "email", "prior_briefing"]),
        "opportunities": tools.get_opportunities(user, client_id=client_id),
        "open_items": tools.get_open_items(user, client_id=client_id),
        "news": tools.get_news(user, client_id=client_id, since=meeting_date - dt.timedelta(days=NEWS_WINDOW_DAYS)),
        "uncertain": tools.get_data_quality_flags(user, client_id=client_id),
    }
    recent_docs = tools.search_documents(user, client_id=client_id, query="", top_k=20,
                                         since=last + dt.timedelta(days=1)).facts if last else []
    facts = {name: r.facts for name, r in results.items()}

    # 2. Evidence, ranked and filtered by code
    flags = sorted(facts["uncertain"], key=lambda f: (f.label in HOUSEKEEPING, SEVERITY_ORDER[f.details["severity"]],
                                                      f.evidence_id))
    ranked = rank_opportunities(facts["opportunities"])
    not_live = [f for f in facts["opportunities"] if f not in ranked]
    open_items = [f for f in facts["open_items"] if f.details["status"] == "Open"]
    overdue = [f for f in open_items if f.details.get("overdue")]
    conflicts = [f for f in flags if f.label == "conflict"]
    # A contradicted document carries its flag's caveat, so the statement is marked where it appears
    caveats = {source_id: (f.details["caveat"], f.evidence_id) for f in conflicts if f.details.get("caveat")
               for source_id in f.details["source_ids"] if source_id.startswith("DOC:")}

    def related_flags(items: list[Fact]) -> list[Fact]:
        ids = {f.evidence_id for f in items}
        return [f for f in flags if f.details["severity"] != "low" and ids & set(f.details["source_ids"])]

    revenue = [f for f, _ in metric_pairs(facts["metrics"]) if f.label == "Revenue"]
    evidence = {
        "client_overview": facts["client_overview"],
        "metrics": facts["metrics"],
        "client_said": facts["client_said"] + related_flags(facts["client_said"]),
        "opportunities": ranked + not_live + related_flags(facts["opportunities"]),
        "open_items": sorted(open_items, key=lambda f: not f.details.get("overdue")),
        "news": facts["news"],
        "uncertain": flags,
        # Talking points draw on the whole briefing: what to clarify first, then priorities
        "talking_points": conflicts + overdue + ranked[:2] + revenue + facts["news"][:1] + open_items + ranked,
    }
    bundles = {name: SectionEvidence(section=name, question=QUESTIONS[name],
                                     evidence=merge([to_evidence(f, caveats) for f in evidence[name]]))
               for name in QUESTIONS}

    # 3. Code writes the numeric and rule-based sections; one LLM call writes the rest
    hidden = hidden_content(user)
    drafts = {"metrics": metric_bullets(facts["metrics"]),
              "uncertain": [Bullet(text=describe(f), citations=[f.evidence_id]) for f in flags]}
    written_by = {name: "code" for name in CODE_SECTIONS}
    author = {name: "code" for name in CODE_SECTIONS}
    tool_failed = {name for name, r in results.items() if not r.ok}
    to_write = [bundles[name] for name in QUESTIONS
                if name not in CODE_SECTIONS and name not in tool_failed and bundles[name].evidence]
    runs, first_checks, provider_of = [], {}, {}

    def keep_passing(bundles: list[SectionEvidence], completion: llm.Completion, attempt: int):
        """Validate each section of an answer: keep the ones that pass, return (bundle, check) for the rest."""
        parsed, schema_errors = validate.parse_draft(completion.data)
        failed = []
        for bundle in bundles:
            check = validate.check_section(parsed.get(bundle.section), bundle, hidden, schema_errors)
            if check.passed:
                drafts[bundle.section] = parsed[bundle.section].bullets
                written_by[bundle.section], author[bundle.section] = completion.model, kind_of(completion)
                provider_of[bundle.section] = completion.provider
            else:
                failed.append((bundle, check))
                first_checks.setdefault(bundle.section, check)
                log_rejection(user, bundle.section, attempt, check)
        if not failed:
            llm.mark_validated(completion)  # only answers that fully pass are replayed with CACHE_REPLAY=any
        return failed

    # 4. Write, validate, and retry failed sections once with the errors on the same provider.
    #    If they fail again, the next provider in LLM_CHAIN writes them; after the last one,
    #    a section shows its evidence itself.
    pending, chain, attempt = to_write, llm.llm_chain(), 0
    while pending and chain:
        first = llm.write_sections(pending, chain=chain)
        runs.append(first)
        attempt += 1
        failed = keep_passing(pending, first, attempt)
        if failed and first.provider in chain:
            retry = llm.write_sections([b for b, _ in failed], feedback={b.section: c.errors for b, c in failed},
                                       chain=[first.provider])
            runs.append(retry)
            attempt += 1
            failed = keep_passing([b for b, _ in failed], retry, attempt)
        pending = [b for b, _ in failed]
        chain = chain[chain.index(first.provider) + 1:] if first.provider in chain else []
    for bundle in pending:
        drafts[bundle.section] = llm.evidence_bullets(bundle)
        written_by[bundle.section], author[bundle.section] = "evidence (fallback)", "evidence"

    # Full names, whoever wrote the bullet: "Raj said" -> "Raj Patel said"
    people = [f.value for f in facts["client_overview"] if f.source in ("contacts", "coverage")]
    drafts = {name: [b.model_copy(update={"text": full_names(b.text, people)}) for b in bullets]
              for name, bullets in drafts.items()}

    # Assemble the sections, validating every one (again) on its final text
    sections = []
    for name, title, question in PLAN:
        section = Section(id=name, title=title, question=question)
        source = results.get(name)
        if source is not None and not source.ok:
            section.status, section.note = "unavailable", "Unavailable: the data could not be loaded."
        elif name not in drafts:
            section.status, section.note = "empty", "Nothing on file for this question."
        else:
            section.bullets, section.written_by, section.author = drafts[name], written_by[name], author[name]
            section.provider = provider_of.get(name)
            section.check = validate.check_section(SectionDraft(section=name, bullets=drafts[name]), bundles[name], hidden)
            if name in first_checks:
                section.retry_errors = first_checks[name].errors
                section.retry_note = retry_note(first_checks[name].reasons, passed=author[name] != "evidence")
            if author[name] == "evidence":
                section.status = "fallback"
            elif not section.bullets:
                section.status, section.note = "empty", "Nothing on file for this question."
        sections.append(section)

    # Everything a chip can open: the bundles, new documents, and every row of the actions
    # table (done actions are shown there but are not evidence for any section)
    all_evidence = merge([e for b in bundles.values() for e in b.evidence]
                         + [to_evidence(f, caveats) for f in recent_docs + facts["open_items"]])
    return Briefing(
        client_id=client_id, client_name=client.value, segment=client.details["segment"],
        region=client.details["region"], user_id=user.user_id, prepared_for=prepared_for(user),
        meeting_date=meeting_date, last_interaction=last,
        coverage=[f"{f.value} ({f.details['coverage_role']})" for f in facts["client_overview"] if f.source == "coverage"],
        contacts=[f"{f.value}, {f.label}" for f in facts["client_overview"] if f.source == "contacts"],
        aliases=client_aliases(client_id),
        what_changed=what_changed(last, facts["metrics"], facts["opportunities"], facts["open_items"], recent_docs),
        sections=sections,
        metrics=[MetricRow(label=f.label, value=value_text(f.value, f.details["unit"]),
                           change=signed_change(f.details["change"], f.details["unit"]) if "change" in f.details else None,
                           period=period_text(f.details["period"]) or None, as_of=f.as_of, evidence_id=f.evidence_id)
                 for f, _ in metric_pairs(facts["metrics"])],
        opportunities=[OpportunityRow(opp_id=f.details["opp_id"], product=f.label, stage=f.details["stage"],
                                      value=format_usd(f.value), owner=f.details["owner"],
                                      next_step=clean_note(f.details["next_step"]) or "", updated=f.as_of,
                                      live=f in ranked, rank=ranked.index(f) + 1 if f in ranked else None,
                                      evidence_id=f.evidence_id)
                       for f in ranked + not_live],
        actions=[ActionRow(action_id=f.details["action_id"], description=f.value, owner=f.details["owner"],
                           due_date=f.details["due_date"], status=f.details["status"], overdue=f.details["overdue"],
                           evidence_id=f.evidence_id)
                 for f in facts["open_items"] if f.source == "open_actions"],
        flags=[FlagRow(flag_id=f.evidence_id.removeprefix("FLAG:"), flag_type=f.label, title=f.details["title"],
                       severity=f.details["severity"], housekeeping=f.label in HOUSEKEEPING, detail=f.value, source_ids=f.details["source_ids"],
                       evidence_id=f.evidence_id) for f in flags],
        evidence={e.evidence_id: e for e in all_evidence},
        llm_runs=[LLMRun(provider=r.provider, model=r.model, cached=r.cached, notes=r.notes, seconds=r.seconds)
                  for r in runs],
        generated_ms=round((time.perf_counter() - started) * 1000),
    )


def kind_of(completion: llm.Completion) -> str:
    """AI only when a real model wrote it; mock mode is a template built from the evidence."""
    return "ai" if completion.provider in AI_PROVIDERS else "template"

# ---------------------------------------------------------------------------
# Markdown export and command line
# ---------------------------------------------------------------------------

AUTHOR_LABELS = {"ai": "AI written, checks passed", "template": "Template (no AI)",
                 "code": "Computed by code, no LLM", "evidence": "Source facts shown, draft failed checks"}


def to_markdown(b: Briefing) -> str:
    """The briefing as a note to paste into email or the CRM. Citations are numbered
    footnotes with plain source names, so no internal IDs appear in the text."""
    numbers: dict[str, int] = {}

    def cite(ids: list[str]) -> str:
        for evidence_id in ids:
            numbers.setdefault(evidence_id, len(numbers) + 1)
        return "".join(f"[{numbers[i]}]" for i in ids)

    lines = [f"# {b.client_name}", "",
             f"Briefing for the meeting on {long_date(b.meeting_date)}, prepared for {b.prepared_for}.",
             f"Last interaction: {long_date(b.last_interaction) if b.last_interaction else 'none on file'}. "
             f"{b.segment}, {b.region}. Coverage: {', '.join(b.coverage)}.", ""]
    if b.what_changed:
        lines += [f"## What changed since {long_date(b.last_interaction)}",
                  *[f"- {c.text} {cite(c.evidence_ids)}" for c in b.what_changed], ""]
    for s in b.sections:
        label = AUTHOR_LABELS[s.author] + (f" ({s.provider}: {s.written_by})" if s.author == "ai" else "")
        lines += [f"## {s.title}", f"_{label}_", ""]
        if s.note:
            lines += [f"> {s.note}", ""]
        if s.retry_note:
            lines += [f"> {s.retry_note}", ""]
        if s.id == "uncertain":
            housekeeping = [f for f in b.flags if f.housekeeping]
            lines += [f"- **{f.title}** {f.detail} {cite([f.evidence_id])}" for f in b.flags if not f.housekeeping]
            if housekeeping and len(housekeeping) == len(b.flags):
                lines.append("Nothing to raise at the meeting.")
            if housekeeping:
                lines += ["", f"Data housekeeping ({len(housekeeping)}):",
                          *[f"- {f.title}. {f.detail} {cite([f.evidence_id])}" for f in housekeeping]]
        else:
            lines += [f"- {bullet.text} {cite(bullet.citations)}" for bullet in s.bullets]
        lines.append("")
    lines += ["## Key metrics", "", "| Metric | Value | Change | As of |", "| --- | --- | --- | --- |"]
    lines += [f"| {m.label} | {m.value} | {m.change or ''} | {long_date(m.as_of)} |" for m in b.metrics]
    lines += ["", "## Sources", ""]
    lines += [f"{n}. {b.evidence[i].label if i in b.evidence else 'Source'}" for i, n in numbers.items()]
    lines += ["", f"_Generated in {b.generated_ms / 1000:.1f} s. Narrative: {llm_summary(b)}._"]
    return "\n".join(lines)


def llm_summary(b: Briefing) -> str:
    """Which model wrote the briefing (and how many calls), and why it fell back if it did."""
    if not b.llm_runs:
        return "none"
    used = Counter(f"{'template (no AI)' if r.provider == 'mock' else f'{r.provider}: {r.model}'}"
                   f"{' (cached)' if r.cached else ''}"
                   for r in b.llm_runs)
    text = ", ".join(f"{model} x{n}" if n > 1 else model for model, n in used.items())
    notes = list(dict.fromkeys(note for r in b.llm_runs for note in r.notes))  # unique, in order
    return f"{text} (after: {'; '.join(notes)})" if notes else text


def main() -> None:
    parser = argparse.ArgumentParser(description="Print one client briefing as Markdown.")
    parser.add_argument("--client", default="C001", help="client ID, name, or alias, e.g. NWC")
    parser.add_argument("--user", default="u2", help="u1 (Alex, restricted_deals) or u2 (Sam, standard)")
    parser.add_argument("--meeting-date", type=dt.date.fromisoformat, default=AS_OF_DATE)
    args = parser.parse_args()
    user = tools.load_user(args.user)
    if user is None:
        raise SystemExit(f"Unknown user {args.user!r}")
    resolved = tools.resolve_client(user, name_or_alias=args.client)
    if not resolved.ok:
        raise SystemExit(f"Could not resolve {args.client!r}: {resolved.error}; candidates {resolved.candidates}")
    briefing = build_briefing(user, resolved.facts[0].details["client_id"], args.meeting_date)
    for note in dict.fromkeys(note for run in briefing.llm_runs for note in run.notes):
        print(f"warning: {note}", file=sys.stderr)  # e.g. why Gemini fell back to another model
    sys.stdout.reconfigure(encoding="utf-8")  # "⚠" and quotes survive redirection to a file on Windows
    print(to_markdown(briefing))


if __name__ == "__main__":
    main()
