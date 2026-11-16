"""Builds one client briefing with a fixed plan (SPEC.md section 5).

  1. Call the tools: read-only, filtered by the user's entitlements, audited.
  2. Build an evidence bundle per section. Every number is formatted here, in code.
  3. Code writes the purely numeric and rule-based parts: the metrics section, the
     "uncertain, conflicting, or unavailable" section, and the "what changed" strip.
     ONE LLM call writes the other sections (app/llm.py).
  4. Validate every section (app/validate.py). Failed sections are retried once with
     the errors; if a section fails again, it shows its evidence as plain bullets.

Run:  make briefing CLIENT=NWC USER_ID=u2   (or: python -m app.orchestrator --client NWC --user u2)
"""

import argparse
import datetime as dt
import sys
import time
from collections import Counter
from contextlib import closing

from pydantic import BaseModel

from app import db, llm, tools, validate
from app.tools import Fact, UserContext
from app.unify import AS_OF_DATE, DOC_TYPE_NAMES, format_usd
from app.validate import Bullet, Check, Evidence, Hidden, SectionDraft, SectionEvidence

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

# ---------------------------------------------------------------------------
# Output shape (also the API response in Phase 5)
# ---------------------------------------------------------------------------


class Section(BaseModel):
    id: str
    title: str
    question: str
    bullets: list[Bullet] = []
    written_by: str = "code"            # code, mock, a model name, or "evidence (fallback)"
    status: str = "ok"                  # ok, empty, unavailable, fallback
    check: Check = Check(passed=True)
    retry_errors: list[str] = []        # why the model's first draft failed, if it did
    note: str | None = None


class Change(BaseModel):
    text: str
    evidence_ids: list[str]


class MetricRow(BaseModel):
    label: str
    value: str
    change: str | None
    period: str | None
    as_of: dt.date
    evidence_id: str


class OpportunityRow(BaseModel):
    opp_id: str
    product: str
    stage: str
    value: str
    owner: str
    next_step: str
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
    severity: str
    detail: str
    source_ids: list[str]
    evidence_id: str


class LLMRun(BaseModel):
    provider: str
    model: str
    cached: bool
    notes: list[str]


class Briefing(BaseModel):
    client_id: str
    client_name: str
    segment: str
    region: str
    user_id: str
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
# Numbers and facts as text: all formatting happens here, in code
# ---------------------------------------------------------------------------


def value_text(value: float, unit: str) -> str:
    return f"{value:g}%" if unit == "pct" else format_usd(value)


def change_text(change: float, unit: str) -> str:
    sign = "+" if change >= 0 else "-"
    return f"{sign}{abs(change):g} pts" if unit == "pct" else f"{sign}{format_usd(abs(change))}"


def describe(f: Fact) -> str:
    """One fact as a plain sentence for the evidence bundle, with numbers formatted."""
    d = f.details
    match f.source:
        case "clients":
            return f"{f.value}: segment {d['segment']}, region {d['region']}, status {d['status']}"
        case "coverage":
            return f"{d['coverage_role'].capitalize()} coverage: {f.value} (since {f.as_of})"
        case "contacts":
            return f"{f.label}: {f.value} ({d['relationship_role']}), last contact {d['last_contact_date']}"
        case "revenue_metrics" | "holdings" | "performance":
            text = f"{f.label}: {value_text(f.value, d['unit'])} ({d['period'] + ', ' if d['period'] else ''}as of {f.as_of})"
            if "change" in d:
                text += f"; change since last interaction: {change_text(d['change'], d['unit'])}"
            return text
        case "opportunities":
            return (f"{f.label} ({d['opp_id']}): stage {d['stage']}, estimated value {format_usd(f.value)}, "
                    f"owner {d['owner']}, next step: {d['next_step']} (updated {f.as_of})")
        case "open_actions":
            return (f"Action {d['action_id']}: {f.value}; owner {d['owner']}; due {d['due_date']}; "
                    f"status {d['status']}" + ("; OVERDUE" if d["overdue"] else ""))
        case "service_issues":
            closed = f"; closed {d['closed']}" if d["closed"] else ""
            return (f"Service issue {d['issue_id']}: {f.value}; severity {d['severity']}; status {d['status']}; "
                    f"opened {d['opened']}{closed}")
        case "data_quality_flags":
            return f"{f.label} ({d['severity']}): {f.value}"
        case _:
            return str(f.value)  # document text, as written


def to_evidence(f: Fact) -> Evidence:
    if f.evidence_id.startswith("DOC:"):
        kind, label = "document", f"{DOC_TYPE_NAMES[f.details['doc_type']].capitalize()} {f.details['doc_id']}"
    else:
        kind, label = ("flag" if f.evidence_id.startswith("FLAG:") else "fact"), f.label
    return Evidence(evidence_id=f.evidence_id, kind=kind, label=label, text=describe(f), as_of=f.as_of,
                    source=f.source)


def merge(items: list[Evidence]) -> list[Evidence]:
    """One evidence item per ID. Facts from the same row (revenue and wallet share) are joined."""
    merged = {}
    for e in items:
        old = merged.get(e.evidence_id)
        if old is None:
            merged[e.evidence_id] = e
        elif e.text not in old.text:
            merged[e.evidence_id] = old.model_copy(update={"text": f"{old.text}; {e.text}"})
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
    """(latest, value at last interaction) for every metric series."""
    by_id = {(f.evidence_id, f.label.removesuffix(" at last interaction")): f
             for f in metric_facts if f.details["role"] == "baseline"}
    pairs = [(f, by_id.get((f.details.get("baseline_evidence_id"), f.label)))
             for f in metric_facts if f.details["role"] == "latest"]
    return sorted(pairs, key=lambda pair: (pair[0].label != "Revenue", pair[0].label != "Wallet share"))  # revenue first


def rank_opportunities(opp_facts: list[Fact]) -> list[Fact]:
    """Live opportunities by expected value (estimate x stage probability), then the most recent."""
    live = [f for f in opp_facts if f.details["stage"] in STAGE_PROBABILITY]
    return sorted(live, key=lambda f: (f.value * STAGE_PROBABILITY[f.details["stage"]], f.as_of), reverse=True)


def what_changed(last: dt.date | None, metric_facts, opp_facts, action_facts, recent_docs) -> list[Change]:
    if last is None:
        return []
    changes = []
    for latest, baseline in metric_pairs(metric_facts):
        if baseline is not None and latest.details["change"] != 0:
            unit = latest.details["unit"]
            changes.append(Change(
                text=f"{latest.label}: {value_text(latest.value, unit)} "
                     f"({change_text(latest.details['change'], unit)} since {last})",
                evidence_ids=[latest.evidence_id, baseline.evidence_id]))
    for f in opp_facts:
        if f.as_of > last:
            changes.append(Change(text=f"{f.label} ({f.details['opp_id']}) updated {f.as_of}: now {f.details['stage']}",
                                  evidence_ids=[f.evidence_id]))
    if recent_docs:
        counts = Counter(DOC_TYPE_NAMES[f.details["doc_type"]] for f in recent_docs)
        listed = ", ".join(f"{n} {name}{'s' if n > 1 else ''}" for name, n in sorted(counts.items()))
        changes.append(Change(text=f"New since {last}: {listed}", evidence_ids=[f.evidence_id for f in recent_docs]))
    new_doc_ids = {f.details["doc_id"] for f in recent_docs}
    for f in action_facts:
        if f.source == "open_actions" and f.details["source_doc_id"] in new_doc_ids and f.details["status"] == "Open":
            changes.append(Change(text=f"New action: {f.value} (owner {f.details['owner']}, due {f.details['due_date']})",
                                  evidence_ids=[f.evidence_id]))
    return changes


def metric_bullets(metric_facts: list[Fact]) -> list[Bullet]:
    bullets = []
    for latest, baseline in metric_pairs(metric_facts):
        text, citations = describe(latest), [latest.evidence_id]
        if baseline is not None:
            text += f" (was {value_text(baseline.value, baseline.details['unit'])} as of {baseline.as_of})"
            citations.append(baseline.evidence_id)
        bullets.append(Bullet(text=text, citations=citations))
    return bullets


def client_aliases(client_id: str) -> list[str]:
    """The names the source data uses for this client (not restricted), for the unification panel."""
    with closing(db.connect()) as conn:
        return db.aliases(conn, client_id)


def hidden_content(user: UserContext) -> Hidden:
    """What this user may not see, so the validator can catch it if it ever appears."""
    with closing(db.connect()) as conn:
        rows = db.hidden_restricted_content(conn, user.entitlements)
    return Hidden(record_ids={r["record_id"] for r in rows}, texts=[r["text"] for r in rows])

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
    flags = sorted(facts["uncertain"], key=lambda f: (SEVERITY_ORDER[f.details["severity"]], f.evidence_id))
    ranked = rank_opportunities(facts["opportunities"])
    not_live = [f for f in facts["opportunities"] if f not in ranked]
    open_items = [f for f in facts["open_items"] if f.details["status"] == "Open"]
    overdue = [f for f in open_items if f.details.get("overdue")]

    def related_flags(items: list[Fact]) -> list[Fact]:
        ids = {f.evidence_id for f in items}
        return [f for f in flags if f.details["severity"] != "low" and ids & set(f.details["source_ids"])]

    revenue = [f for f, _ in metric_pairs(facts["metrics"]) if f.label == "Revenue"]
    evidence = {
        "client_overview": facts["client_overview"],
        "client_said": facts["client_said"] + related_flags(facts["client_said"]),
        "opportunities": ranked + not_live + related_flags(facts["opportunities"]),
        "open_items": sorted(open_items, key=lambda f: not f.details.get("overdue")),
        "news": facts["news"],
        # Talking points may draw on the whole briefing: priorities first, then everything else key
        "talking_points": overdue + ranked[:2] + [f for f in flags if f.details["severity"] == "high"]
                          + revenue + open_items + ranked + facts["news"],
    }
    evidence["metrics"], evidence["uncertain"] = facts["metrics"], flags
    bundles = {name: SectionEvidence(section=name, question=QUESTIONS[name],
                                     evidence=merge([to_evidence(f) for f in evidence[name]]))
               for name in QUESTIONS}

    # 3. Code writes the numeric and rule-based sections; one LLM call writes the rest
    hidden = hidden_content(user)
    drafts = {"metrics": metric_bullets(facts["metrics"]),
              "uncertain": [Bullet(text=f.value, citations=[f.evidence_id]) for f in flags]}
    written_by = {name: "code" for name in CODE_SECTIONS}
    tool_failed = {name for name, r in results.items() if not r.ok}
    to_write = [bundles[name] for name in QUESTIONS
                if name not in CODE_SECTIONS and name not in tool_failed and bundles[name].evidence]
    runs = []
    checks = {}
    first_errors = {}  # section -> why its first draft failed, shown to the user
    if to_write:
        completion = llm.write_sections(to_write)
        runs.append(completion)
        parsed, schema_errors = validate.parse_draft(completion.data)
        failed = []
        for bundle in to_write:
            checks[bundle.section] = validate.check_section(parsed.get(bundle.section), bundle, hidden, schema_errors)
            if checks[bundle.section].passed:
                drafts[bundle.section], written_by[bundle.section] = parsed[bundle.section].bullets, completion.model
            else:
                failed.append(bundle)
        # 4. Retry the failed sections once, with the errors; then fall back to the evidence itself
        first_errors = {b.section: checks[b.section].errors for b in failed}
        if failed:
            retry = llm.write_sections(failed, feedback={b.section: checks[b.section].errors for b in failed})
            runs.append(retry)
            parsed, schema_errors = validate.parse_draft(retry.data)
            for bundle in failed:
                check = validate.check_section(parsed.get(bundle.section), bundle, hidden, schema_errors)
                if check.passed:
                    drafts[bundle.section], written_by[bundle.section] = parsed[bundle.section].bullets, retry.model
                else:
                    drafts[bundle.section], written_by[bundle.section] = llm.evidence_bullets(bundle), "evidence (fallback)"
                checks[bundle.section] = check

    # Assemble the sections, validating the code-written ones too
    sections = []
    for name, title, question in PLAN:
        section = Section(id=name, title=title, question=question)
        source = results.get(name)
        if source is not None and not source.ok:
            section.status, section.note = "unavailable", f"Unavailable: the data could not be loaded ({source.error})."
        elif name not in drafts:
            section.status, section.note = "empty", "Nothing on file for this question."
        else:
            section.bullets, section.written_by = drafts[name], written_by[name]
            section.retry_errors = first_errors.get(name, [])
            section.check = validate.check_section(SectionDraft(section=name, bullets=drafts[name]), bundles[name], hidden)
            if written_by[name] == "evidence (fallback)":
                section.status = "fallback"
                section.note = "Could not summarize: the model's answer failed the checks twice, so this shows the evidence."
            elif not section.bullets:
                section.status, section.note = "empty", "Nothing on file for this question."
        sections.append(section)

    all_evidence = merge([e for b in bundles.values() for e in b.evidence]
                         + [to_evidence(f) for f in recent_docs])
    return Briefing(
        client_id=client_id, client_name=client.value, segment=client.details["segment"],
        region=client.details["region"], user_id=user.user_id, meeting_date=meeting_date, last_interaction=last,
        coverage=[f"{f.value} ({f.details['coverage_role']})" for f in facts["client_overview"] if f.source == "coverage"],
        contacts=[f"{f.value}, {f.label}" for f in facts["client_overview"] if f.source == "contacts"],
        aliases=client_aliases(client_id),
        what_changed=what_changed(last, facts["metrics"], facts["opportunities"], facts["open_items"], recent_docs),
        sections=sections,
        metrics=[MetricRow(label=f.label, value=value_text(f.value, f.details["unit"]),
                           change=change_text(f.details["change"], f.details["unit"]) if "change" in f.details else None,
                           period=f.details["period"], as_of=f.as_of, evidence_id=f.evidence_id)
                 for f, _ in metric_pairs(facts["metrics"])],
        opportunities=[OpportunityRow(opp_id=f.details["opp_id"], product=f.label, stage=f.details["stage"],
                                      value=format_usd(f.value), owner=f.details["owner"],
                                      next_step=f.details["next_step"], updated=f.as_of, live=f in ranked,
                                      rank=ranked.index(f) + 1 if f in ranked else None, evidence_id=f.evidence_id)
                       for f in ranked + not_live],
        actions=[ActionRow(action_id=f.details["action_id"], description=f.value, owner=f.details["owner"],
                           due_date=f.details["due_date"], status=f.details["status"], overdue=f.details["overdue"],
                           evidence_id=f.evidence_id)
                 for f in facts["open_items"] if f.source == "open_actions"],
        flags=[FlagRow(flag_id=f.evidence_id.removeprefix("FLAG:"), flag_type=f.label, severity=f.details["severity"],
                       detail=f.value, source_ids=f.details["source_ids"], evidence_id=f.evidence_id) for f in flags],
        evidence={e.evidence_id: e for e in all_evidence},
        llm_runs=[LLMRun(provider=r.provider, model=r.model, cached=r.cached, notes=r.notes) for r in runs],
        generated_ms=round((time.perf_counter() - started) * 1000),
    )

# ---------------------------------------------------------------------------
# Markdown export and command line
# ---------------------------------------------------------------------------


def to_markdown(b: Briefing) -> str:
    lines = [f"# Client briefing: {b.client_name} ({b.client_id})", "",
             f"Meeting {b.meeting_date} | prepared for {b.user_id} | last interaction {b.last_interaction or 'none on file'}",
             f"Segment {b.segment}, {b.region} | Coverage: {', '.join(b.coverage)}", ""]
    if b.what_changed:
        lines += [f"## What changed since {b.last_interaction}", *[f"- {c.text}" for c in b.what_changed], ""]
    for s in b.sections:
        badge = "checks passed" if s.check.passed else "checks failed"
        lines += [f"## {s.title}", f"_{s.question}_ (written by {s.written_by}; {badge})", ""]
        if s.note:
            lines += [f"> {s.note}", ""]
        if s.retry_errors:
            outcome = f"the retry by {s.written_by} passed" if s.status != "fallback" else "the retry failed too"
            lines += [f"> The validator rejected the first draft ({'; '.join(s.retry_errors)}); {outcome}.", ""]
        lines += [f"- {bullet.text} [{', '.join(bullet.citations)}]" for bullet in s.bullets] + [""]
    lines += ["## Key metrics", "", "| Metric | Value | Change | As of |", "| --- | --- | --- | --- |"]
    lines += [f"| {m.label} | {m.value} | {m.change or ''} | {m.as_of} |" for m in b.metrics]
    lines += ["", f"_Generated in {b.generated_ms} ms. LLM: {llm_summary(b)}._"]
    return "\n".join(lines)


def llm_summary(b: Briefing) -> str:
    """Which model wrote the briefing (and how many calls), and why it fell back if it did."""
    if not b.llm_runs:
        return "none"
    used = Counter(f"{r.model}{' (cached)' if r.cached else ''}" for r in b.llm_runs)
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
    print(to_markdown(briefing))


if __name__ == "__main__":
    main()
