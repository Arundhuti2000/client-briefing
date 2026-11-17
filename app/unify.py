"""Unification: entity resolution, dedupe, staleness, conflicts, indexing (SPEC.md section 4).

All rules, no LLM. Every finding becomes a row in data_quality_flags, which the
briefing's "Uncertain, conflicting, or unavailable" section reads directly.

Run order (each step relies on the one before):
  0. Reload briefing.db from data/raw, so running unify twice gives the same result.
  1. Merge duplicate clients (T2), so names of merged records point at the survivor.
  2. Resolve document client_refs (T1, T7, T8) and pipeline client names.
  3. Remove duplicate contacts (T3).
  4. Staleness: superseded metrics, stale statements (T4), overdue actions (T12).
  5. Conflicts: contact roles (T5), commitments vs pipeline (T6).
  6. Chunk approved, resolved documents for search (T11) and embed each chunk.

Run:  make unify   (or: python -m app.unify)
"""

import datetime as dt
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

from app import load_structured, retrieval
from app.ingest import Document, load_documents
from app.wording import (AS_OF_DATE, DOC_NAMES, article, capitalize, day_month, days_before, doc_phrase,  # noqa: F401
                         format_usd, join_words, metric_label, month_of, period_text, plain_words, first_lower)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

RESOLVE_SCORE = 90       # fuzzy score that resolves a name (SPEC section 4)
REVIEW_SCORE = 75        # 75-89 goes to the review queue instead
MENTION_SCORE = 50       # not attached, but close enough to mention on that client's briefing
CLIENT_MERGE_SCORE = 92  # name similarity that marks two client records as duplicates
STALE_AFTER_DAYS = 120
MAX_CHUNK_CHARS = 1000   # longer documents are split by paragraph

LEGAL_SUFFIXES = {"llc", "inc", "ltd", "plc", "corp", "partners",  # abbreviations, and
                  "limited", "incorporated", "corporation"}         # the same words in full
TYPO_TOLERANT_SUFFIXES = {"partners"}  # "limited" is too close to "unlimited" (88), "incorporated" to "corporate" (86)
SUFFIX_TYPO_SCORE = 85   # a last word this close to "partners" is a misspelt suffix
HONORIFICS = {"dr", "mr", "mrs", "ms", "miss", "prof"}
LOST_STAGES = {"Lost"}   # "Won" means the client did commit, so it is not a conflict

# Every table that points at a client; merged clients' rows move to the survivor.
CHILD_TABLES = ["client_aliases", "contacts", "coverage", "revenue_metrics", "holdings", "performance",
                "opportunities", "service_issues", "open_actions"]

UNIFY_SCHEMA = """
CREATE TABLE client_merges (
    survivor_id  TEXT,
    merged_id    TEXT,
    reason       TEXT
);
CREATE TABLE doc_client_map (
    doc_id     TEXT PRIMARY KEY,
    client_id  TEXT NOT NULL,
    method     TEXT,               -- id, exact, fuzzy, text
    score      REAL
);
CREATE TABLE unresolved_refs (
    source_id   TEXT,              -- e.g. DOC:news_005 or SQL:opportunities:OPP-X
    ref_text    TEXT,              -- what the source called the client (NULL if nothing)
    status      TEXT,              -- review, unresolved, ambiguous
    best_match  TEXT,              -- closest client, never used as the answer
    score       REAL
);
CREATE TABLE data_quality_flags (
    flag_id               TEXT PRIMARY KEY,
    client_id             TEXT,
    flag_type             TEXT,
    title                 TEXT,    -- short, for people, e.g. "Who is the CFO?"
    detail                TEXT,    -- one plain sentence or two; numbers and dates formatted by code
    source_ids            TEXT,    -- JSON list of evidence IDs
    severity              TEXT,    -- low, medium, high
    required_entitlement  TEXT,    -- strictest entitlement of the flag's sources
    action                TEXT,    -- conflicts: what to clarify at the meeting (a talking point)
    caveat                TEXT,    -- conflicts: why the document statement is contradicted
    uses                  TEXT     -- conflicts: the source the briefing uses (an evidence ID)
);
CREATE TABLE chunks (
    chunk_id              TEXT PRIMARY KEY,
    doc_id                TEXT,
    client_id             TEXT NOT NULL,
    doc_type              TEXT,
    date                  TEXT,
    required_entitlement  TEXT,
    text                  TEXT,
    source                TEXT     -- e.g. Reuters, crm_notes, email
);
"""

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def words_of(text: str) -> list[str]:
    """Lower case, punctuation and "and" removed, so "&" and "and" read the same:
    'Raj J. Patel' -> ['raj', 'j', 'patel']; 'Harbor and Pine' and 'Harbor & Pine' -> ['harbor', 'pine']"""
    return [w for w in re.sub(r"[^\w\s]", " ", text.lower()).split() if w != "and"]


def is_legal_suffix(word: str) -> bool:
    """A legal suffix, abbreviated or in full ('Ltd' or 'Limited'), or a misspelt 'partners'
    ('prtners' scores 93; real words like 'painters' 75). The others must be exact: a typo of
    'inc' or 'limited' can't be told from a real word."""
    return word in LEGAL_SUFFIXES or (len(word) >= 6 and any(
        fuzz.ratio(word, suffix) >= SUFFIX_TYPO_SCORE for suffix in TYPO_TOLERANT_SUFFIXES))


def normalize(name: str) -> str:
    """'Northwind Capital Partners LLC' -> 'northwind capital'; 'Northwind Cap.' -> 'northwind cap'"""
    words = words_of(name)
    while words and is_legal_suffix(words[-1]):
        words.pop()
    return " ".join(words)


def same_person(a: str, b: str) -> bool:
    """'Raj Patel' = 'RAJ  PATEL' = 'Raj J. Patel' = 'Dr. Raj Patel': case, spacing, middle initials
    and a title in front don't matter. 'R. Patel' is not 'Raj Patel': a first name that is only an
    initial still needs confirming."""
    def key(name: str) -> list[str]:
        words = words_of(name)
        while words and words[0] in HONORIFICS:  # 'dr alan whitfield' -> 'alan whitfield'
            words = words[1:]
        middle = [w for w in words[1:-1] if len(w) > 1]  # drops the 'j' in 'raj j patel'
        return words[:1] + middle + words[1:][-1:]       # first name, middle names, last name
    return key(a) == key(b)


def same_product(on_file: str, said: str) -> bool:
    """'FX Hedging' matches 'fx hedging' and 'FX Hedging program': every word on file is in what was said."""
    return set(words_of(on_file)) <= set(words_of(said))


def strictest(*entitlements: str) -> str:
    """A flag built from a restricted source is itself restricted."""
    return next((e for e in entitlements if e != "standard"), "standard")


def add_flag(conn, client_id, flag_type, severity, title, detail, source_ids, entitlement="standard",
             action=None, caveat=None, uses=None) -> None:
    """Record one finding. Its title and detail are written for people: no IDs, human dates.
    The IDs a reader may want are in source_ids, shown as citation chips."""
    count = conn.execute("SELECT COUNT(*) FROM data_quality_flags").fetchone()[0]
    conn.execute("INSERT INTO data_quality_flags VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (f"F{count + 1:03d}", client_id, flag_type, title, detail, json.dumps(source_ids), severity,
                  entitlement, action, caveat, uses))

# ---------------------------------------------------------------------------
# Step 1: duplicate clients (T2)
# ---------------------------------------------------------------------------


def merge_duplicate_clients(conn) -> None:
    """Same domain, or names >= 92 similar -> merge into the record with the newest updated_at."""
    clients = conn.execute("SELECT * FROM clients ORDER BY updated_at DESC, client_id").fetchall()
    survivors = []
    for client in clients:
        survivor = next((s for s in survivors
                         if s["domain"].lower() == client["domain"].lower()
                         or fuzz.ratio(normalize(s["legal_name"]), normalize(client["legal_name"])) >= CLIENT_MERGE_SCORE),
                        None)
        if survivor is None:
            survivors.append(client)
            continue
        merged_id, survivor_id = client["client_id"], survivor["client_id"]
        reason = "same domain" if survivor["domain"].lower() == client["domain"].lower() else "similar name"
        moved = sum(conn.execute(f"UPDATE {table} SET client_id = ? WHERE client_id = ?",
                                 (survivor_id, merged_id)).rowcount for table in CHILD_TABLES)
        # Keep the old name findable, then drop the duplicate (its raw row stays in stg_crm_clients).
        conn.execute("INSERT INTO client_aliases VALUES (?, ?, ?)",
                     (client["legal_name"], survivor_id, f"merged from {merged_id}"))
        conn.execute("DELETE FROM clients WHERE client_id = ?", (merged_id,))
        conn.execute("INSERT INTO client_merges VALUES (?, ?, ?)", (survivor_id, merged_id, reason))
        why = "shared this client's web domain" if reason == "same domain" else "had a nearly identical name"
        add_flag(conn, survivor_id, "duplicate_client", "low", "Duplicate client record merged",
                 f"An older record for “{client['legal_name']}” (last updated in {month_of(client['updated_at'])}) "
                 f"{why} and was merged into this client, with {moved} related record{'' if moved == 1 else 's'}.",
                 [f"SQL:clients:{merged_id}", f"SQL:clients:{survivor_id}"])

# ---------------------------------------------------------------------------
# Step 2: entity resolution (T1, T7, T8) and pipeline client names
# ---------------------------------------------------------------------------


@dataclass
class Resolution:
    client_id: str | None          # set only when the reference is resolved
    method: str                    # id, exact, fuzzy, text | review, unresolved, ambiguous
    score: float
    best_match: str | None = None  # closest client when unresolved; never used as the answer


class Resolver:
    """Maps an ID, name or alias to a client_id with the rules from SPEC.md section 4, step 1."""

    def __init__(self, names: dict[str, set[str]], ids: dict[str, str]):
        self.names = names  # normalized name or alias -> client_ids
        self.ids = ids      # every known client_id, merged ones too -> surviving client_id

    @classmethod
    def from_db(cls, conn) -> "Resolver":
        ids = {cid: cid for (cid,) in conn.execute("SELECT client_id FROM clients")}
        ids.update({merged: survivor for merged, survivor in
                    conn.execute("SELECT merged_id, survivor_id FROM client_merges")})
        names = {}
        rows = conn.execute("SELECT legal_name, client_id FROM clients "
                            "UNION ALL SELECT alias, client_id FROM client_aliases")
        for name, client_id in rows:
            names.setdefault(normalize(name), set()).add(client_id)
        return cls(names, ids)

    def resolve(self, ref: str) -> Resolution:
        if ref in self.ids:                                     # 1. already a valid ID
            return Resolution(self.ids[ref], "id", 100)
        key = normalize(ref)
        exact = self.names.get(key, set())
        if len(exact) == 1:                                     # 2. exact normalized name or alias
            return Resolution(next(iter(exact)), "exact", 100)
        if len(exact) > 1:
            return Resolution(None, "ambiguous", 100)
        match, score, _ = process.extractOne(key, sorted(self.names), scorer=fuzz.ratio)  # 3. fuzzy
        candidates = self.names[match]
        if score >= RESOLVE_SCORE and len(candidates) == 1:
            return Resolution(next(iter(candidates)), "fuzzy", score)
        status = "review" if score >= REVIEW_SCORE else "unresolved"
        best = min(candidates) if score >= REVIEW_SCORE else self.mentioned(key)
        return Resolution(None, status, score, best_match=best)

    def mentioned(self, key: str) -> str | None:
        """A weak match is shown on the closest client that shares a whole word with it. By letters,
        'Arbor' is closer to 'Harbor & Pine' (62) than to 'Arbor Health' (59), but it means Arbor."""
        sharing = sorted(name for name in self.names if set(key.split()) & set(name.split()))
        if not sharing:
            return None
        match, score, _ = process.extractOne(key, sharing, scorer=fuzz.ratio)
        return min(self.names[match]) if score >= MENTION_SCORE else None

    def find_in_text(self, text: str) -> Resolution:
        """4. No client_ref: look for known names and aliases as whole words in the text."""
        padded = f" {normalize(text)} "
        found = {cid for name, cids in self.names.items() if f" {name} " in padded for cid in cids}
        if len(found) == 1:
            return Resolution(found.pop(), "text", 100)
        return Resolution(None, "ambiguous" if found else "unresolved", 0)


def record_unresolved(conn, source_id, ref_text, r: Resolution, what: str, entitlement: str) -> None:
    """Never attach the source to a client; log it and flag it (on the closest client, if any)."""
    conn.execute("INSERT INTO unresolved_refs VALUES (?, ?, ?, ?, ?)",
                 (source_id, ref_text, r.method, r.best_match, r.score))
    reason = {"review": "needs a human review before it can be matched",
              "unresolved": "couldn't be matched to a client confidently",
              "ambiguous": "matches more than one client"}[r.method]
    named = f"mentions “{ref_text}”" if ref_text else "names no known client"
    add_flag(conn, r.best_match, "unresolved_reference", "medium", "Unmatched reference",
             f"{capitalize(article(what))} {what} {named} but {reason}, so it was not attached to any client.",
             [source_id], entitlement)


def resolve_documents(conn, resolver: Resolver, docs: list[Document]) -> dict[str, str]:
    """Map each document to a client. Returns {doc_id: client_id} for resolved documents only."""
    doc_clients = {}
    for doc in docs:
        r = resolver.resolve(doc.client_ref) if doc.client_ref else resolver.find_in_text(doc.text)
        if r.client_id:
            doc_clients[doc.doc_id] = r.client_id
            conn.execute("INSERT INTO doc_client_map VALUES (?, ?, ?, ?)",
                         (doc.doc_id, r.client_id, r.method, r.score))
        else:
            record_unresolved(conn, f"DOC:{doc.doc_id}", doc.client_ref, r,
                              DOC_NAMES[doc.doc_type], doc.required_entitlement)
    return doc_clients


def resolve_pipeline(conn, resolver: Resolver) -> None:
    """The pipeline export names clients instead of using IDs; fill opportunities.client_id."""
    rows = conn.execute("SELECT o.opp_id, s.client_name, o.required_entitlement FROM opportunities o "
                        "JOIN stg_pipeline_opportunities s ON s.opp_id = o.opp_id ORDER BY o.opp_id").fetchall()
    for opp_id, client_name, entitlement in rows:
        r = resolver.resolve(client_name)
        if r.client_id:
            conn.execute("UPDATE opportunities SET client_id = ? WHERE opp_id = ?", (r.client_id, opp_id))
        else:
            record_unresolved(conn, f"SQL:opportunities:{opp_id}", client_name, r,
                              "pipeline opportunity", entitlement)

# ---------------------------------------------------------------------------
# Step 3: duplicate contacts (T3)
# ---------------------------------------------------------------------------


def dedupe_contacts(conn) -> None:
    """Same client and same email (any letter case), or same name and title -> keep the newest."""
    kept = {}  # match key -> the contact we kept
    for c in conn.execute("SELECT * FROM contacts ORDER BY updated_at DESC, contact_id").fetchall():
        keys = [(c["client_id"], "email", c["email"].lower()),
                (c["client_id"], "name+title", c["name"].lower(), c["title"].lower())]
        original = next((kept[k] for k in keys if k in kept), None)
        if original is None:
            for k in keys:
                kept[k] = c
            continue
        conn.execute("DELETE FROM contacts WHERE contact_id = ?", (c["contact_id"],))
        why = ("the email addresses differed only in capital letters"
               if original["email"].lower() == c["email"].lower() else "both had the same name and title")
        add_flag(conn, c["client_id"], "duplicate_contact", "low", "Duplicate contact removed",
                 f"{c['name']} was listed twice ({why}). Kept the newer record, updated on "
                 f"{day_month(original['updated_at'])}.",
                 [f"SQL:contacts:{original['contact_id']}", f"SQL:contacts:{c['contact_id']}"])

# ---------------------------------------------------------------------------
# Step 4: staleness (T4, T12)
# ---------------------------------------------------------------------------

# Each metric series as (client_id, source table, product, metric, evidence ID, as_of).
# The label people see comes from wording.metric_label, the same rule the tools use.
SERIES_QUERIES = [
    "SELECT client_id, 'revenue_metrics', NULL, 'revenue_usd', "
    "'SQL:revenue_metrics:' || client_id || ':' || period, as_of FROM revenue_metrics",
    "SELECT client_id, 'holdings', product, NULL, "
    "'SQL:holdings:' || client_id || ':' || product || ':' || as_of, as_of FROM holdings",
    "SELECT client_id, 'performance', product, metric, "
    "'SQL:performance:' || client_id || ':' || product || ':' || metric || ':' || period, as_of FROM performance",
]


def stale_as_ofs(as_ofs: list[str], today: dt.date) -> list[str]:
    """The as_of dates that are more than 120 days old AND superseded by a newer value."""
    cutoff = (today - dt.timedelta(days=STALE_AFTER_DAYS)).isoformat()
    latest = max(as_ofs)
    return sorted(a for a in as_ofs if a < cutoff and a < latest)


def flag_stale_metrics(conn, today: dt.date) -> None:
    """One low-severity flag per client listing series whose older values are superseded."""
    series = {}  # (client_id, label) -> [(as_of, evidence_id)]
    for query in SERIES_QUERIES:
        for client_id, source, product, metric, evidence_id, as_of in conn.execute(query):
            label = metric_label(source, product, metric)
            series.setdefault((client_id, label), []).append((as_of, evidence_id))
    per_client = {}  # client_id -> (labels, evidence_ids)
    for (client_id, label), rows in sorted(series.items()):
        old = stale_as_ofs([as_of for as_of, _ in rows], today)
        if old:
            labels, ids = per_client.setdefault(client_id, ([], []))
            labels.append(label)
            ids.extend(evidence_id for as_of, evidence_id in sorted(rows) if as_of in old)
    for client_id, (labels, ids) in per_client.items():
        add_flag(conn, client_id, "stale", "low", "Older values superseded",
                 f"Older values of {join_words([first_lower(label) for label in labels])} are more than "
                 f"{STALE_AFTER_DAYS} days old and were replaced by newer ones; only the latest values are used.", ids)


def flag_stale_statements(conn, docs: list[Document], doc_clients: dict[str, str]) -> None:
    """T4: a revenue figure stated in a document that differs from the latest SQL value."""
    for doc in docs:
        client_id = doc_clients.get(doc.doc_id)
        for claim in doc.claims:
            if client_id is None or claim["type"] != "metric" or claim["metric"] != "revenue_usd":
                continue  # revenue is the only metric claim the prototype checks
            latest = conn.execute("SELECT revenue_usd, period, as_of FROM revenue_metrics "
                                  "WHERE client_id = ? ORDER BY as_of DESC LIMIT 1", (client_id,)).fetchone()
            if latest is None or latest["revenue_usd"] == claim["value"]:
                continue
            now = format_usd(latest["revenue_usd"])
            add_flag(conn, client_id, "stale_statement", "medium", "Revenue figure is out of date",
                     f"{capitalize(doc_phrase(doc.doc_type, doc.date))} said revenue was {format_usd(claim['value'])}, "
                     f"but the latest records say {now} ({period_text(latest['period'])}, as of "
                     f"{day_month(latest['as_of'])}). Using {now}.",
                     [f"DOC:{doc.doc_id}", f"SQL:revenue_metrics:{client_id}:{latest['period']}"],
                     doc.required_entitlement)


def flag_overdue_actions(conn, today: dt.date) -> None:
    """T12: an open action whose due date has passed."""
    rows = conn.execute("SELECT * FROM open_actions WHERE status = 'Open' AND due_date < ? "
                        "ORDER BY due_date, action_id", (today.isoformat(),)).fetchall()
    for a in rows:
        add_flag(conn, a["client_id"], "overdue", "medium", "Overdue action",
                 f"“{a['description']}” (owner {a['owner']}) was due on {day_month(a['due_date'])}, "
                 f"{days_before(a['due_date'], today)} days ago.",
                 [f"SQL:open_actions:{a['action_id']}"])

# ---------------------------------------------------------------------------
# Step 5: conflicts (T5, T6)
# ---------------------------------------------------------------------------


def flag_role_conflicts(conn, docs: list[Document], doc_clients: dict[str, str]) -> None:
    """T5: a document names someone in a role that the contacts table gives to someone else.
    The newer of the two is used. When that is the document, the unified contact list follows it
    (see replace_role_holder), unless the document is restricted: then the contact list everyone
    sees keeps the record. Either way the flag asks the banker to confirm."""
    for doc in docs:
        client_id = doc_clients.get(doc.doc_id)
        for claim in doc.claims:
            if client_id is None or claim["type"] != "contact_role":
                continue
            contact = conn.execute("SELECT * FROM contacts WHERE client_id = ? AND lower(title) = lower(?) "
                                   "ORDER BY updated_at DESC LIMIT 1", (client_id, claim["role"])).fetchone()
            if contact is None or same_person(contact["name"], claim["name"]):
                continue  # nobody holds the role on file, or the document agrees
            role, said_by = claim["role"], doc_phrase(doc.doc_type, doc.date)  # e.g. "a June email"
            updated = month_of(contact["updated_at"])
            record_is_newer = contact["updated_at"] >= doc.date.isoformat()
            use_document = not record_is_newer and doc.required_entitlement == "standard"
            if use_document:
                using = f"Using {claim['name']}, the newer source."
                replace_role_holder(conn, contact, claim["name"], doc)
            elif record_is_newer:
                using = f"Using {contact['name']}, the newer record."
            else:
                using = f"Using {contact['name']} until confirmed."
            add_flag(conn, client_id, "conflict", "high", f"Who is the {role}?",
                     f"{capitalize(said_by)} names {claim['name']}, but the contacts record (updated in {updated}) "
                     f"says {contact['name']}. {using} Confirm at the meeting.",
                     [f"DOC:{doc.doc_id}", f"SQL:contacts:{contact['contact_id']}"],
                     doc.required_entitlement,
                     action=f"Confirm who the {role} is (records say {contact['name']}; {said_by} says {claim['name']}).",
                     caveat=(f"the contacts record (updated in {updated}) says the {role} is {contact['name']}."
                             if record_is_newer else None),
                     uses=f"DOC:{doc.doc_id}" if use_document else f"SQL:contacts:{contact['contact_id']}")


def replace_role_holder(conn, old, name: str, doc: Document) -> None:
    """The document is newer than the contacts record: keep the old holder as 'Former <title>' and
    add the new one, with an ID that says where it came from (e.g. CT201-email_201)."""
    conn.execute("UPDATE contacts SET title = ? WHERE contact_id = ?", (f"Former {old['title']}", old["contact_id"]))
    conn.execute("INSERT INTO contacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (f"{old['contact_id']}-{doc.doc_id}", old["client_id"], name, old["title"], old["relationship_role"],
                  "", doc.date.isoformat(), doc.date.isoformat()))


def flag_commitment_conflicts(conn, docs: list[Document], doc_clients: dict[str, str]) -> None:
    """T6: a document reports a commitment on a product whose opportunity is Lost."""
    for doc in docs:
        client_id = doc_clients.get(doc.doc_id)
        for claim in doc.claims:
            if client_id is None or claim["type"] != "commitment":
                continue
            opps = conn.execute("SELECT * FROM opportunities WHERE client_id = ?", (client_id,)).fetchall()
            matches = [o for o in opps if same_product(o["product"], claim["product"])]
            # The most specific match: 'FX Hedging Advisory' beats 'FX Hedging' for 'FX Hedging Advisory program'
            opp = max(matches, key=lambda o: len(words_of(o["product"])), default=None)
            if opp is None or opp["stage"] not in LOST_STAGES:
                continue
            product, amount = plain_words(claim["product"]), format_usd(claim["amount_usd"])
            marked = f"marked {opp['stage']} in {month_of(opp['updated_at'])}"
            add_flag(conn, client_id, "conflict", "high", f"Is the {product} deal still live?",
                     f"{capitalize(doc_phrase(doc.doc_type, doc.date))} says the client committed to {amount} of "
                     f"{product} by {day_month(claim['due'])}, but the opportunity was {marked}. "
                     f"It is not shown as a live opportunity.",
                     [f"DOC:{doc.doc_id}", f"SQL:opportunities:{opp['opp_id']}"],
                     strictest(doc.required_entitlement, opp["required_entitlement"]),
                     action=f"Ask about the {amount} {product} commitment, since the opportunity was "
                            f"marked {opp['stage']}.",
                     caveat=f"the opportunity was {marked}.", uses=f"SQL:opportunities:{opp['opp_id']}")

# ---------------------------------------------------------------------------
# Step 6: approved sources (T11) and chunks
# ---------------------------------------------------------------------------


def split_into_chunks(text: str) -> list[str]:
    """Short documents are one chunk; long ones are split by paragraph."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def index_chunks(conn, docs: list[Document], doc_clients: dict[str, str]) -> None:
    """Chunk every resolved document, except news from unapproved sources.
    Restricted documents are chunked too: they keep required_entitlement, and
    search filters on it at query time (SPEC section 5)."""
    approved = {name for (name,) in conn.execute("SELECT source_name FROM approved_news_sources")}
    for doc in docs:
        client_id = doc_clients.get(doc.doc_id)
        if client_id is None:
            continue  # unresolved: never attached, never searchable
        if doc.doc_type == "news" and doc.source not in approved:
            # The flag names the source only; it never repeats the unapproved story.
            add_flag(conn, client_id, "excluded_source", "medium", "Unapproved news source",
                     f"A news item from {doc.source}, which is not an approved news source, was left out of "
                     f"the briefing.", [f"DOC:{doc.doc_id}"])
            continue
        for i, text in enumerate(split_into_chunks(doc.text)):
            conn.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (f"{doc.doc_id}#{i}", doc.doc_id, client_id, doc.doc_type, doc.date.isoformat(),
                          doc.required_entitlement, text, doc.source))


def embed_chunks(conn, data_dir: Path) -> None:
    """Embed every chunk once (all-MiniLM-L6-v2) for the vector half of hybrid search."""
    rows = conn.execute("SELECT chunk_id, text FROM chunks ORDER BY chunk_id").fetchall()
    vectors = retrieval.encode([row["text"] for row in rows])
    retrieval.save_embeddings(data_dir, [row["chunk_id"] for row in rows], vectors)

# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def run(data_dir: Path = DATA_DIR, today: dt.date = AS_OF_DATE) -> None:
    """Rebuild briefing.db from data_dir/raw, then apply every unification rule."""
    load_structured.load(data_dir)  # start from the raw files every time, so reruns are identical
    docs = load_documents(data_dir / "raw" / "docs", data_dir / "extracted_claims.json")
    conn = sqlite3.connect(data_dir / "briefing.db")
    conn.row_factory = sqlite3.Row  # rows readable by column name
    try:
        conn.executescript(UNIFY_SCHEMA)
        merge_duplicate_clients(conn)
        resolver = Resolver.from_db(conn)
        doc_clients = resolve_documents(conn, resolver, docs)
        resolve_pipeline(conn, resolver)
        dedupe_contacts(conn)
        flag_stale_metrics(conn, today)
        flag_stale_statements(conn, docs, doc_clients)
        flag_overdue_actions(conn, today)
        flag_role_conflicts(conn, docs, doc_clients)
        flag_commitment_conflicts(conn, docs, doc_clients)
        index_chunks(conn, docs, doc_clients)
        embed_chunks(conn, data_dir)
        conn.commit()
    finally:
        conn.close()


def print_summary(data_dir: Path = DATA_DIR) -> None:
    conn = sqlite3.connect(data_dir / "briefing.db")
    try:
        print(f"Unified {data_dir / 'briefing.db'} (as of {AS_OF_DATE})")
        for survivor, merged, reason in conn.execute("SELECT * FROM client_merges"):
            print(f"  merged client {merged} into {survivor} ({reason})")
        methods = conn.execute("SELECT method, COUNT(*) FROM doc_client_map GROUP BY method ORDER BY method")
        print("  documents resolved: " + ", ".join(f"{n} by {m}" for m, n in methods))
        for source_id, ref, status, best, score in conn.execute("SELECT * FROM unresolved_refs"):
            print(f"  not attached: {source_id} ref={ref!r} status={status} closest={best} score={score:.0f}")
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("clients", "contacts", "chunks", "data_quality_flags")}
        unresolved_opps = conn.execute("SELECT COUNT(*) FROM opportunities WHERE client_id IS NULL").fetchone()[0]
        print(f"  clients {counts['clients']}, contacts {counts['contacts']}, chunks {counts['chunks']} "
              f"(embedded to {data_dir / 'embeddings.npy'}), opportunities without a client {unresolved_opps}")

        print(f"\nData quality flags ({counts['data_quality_flags']}):")
        rows = conn.execute("SELECT flag_id, client_id, severity, title, required_entitlement, detail "
                            "FROM data_quality_flags ORDER BY flag_id")
        for flag_id, client_id, severity, title, entitlement, detail in rows:
            lock = "" if entitlement == "standard" else f" [{entitlement}]"
            print(f"  {flag_id} {client_id or '-':<5} {severity:<7}{title}: {detail}{lock}")
    finally:
        conn.close()


def main() -> None:
    run()
    print_summary()


if __name__ == "__main__":
    main()
