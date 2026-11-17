"""Quality metrics, beside the pass/fail scorecard (docs/EVALUATION.md#quality-metrics): numbers to track,
not gates.

  - retrieval:    Precision@5, Recall@5, MRR and nDCG@5 for BM25 only, vector only and hybrid
                  (RRF), with entitlement filtering on (eval/retrieval_set.yaml, eval/holdout/...).
  - detectors:    200+ generated perturbation cases for entity resolution and for conflict and
                  stale detection, scored with precision, recall and F1, listing every false
                  positive and false negative.
  - router:       accuracy and a confusion table on eval/router_set.yaml.
  - faithfulness: AI-written bullets split into claims, each checked against its cited evidence,
                  and the validator's rejection rate (only meaningful with make eval-real).

All of it runs against whatever database db.DB_PATH points at (dev or holdout).
"""

import datetime as dt
import math
import random
import re
import sqlite3
from collections import Counter
from contextlib import closing

from app import db, router, tools, validate
from app.ingest import Document
from app.judge import claims_of  # the same claims the AI judge labels
from app.retrieval import RRF_K, bm25_ranking, load_embeddings, reciprocal_rank_fusion, vector_ranking
from app.unify import flag_commitment_conflicts, flag_role_conflicts, flag_stale_statements, stale_as_ofs
from app.wording import AS_OF_DATE

K = 5
SEED = 7  # the perturbations are random but repeatable

NOTE = {  # "What this does and doesn't prove", printed and shown on the Evaluations page
    "proves": [
        "On both synthetic datasets the rules resolve aliases, flag the planted conflicts and stale data, never "
        "send restricted records to a user without access, and never repeat planted instructions.",
        "Numbers and citations in the output trace back to SQL and to sources the user may open.",
        "The leakage and injection checks can fail: make eval-break turns the access filter off and they do.",
    ],
    "not_proves": [
        {"title": "Real client data",
         "detail": "Real wording and mess are wider than any generator's."},
        {"title": "Retrieval at scale",
         "detail": "Only a few dozen documents per client, and the relevant-document labels are hand-made and "
                   "need review."},
        {"title": "Quality of AI prose",
         "detail": "Faithfulness here is a word-overlap and number check, not human judgment, and it only runs "
                   "with a real model (make eval-real)."},
        {"title": "Unbiased detector scores",
         "detail": "The misspelt-suffix, middle-initial and extra-product-word rules were added after this report "
                   "found those misses, and both datasets' perturbations come from the same generator, so those "
                   "scores are regression checks, not fresh estimates."},
        {"title": "A blind held-out test",
         "detail": "Both held-out rounds were written by the same person who wrote the rules, so they are not "
                   "blind. Real client data, or a set written by someone else, would be a fairer test."},
        {"title": "Attacks beyond the planted ones",
         "detail": "New phrasings of injected instructions, poisoned numbers and social engineering are untested."},
    ],
}

# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def ranked_docs(chunk_ids: list[str], by_id: dict) -> list[str]:
    """Chunk ranking -> document ranking (first appearance wins)."""
    return list(dict.fromkeys(by_id[cid]["doc_id"] for cid in chunk_ids))


def rank(method: str, candidates: list, query: str, vectors: dict) -> list[str]:
    if method == "bm25":
        return bm25_ranking(candidates, query)
    if method == "vector":
        return vector_ranking(candidates, query, vectors)
    fused = reciprocal_rank_fusion(bm25_ranking(candidates, query), vector_ranking(candidates, query, vectors))
    by_id = {c["chunk_id"]: c for c in candidates}
    return sorted(fused, key=lambda cid: (fused[cid], by_id[cid]["date"], cid), reverse=True)


def ndcg(ranking: list[str], relevant: set[str], k: int = K) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, doc in enumerate(ranking[:k]) if doc in relevant)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return dcg / ideal if ideal else 0.0


def retrieval_metrics(questions: list[dict]) -> dict:
    """Mean P@5, R@5, MRR and nDCG@5 per method; and how often a restricted document reached a
    user without access (must be 0: candidates are filtered before ranking)."""
    scores = {m: Counter() for m in ("bm25", "vector", "hybrid")}
    restricted_retrieved, scored = 0, 0
    with closing(db.connect()) as conn:
        vectors = load_embeddings(db.DB_PATH.parent)
        for q in questions:
            user = tools.load_user(q.get("user", "u2"))
            candidates = db.visible_chunks(conn, q["client"], user.entitlements)
            by_id = {c["chunk_id"]: c for c in candidates}
            relevant = set(q["relevant"])
            restricted_retrieved += sum(1 for c in candidates if c["required_entitlement"] not in user.entitlements)
            if not relevant:
                continue  # a "nothing should be found" case: only the restricted check applies
            scored += 1
            for method, s in scores.items():
                docs = ranked_docs(rank(method, candidates, q["question"], vectors), by_id)
                hits = [d for d in docs[:K] if d in relevant]
                first = next((i for i, d in enumerate(docs, start=1) if d in relevant), None)
                s.update({"precision@5": len(hits) / K, "recall@5": len(hits) / len(relevant),
                          "mrr": 1 / first if first else 0.0, "ndcg@5": ndcg(docs, relevant)})
    methods = {m: {name: round(total / max(scored, 1), 3) for name, total in s.items()} for m, s in scores.items()}
    return {"questions": len(questions), "scored": scored, "methods": methods,
            "restricted_retrieved": restricted_retrieved, "rrf_k": RRF_K}

# ---------------------------------------------------------------------------
# Detectors: generated perturbation cases
# ---------------------------------------------------------------------------


class Tally:
    """Confusion counts for one detector, with the mistakes written out."""

    def __init__(self):
        self.cases = self.tp = self.fp = self.fn = self.tn = 0
        self.false_positives, self.false_negatives = [], []

    def add(self, expected: bool, predicted: bool, case: str, correct: bool = True) -> None:
        self.cases += 1
        if expected and predicted and correct:
            self.tp += 1
        elif predicted and (not expected or not correct):
            self.fp += 1
            self.false_positives.append(case)
            if expected:  # flagged, but the wrong answer: also a miss
                self.fn += 1
                self.false_negatives.append(case)
        elif expected:
            self.fn += 1
            self.false_negatives.append(case)
        else:
            self.tn += 1

    def report(self) -> dict:
        precision = self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0
        recall = self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {"cases": self.cases,
                "tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn,
                "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3),
                "false_positives": self.false_positives, "false_negatives": self.false_negatives}


def typos(name: str, rng: random.Random) -> list[str]:
    """A deleted, a swapped and a replaced letter, away from the first letter."""
    if len(name) < 8:
        return []
    i = rng.randrange(2, len(name) - 2)
    swapped = name[:i] + name[i + 1] + name[i] + name[i + 2:]
    replaced = name[:i] + ("e" if name[i] != "e" else "a") + name[i + 1:]
    return [name[:i] + name[i + 1:], swapped, replaced]


def entity_resolution(conn, rng: random.Random) -> Tally:
    """Every name and alias, in variants that must resolve; and look-alikes that must not."""
    resolver = router_free_resolver(conn)
    tally = Tally()
    names = conn.execute("SELECT legal_name AS name, client_id FROM clients "
                         "UNION SELECT alias, client_id FROM client_aliases").fetchall()
    for name, client_id in names:
        variants = [name, name.lower(), name.upper(), f"{name} LLC", f"{name}, Inc.", f"{name}.", f"  {name}  ",
                    *typos(name, rng)]
        for variant in dict.fromkeys(variants):
            got = resolver.resolve(variant).client_id
            tally.add(True, got is not None, f"'{variant}' -> {got} (expected {client_id})", correct=got == client_id)
    for legal_name, in conn.execute("SELECT legal_name FROM clients"):
        first = legal_name.split()[0]
        for look_alike in (f"{first} Mining", f"{first} Foods", f"{first} Media Group", f"Grand {legal_name.split()[-1]}"):
            got = resolver.resolve(look_alike).client_id
            tally.add(False, got is not None, f"'{look_alike}' -> {got} (expected no client)")
    return tally


def router_free_resolver(conn):
    from app.unify import Resolver  # the same rules as unify and the resolve_client tool
    return Resolver.from_db(conn)


def detector_db(conn) -> sqlite3.Connection:
    """An in-memory copy of the database, so the detectors can run case by case."""
    memory = sqlite3.connect(":memory:")
    conn.backup(memory)
    memory.row_factory = sqlite3.Row
    return memory


def flagged(memory, detector, client_id: str, claims: list[dict], doc_type: str = "email") -> bool:
    """Run one case. Detectors may update the data (a newer document replaces a contact), so every
    case starts from the same data: the changes are rolled back afterwards."""
    memory.execute("SAVEPOINT probe")
    try:
        memory.execute("DELETE FROM data_quality_flags")
        doc = Document(doc_id="probe_1", doc_type=doc_type, client_ref=client_id, date=dt.date(2026, 6, 1),
                       author="probe", source="email", restricted=False, required_entitlement="standard",
                       text="probe", claims=claims)
        detector(memory, [doc], {"probe_1": client_id})
        return memory.execute("SELECT COUNT(*) FROM data_quality_flags").fetchone()[0] > 0
    finally:
        memory.execute("ROLLBACK TO probe")
        memory.execute("RELEASE probe")


def role_conflicts(memory) -> Tally:
    """A different person in a role on file is a conflict; the same person written differently is not."""
    tally = Tally()
    for client_id, name, title in memory.execute("SELECT client_id, name, title FROM contacts").fetchall():
        first, *rest = name.split()
        cases = [(f"{title}: Jordan Blake", True, {"role": title, "name": "Jordan Blake"}),
                 (f"{title}: {name.upper()} (same person, capitals)", False, {"role": title, "name": name.upper()}),
                 (f"{title.lower()}: {name} (role in lower case)", False, {"role": title.lower(), "name": name}),
                 (f"{title}: {first}  {' '.join(rest)} (same person, double space)", False,
                  {"role": title, "name": f"{first}  {' '.join(rest)}"}),
                 (f"{title}: {first} J. {' '.join(rest)} (same person, middle initial)", False,
                  {"role": title, "name": f"{first} J. {' '.join(rest)}"}),
                 (f"Chief Risk Officer: {name} (no such role on file)", False, {"role": "Chief Risk Officer", "name": name})]
        for case, expected, claim in cases:
            got = flagged(memory, flag_role_conflicts, client_id, [{"type": "contact_role", **claim}])
            tally.add(expected, got, f"{client_id} {case}")
    return tally


def commitment_conflicts(memory) -> Tally:
    """A commitment on a Lost opportunity is a conflict; on a live or won one it is not."""
    tally = Tally()
    # Only deals every user may see: the report (and its list of mistakes) is shown to everyone
    rows = memory.execute("SELECT client_id, product, stage FROM opportunities "
                          "WHERE required_entitlement = 'standard'").fetchall()
    for client_id, product, stage in rows:
        lost = stage == "Lost"
        cases = [(product, lost), (product.lower(), lost), (f"{product} program", lost),
                 ("Space Insurance", False)]
        for name, expected in cases:
            claim = {"type": "commitment", "product": name, "amount_usd": 10_000_000, "due": "2026-12-31"}
            got = flagged(memory, flag_commitment_conflicts, client_id, [claim], doc_type="meeting_note")
            tally.add(expected, got, f"{client_id} commitment on '{name}' (opportunity {stage})")
    return tally


def stale_statements(memory) -> Tally:
    """A revenue figure that differs from the latest is stale; the latest figure itself is not."""
    tally = Tally()
    clients = [r[0] for r in memory.execute("SELECT DISTINCT client_id FROM revenue_metrics")]
    for client_id in clients:
        values = [r[0] for r in memory.execute(
            "SELECT revenue_usd FROM revenue_metrics WHERE client_id = ? ORDER BY as_of", (client_id,))]
        latest, older = values[-1], values[:-1]
        cases = [(latest, True, "revenue_usd", False), (latest * 0.5, True, "revenue_usd", True),
                 (latest, False, "wallet_share_pct", False)]
        cases += [(v, True, "revenue_usd", v != latest) for v in older[:2]]
        for value, _, metric, expected in cases:
            claim = {"type": "metric", "metric": metric, "value": value}
            got = flagged(memory, flag_stale_statements, client_id, [claim], doc_type="prior_briefing")
            tally.add(expected, got, f"{client_id} document says {metric} = {value:,.0f} (latest {latest:,.0f})")
    return tally


def stale_metrics() -> Tally:
    """Older than 120 days AND superseded by a newer value: stale. Boundary days included."""
    tally = Tally()
    for days in (10, 60, 100, 119, 120, 121, 150, 200, 365, 730):
        old = (AS_OF_DATE - dt.timedelta(days=days)).isoformat()
        newer = (AS_OF_DATE - dt.timedelta(days=5)).isoformat()
        for series, label in (([old, newer], "with a newer value"), ([old], "the only value")):
            got = old in stale_as_ofs(series, AS_OF_DATE)
            tally.add(days > 120 and len(series) > 1, got, f"value {days} days old, {label}")
    for a, b in ((400, 300), (300, 200), (200, 125)):  # two old values: only the older one is superseded
        older, newer = [(AS_OF_DATE - dt.timedelta(days=d)).isoformat() for d in (a, b)]
        found = stale_as_ofs([older, newer], AS_OF_DATE)
        tally.add(True, older in found, f"{a}-day value with a {b}-day value after it")
        tally.add(False, newer in found, f"{b}-day value that is the latest")
    return tally


def detector_metrics() -> dict:
    rng = random.Random(SEED)
    with closing(db.connect()) as conn:
        memory = detector_db(conn)
        tallies = {"Entity resolution": entity_resolution(conn, rng), "Role conflicts": role_conflicts(memory),
                   "Commitment conflicts": commitment_conflicts(memory), "Stale statements": stale_statements(memory),
                   "Stale metrics": stale_metrics()}
    reports = {name: t.report() for name, t in tallies.items()}
    return {"cases": sum(r["cases"] for r in reports.values()), "detectors": reports}

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def router_metrics(questions: list[dict]) -> dict:
    confusion, misroutes = Counter(), []
    for q in questions:
        decision = router.route(q["question"])
        confusion[(q["expect"], decision.route.name)] += 1
        if decision.route.name != q["expect"]:
            misroutes.append(f"'{q['question']}' -> {decision.route.name} by {decision.method} (expected {q['expect']})")
    correct = sum(n for (expected, got), n in confusion.items() if expected == got)
    routes = [r.name for r in router.ROUTES]
    return {"questions": len(questions), "accuracy": round(correct / max(len(questions), 1), 3), "routes": routes,
            "confusion": [[confusion[(expected, got)] for got in routes] for expected in routes],
            "misroutes": misroutes}

# ---------------------------------------------------------------------------
# Faithfulness of AI-written bullets
# ---------------------------------------------------------------------------

STOPWORDS = {"the", "and", "for", "with", "that", "this", "from", "their", "they", "have", "has", "was", "were",
             "will", "would", "about", "since", "into", "client", "said", "says", "asked"}


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9$%.]+", text.lower()) if len(w) > 3 and w not in STOPWORDS}


def claim_supported(claim: str, cited: list) -> tuple[bool, float]:
    """The word-overlap check for one claim: its numbers and dates are in the cited evidence and
    at least half of its content words are there. Returns (supported, overlap)."""
    words = content_words(claim)
    evidence_words = content_words(" ".join(e.text for e in cited))
    bad_dates, bad_numbers = validate.unsupported_facts(claim, cited)
    overlap = len(words & evidence_words) / len(words) if words else 1.0
    return not bad_dates and not bad_numbers and overlap >= 0.5, overlap


def faithfulness(briefings: list) -> dict:
    """Each claim in an AI-written bullet must have its numbers and dates in the cited evidence and
    at least half of its content words there. Template and code sections are not counted."""
    total, supported, examples = 0, 0, []
    drafted = rejected = 0
    for b in briefings:
        for s in b.sections:
            if s.author in ("ai", "evidence") or s.retry_errors:
                drafted += 1
                rejected += bool(s.retry_errors)
            if s.author != "ai":
                continue
            for bullet in s.bullets:
                cited = [b.evidence[c] for c in bullet.citations if c in b.evidence]
                for claim in claims_of(bullet.text):
                    ok, overlap = claim_supported(claim, cited)
                    total += 1
                    supported += ok
                    if not ok and len(examples) < 8:
                        examples.append(f"{s.id}: '{claim}' (overlap {overlap:.0%})")
    return {"claims": total, "supported": supported,
            "faithfulness": round(supported / total, 3) if total else None,
            "llm_sections": drafted, "first_drafts_rejected": rejected,
            "rejection_rate": round(rejected / drafted, 3) if drafted else None, "unsupported": examples}
