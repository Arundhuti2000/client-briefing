"""`make eval-judge`: the AI judge (app/judge.py) on the dev golden cases, compared claim by claim
with the word-overlap check (docs/EVALUATION.md#llm-as-judge). A metric to track, not a gate.

For each dev golden case the briefing is built with LLM_CHAIN (with CACHE_REPLAY=any it comes from
the cache at no cost), then a judge model (JUDGE_CHAIN) labels every claim in its AI-written
bullets supported, unsupported or contradicted. Code counts the labels, computes the rates and
compares each label with eval/quality.py's word-overlap answer for the same claim.

Saves counts only to eval/history/judge.json: claim text and the judge's reasons can come from
restricted briefings, so they are printed in the terminal and never saved.
Run:  make eval-judge
"""

import datetime as dt
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

import yaml

from app import judge, llm, tools
from app.orchestrator import build_briefing
from eval import quality, run_eval

JUDGE_HISTORY = run_eval.EVAL_DIR / "history" / "judge.json"


def report(judged: list[tuple]) -> dict:
    """Counts and rates, all computed here, from (briefing, claims, completion) per briefing."""
    claims = [c for _, cs, _ in judged for c in cs]
    overlap = {id(c): quality.claim_supported(c.text, c.cited)[0] for c in claims}  # the word-overlap answer
    answered = [c for c in claims if c.verdict != judge.NO_VERDICT]
    verdicts = Counter(c.verdict for c in claims)
    table = Counter((c.verdict == "supported", overlap[id(c)]) for c in answered)  # (judge, overlap)
    completions = [x for _, _, x in judged if x is not None]
    judge_models = {x.model for x in completions if x.data is not None}
    writer_models = {s.written_by for b, _, _ in judged for s in b.sections if s.author == "ai"}
    return {
        "judges": sorted({f"{x.provider}: {x.model}" for x in completions if x.data is not None}),
        "writers": sorted(writer_models),
        "self_judged": bool(judge_models & writer_models),
        "briefings": len(completions),
        "claims": len(claims),
        "verdicts": {v: verdicts[v] for v in (*judge.VERDICTS, judge.NO_VERDICT)},
        "judge_faithfulness": round(verdicts["supported"] / len(answered), 3) if answered else None,
        "agreement_with_overlap": round((table[True, True] + table[False, False]) / len(answered), 3) if answered else None,
        "both_supported": table[True, True],
        "both_unsupported": table[False, False],
        "judge_only_unsupported": table[False, True],    # the overlap check passed it, the judge didn't
        "overlap_only_unsupported": table[True, False],  # e.g. a paraphrase the overlap check missed
        "requests": sum(x.requests for x in completions),
        "cache_hits": sum(x.cached for x in completions),
        # Claim text and reasons can come from restricted briefings: shown in the terminal, never saved
        "flagged": [f"{c.section}: {c.verdict}: '{c.text}' ({c.reason})"
                    for c in answered if c.verdict != "supported"],
        "disagreements": [f"{c.section}: judge {c.verdict}, overlap {'supported' if overlap[id(c)] else 'unsupported'}: "
                          f"'{c.text}'" for c in answered if (c.verdict == "supported") != overlap[id(c)]],
    }


def print_report(r: dict) -> None:
    print(f"\nLLM as judge: judged by {', '.join(r['judges']) or 'nobody (no judge answered)'}; "
          f"written by {', '.join(r['writers']) or 'nobody'}")
    if r["self_judged"]:
        print("  Note: the judge is the same model as the writer; set JUDGE_CHAIN to another provider for a fairer check.")
    v = r["verdicts"]
    print(f"  Claims: {r['claims']} in {r['briefings']} briefings; without a valid verdict: {v[judge.NO_VERDICT]}")
    print(f"  Verdicts: supported {v['supported']}, unsupported {v['unsupported']}, contradicted {v['contradicted']}")
    if r["judge_faithfulness"] is not None:
        print(f"  Judge faithfulness: {r['judge_faithfulness']:.0%} of judged claims supported")
        print(f"  Agreement with the word-overlap check: {r['agreement_with_overlap']:.0%} "
              f"(both supported {r['both_supported']}, both unsupported {r['both_unsupported']}, "
              f"judge only {r['judge_only_unsupported']}, overlap only {r['overlap_only_unsupported']})")
    for line in r["flagged"][:10]:
        print(f"      flagged: {line}")
    for line in r["disagreements"][:10]:
        print(f"      disagree: {line}")
    print(f"  Judge requests: {r['requests']}; cache hits: {r['cache_hits']}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    chain = judge.judge_chain()
    if not chain:
        raise SystemExit("No judge: JUDGE_CHAIN (or LLM_CHAIN) lists no real provider, and the template can't judge.")
    golden = yaml.safe_load(run_eval.GOLDEN_PATH.read_text(encoding="utf-8"))
    judged = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        print(f"Building a fresh copy of the dev data in {tmp} ...")
        run_eval.build_fresh_data(Path(tmp), "dev")
        for case in golden["cases"]:
            briefing = build_briefing(tools.load_user(case["user"]), case["client"])
            claims = judge.claims_to_judge(briefing)
            completion = judge.judge_claims(claims, chain)
            judged.append((briefing, claims, completion))
            who = f"{completion.provider}: {completion.model}" if completion else "no AI-written claims"
            print(f"  {case['client']}/{case['user']}: {len(claims)} claims ({who})")
    result = report(judged)
    print_report(result)
    if not result["claims"]:
        print("\nNothing to judge: the briefings have no AI-written text. Set a real LLM_CHAIN "
              "(cached answers are free with CACHE_REPLAY=any).")
        return
    saved = {k: v for k, v in result.items() if k not in ("flagged", "disagreements")}  # counts only
    ran_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    JUDGE_HISTORY.write_text(json.dumps({"ran_at": ran_at, "judge_chain": chain} | saved, indent=2) + "\n",
                             encoding="utf-8")
    print(f"\nSaved the counts to eval/history/{JUDGE_HISTORY.name}.")
    print(f"Real LLM requests sent by this run: {llm.REQUESTS_SENT[0]}")


if __name__ == "__main__":
    main()
