"""`make results`: the README's results section, written from the saved eval reports so that no
number is ever typed by hand.

Reads eval/last_run.json (the last `make eval`), eval/history/ (the held-out first runs and the
last real-model run) and rewrites the text between the RESULTS markers in README.md and in
docs/EVALUATION.md ("Current results").

Run:  make results   (after make eval)
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "eval" / "last_run.json"
HISTORY = ROOT / "eval" / "history"
README = ROOT / "README.md"
EVALUATION_DOC = ROOT / "docs" / "EVALUATION.md"
PRESENTATION = ROOT / "PRESENTATION.md"
START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"
NAMES = {"dev": "Dev", "dev2": "Dev 2", "holdout": "Holdout"}
METRICS = [("precision@5", "P@5"), ("recall@5", "R@5"), ("mrr", "MRR"), ("ndcg@5", "nDCG@5")]
METHODS = [("bm25", "BM25 only"), ("vector", "Vector only"), ("hybrid", "Hybrid (RRF, used by the app)")]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def run_name(card: dict) -> str:
    return f"{NAMES[card['dataset']]} ({'template' if card['provider'] == 'mock' else 'live model'})"


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header), *("| " + " | ".join(r) + " |" for r in rows)]


def scorecard(cards: list[dict]) -> list[str]:
    rows = []
    for i, check in enumerate(cards[0]["checks"]):
        name = check["name"] + (" (zero tolerance)" if check["zero_tolerance"] else "")
        cells = [f"{c['checks'][i]['result']} {'pass' if c['checks'][i]['passed'] else '**FAIL**'}" for c in cards]
        rows.append([name, check["target"], *cells])
    rows.append(["Latency per briefing", "report", *(c["latency"] for c in cards)])
    rows.append(["LLM requests per briefing", "report", *(f"{c['cost']['requests']:g}" for c in cards)])
    return table(["Check", "Target", *(run_name(c) for c in cards)], rows)


def retrieval(q: dict, datasets: list[str]) -> list[str]:
    rows = [[label, *(" / ".join(f"{q['retrieval'][d]['methods'][m][key]:.2f}" for d in datasets) for key, _ in METRICS)]
            for m, label in METHODS]
    leaked = " / ".join(str(q["retrieval"][d]["restricted_retrieved"]) for d in datasets)
    scored = " / ".join(str(q["retrieval"][d]["scored"]) for d in datasets)
    return [f"Top 5 documents per question, entitlement filter on; values are {' / '.join(NAMES[d] for d in datasets)} "
            f"({scored} labelled questions).", "",
            *table(["Method", *(label for _, label in METRICS)], rows), "",
            f"Restricted documents returned to a user without access: {leaked}."]


def detectors(q: dict, datasets: list[str]) -> list[str]:
    names = list(q["detectors"][datasets[0]]["detectors"])
    rows = []
    for name in names:
        reports = [q["detectors"][d]["detectors"][name] for d in datasets]
        rows.append([name, " / ".join(str(r["cases"]) for r in reports),
                     *(" / ".join(f"{r[key]:.2f}" for r in reports) for key in ("precision", "recall", "f1"))])
    return [f"Generated perturbations (aliases, typos, suffixes, case, look-alikes, true conflicts and near-misses); "
            f"values are {' / '.join(NAMES[d] for d in datasets)}.", "",
            *table(["Detector", "Cases", "Precision", "Recall", "F1"], rows)]


def router(q: dict) -> list[str]:
    r = q["router"]
    right = sum(row[i] for i, row in enumerate(r["confusion"]))
    lines = [f"{right} of {r['questions']} labelled questions routed as expected ({r['accuracy']:.0%}), "
             f"in template mode (the LLM tie-breaker is off)."]
    return lines + [f"- Missed: {m}" for m in r["misroutes"]]


def faithfulness() -> list[str]:
    real = load(HISTORY / "eval_real.json")
    if not real:
        return ["Not measured yet: it needs `make eval-real` with a working model (template mode writes no AI text)."]
    lines = []
    for card, f in zip(real["cards"], real["faithfulness"]):
        lines.append(f"- {NAMES[card['dataset']]} data, chain `{card['provider']}`, answered by {card['models']} "
                     f"(run {real['ran_at'][:16].replace('T', ' ')} UTC): {f['supported']} of {f['claims']} claims "
                     f"supported by the evidence they cite ({f['faithfulness']:.1%}); first drafts rejected by the "
                     f"validator: {f['first_drafts_rejected']} of {f['llm_sections']} sections "
                     f"({(f['rejection_rate'] or 0):.1%}); {card['cost']['requests']:g} real requests per briefing.")
        failed = [c["name"] for c in card["checks"] if not c["passed"]]
        lines.append(f"- With the model writing the text, {'every scorecard check passed' if not failed else 'failed: ' + ', '.join(failed)} "
                     f"(" + "; ".join(f"{c['name'].lower()} {c['result']}" for c in card["checks"] if c["name"] in
                                       ("Numeric accuracy", "Citation validity", "Restricted leakage", "Injection resistance")) + ").")
        if "(cached)" in card["models"]:
            lines.append("- Some briefings replayed that model's cached answers; a cached answer already passed the "
                         "validator once, so it can't count as a rejected first draft.")
    lines.append("- Faithfulness is a word-overlap and number check per claim, not a human judgment; a paraphrase can "
                 "count as unsupported.")
    return lines


def history() -> list[str]:
    lines = []
    round1 = load(HISTORY / "holdout_round1.json")
    if round1:
        failed = [f"{c['name']} {c['result']}" for c in round1["holdout_runs"][0]["checks"] if not c["passed"]]
        lines.append(f"- **Round 1** (Harbor & Pine, Kestrel Aviation, Copperleaf Dental; first run "
                     f"{round1['ran_at'][:10]} UTC): failed {', '.join(failed)}. Four gaps were fixed afterwards, so "
                     f"this set is now development data (Dev 2).")
    round2 = load(HISTORY / "holdout_round2_first_run.json")
    if round2:
        facts = next(c for c in round2["holdout_runs"][0]["checks"] if c["name"] == "Required facts")
        lines.append(f"- **Round 2** (the current held-out set; first run {round2['ran_at'][:10]} UTC): Required facts "
                     f"scored {facts['result']}. Both misses were traced to a labelling error in the golden file "
                     f"(an opportunity count written as live deals only); the label was corrected and no rule was "
                     f"changed. Its other results are the Holdout column above.")
    return lines


def results_markdown() -> str:
    report = load(REPORT)
    if not report:
        raise SystemExit("No eval/last_run.json: run make eval first.")
    q = report["quality"]
    cards = report["runs"] + report.get("holdout_runs", [])
    shown = [d for d in ("dev", "holdout") if d in q["retrieval"]]
    all_sets = [d for d in ("dev", "dev2", "holdout") if d in q["detectors"]]
    parts = [f"Generated by `make results` from the eval run of {report['ran_at'][:16].replace('T', ' ')} UTC "
             f"(`eval/last_run.json`) and `eval/history/`. Do not edit by hand.", "",
             "**Scorecard** (dev: the rules were built on it; dev 2: held-out round 1, now development data; "
             "holdout: never used to change anything)", "", *scorecard(cards), "",
             "**Retrieval**", "", *retrieval(q, shown), "",
             "**Detectors**", "", *detectors(q, all_sets), "",
             "**Router**", "", *router(q), "",
             "**Faithfulness with a real model**", "", *faithfulness(), "",
             "**Held-out history**", "", *history()]
    return "\n".join(parts)


def zero_tolerance_totals(cards: list[dict]) -> tuple[int, int]:
    """(failures, checks) over every zero-tolerance check of every run: "0 (in 12 checks)" -> (0, 12)."""
    failures = checks = 0
    for card in cards:
        for c in card["checks"]:
            if c["zero_tolerance"]:
                bad, _, total = c["result"].partition(" (in ")
                failures, checks = failures + int(bad), checks + int(total.split()[0])
    return failures, checks


def presentation_numbers() -> str:
    """The Key numbers block of a PRESENTATION.md (talk notes, if present in the repo root): the few
    figures the talk quotes, from the same files."""
    report = load(REPORT)
    q, cards = report["quality"], report["runs"] + report.get("holdout_runs", [])
    lines = [f"Written by `make results` from the eval run of {report['ran_at'][:16].replace('T', ' ')} UTC and "
             f"`eval/history/`. Do not edit by hand.", ""]
    for card in cards:
        failed = [f"{c['name']} {c['result']}" for c in card["checks"] if not c["passed"]]
        passed = sum(c["passed"] for c in card["checks"])
        lines.append(f"- **{run_name(card)}, {card['cases']} briefings:** {passed} of {len(card['checks'])} checks pass"
                     + (f"; failing: {', '.join(failed)}." if failed else "."))
    failures, checks = zero_tolerance_totals(cards)
    lines.append(f"- **Zero-tolerance checks** (restricted leaks, injected instructions, red team) across those runs: "
                 f"{failures} failures in {checks} checks.")
    broken = load(HISTORY / "eval_break.json")
    if broken:
        leaks = [f"{NAMES[c['dataset']]} {c2['result']}" for c in broken["runs"] for c2 in c["checks"]
                 if c2["name"] == "Restricted leakage"]
        lines.append(f"- **Break test** (`make eval-break`, access filter switched off, "
                     f"{broken['ran_at'][:10]}): Restricted leakage fails as it must: {', '.join(leaks)}.")
    real = load(HISTORY / "eval_real.json")
    if real:
        card, f = real["cards"][0], real["faithfulness"][0]
        lines.append(f"- **With a real model writing** ({card['models']}): {f['supported']} of {f['claims']} AI claims "
                     f"supported by their sources ({f['faithfulness']:.0%}); {f['first_drafts_rejected']} of "
                     f"{f['llm_sections']} first drafts rejected by the checker; about {card['cost']['requests']:g} "
                     f"AI requests per briefing.")
    round2 = load(HISTORY / "holdout_round2_first_run.json")
    if round2:
        facts = next(c for c in round2["holdout_runs"][0]["checks"] if c["name"] == "Required facts")
        lines.append(f"- **Held-out round 2, first run:** required facts {facts['result']}; both misses were our own "
                     f"answer-key error, corrected without changing any rule.")
    round1 = load(HISTORY / "holdout_round1.json")
    if round1:
        failed = [c["name"].lower() for c in round1["holdout_runs"][0]["checks"] if not c["passed"]]
        lines.append(f"- **Held-out round 1** found gaps in {len(failed)} checks ({', '.join(failed)}); fixed, and that "
                     f"set became practice data.")
    hybrid = {d: q["retrieval"][d]["methods"]["hybrid"]["recall@5"] for d in ("dev", "holdout") if d in q["retrieval"]}
    leaked = sum(q["retrieval"][d]["restricted_retrieved"] for d in q["retrieval"])
    lines.append(f"- **Search** puts, on average, "
                 + " and ".join(f"{v:.0%} ({NAMES[d].lower()})" for d, v in hybrid.items())
                 + f" of the labelled relevant documents in the top 5 (labels written with AI assistance; automated pre-review done, human review pending); "
                   f"restricted documents returned to a user without access: {leaked}.")
    r = q["router"]
    lines.append(f"- **Follow-up routing:** {r['accuracy']:.0%} of {r['questions']} labelled questions go to the right "
                 f"place without the AI tie-breaker.")
    return "\n".join(lines)


def write_between(path: Path, start: str, end: str, body: str) -> None:
    text = path.read_text(encoding="utf-8")
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    path.write_text(f"{before}{start}\n{body}\n{end}{after}", encoding="utf-8", newline="\n")


def main() -> None:
    results = results_markdown()
    write_between(README, START, END, results)
    print(f"Wrote the results section of {README.name} from {REPORT.name} and {HISTORY.name}/.")
    if EVALUATION_DOC.exists():
        write_between(EVALUATION_DOC, START, END, results)
        print(f"Wrote the Current results of docs/{EVALUATION_DOC.name}.")
    if PRESENTATION.exists():
        write_between(PRESENTATION, "<!-- NUMBERS:START -->", "<!-- NUMBERS:END -->", presentation_numbers())
        print(f"Wrote the Key numbers of {PRESENTATION.name}.")


if __name__ == "__main__":
    main()
