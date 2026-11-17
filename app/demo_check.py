"""`make demo-check`: replay the demo's AI paths from the cache and print PASS or FAIL per path.

The live demo (README, "Demo in 2 minutes") should never depend on a free-tier model being up or
spend a request, so its AI answers are generated once with a real model and cached:
  briefings:  Northwind as Sam, Helios as Alex, Helios as Sam
  follow-ups: three questions on Northwind as Sam (DEMO_QUESTIONS)

  python -m app.demo_check --generate   once, with the real chain in .env; cap it with LLM_REQUEST_BUDGET
  make demo-check                       replay only: CACHE_REPLAY=any and a budget of 0 requests

A path passes when its AI-written parts came from a real model and no request was sent. Paths
answered by code (numbers and records) pass when they are answered. Uses the app's data/briefing.db.
"""

import argparse
import os
import sys

from app import ask, llm, tools
from app.orchestrator import build_briefing

DEMO_BRIEFINGS = [("u2", "C001", "Northwind as Sam"), ("u1", "C002", "Helios as Alex"), ("u2", "C002", "Helios as Sam")]
DEMO_QUESTIONS = ["What did Priya ask about the credit facility?", "Why did deposits go up?",
                  "Is the FX hedging deal still live?"]
NOT_A_MODEL = {"mock", "none", None}


def briefing_path(user_id: str, client_id: str, replay: bool) -> tuple[bool, str]:
    before = llm.REQUESTS_SENT[0]
    b = build_briefing(tools.load_user(user_id), client_id)
    sent = llm.REQUESTS_SENT[0] - before
    written = [s for s in b.sections if s.author != "code"]  # the sections a model is asked to write
    by_model = [s for s in written if s.author == "ai"]
    models = sorted({f"{r.model}{' (cached)' if r.cached else ''}" for r in b.llm_runs if r.provider not in NOT_A_MODEL})
    ok = bool(written) and len(by_model) == len(written)
    if replay:  # the demo must replay: every model answer from the cache, no request sent
        ok = ok and sent == 0 and all(r.cached for r in b.llm_runs if r.provider not in NOT_A_MODEL)
    return ok, f"{len(by_model)} of {len(written)} sections by {', '.join(models) or 'no model'}; {sent} requests sent"


def question_path(question: str, replay: bool) -> tuple[bool, str]:
    before = llm.REQUESTS_SENT[0]
    a = ask.answer(tools.load_user("u2"), "C001", question)
    sent = llm.REQUESTS_SENT[0] - before
    by_model = a.answered_by == "ai" and a.provider not in NOT_A_MODEL
    ok = a.status == "answered" and (a.answered_by == "code" or by_model) and not (replay and sent)
    who = f"{a.provider}: {a.model}" if by_model else a.answered_by
    return ok, f"route {a.route} ({a.method}), {a.status}, written by {who}; {sent} requests sent"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or replay the demo's cached AI answers.")
    parser.add_argument("--generate", action="store_true", help="call the real chain for anything not cached yet")
    args = parser.parse_args()
    if not args.generate:  # replay only: any request would be refused, so a cache miss shows as FAIL
        os.environ["CACHE_REPLAY"] = "any"
        os.environ["LLM_REQUEST_BUDGET"] = "0"
    print(f"{'Generating' if args.generate else 'Replaying'} the demo paths (LLM_CHAIN: {','.join(llm.llm_chain())})")
    replay = not args.generate
    results = [(f"briefing: {name}", *briefing_path(user_id, client_id, replay)) for user_id, client_id, name in DEMO_BRIEFINGS]
    results += [(f"ask (Northwind as Sam): {q}", *question_path(q, replay)) for q in DEMO_QUESTIONS]
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}\n        {detail}")
    print(f"Real requests sent: {llm.REQUESTS_SENT[0]}")
    if not all(ok for _, ok, _ in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
