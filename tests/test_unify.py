"""Phase 2 tests for app/unify.py: one test per rule, then one per planted trap."""

import datetime as dt
import json
import sqlite3

import pytest

from app import load_structured, unify
from app.ingest import Document
from data import generate_data as gd

TODAY = dt.date(2026, 11, 18)


def make_resolver():
    """A small resolver: three clients, their aliases, and C014 merged into C001."""
    names = {}
    for client_id, name in [("C001", "Northwind Capital Partners"), ("C001", "NWC"), ("C001", "Northwind Cap."),
                            ("C002", "Helios Energy Group"), ("C002", "Helios"),
                            ("C003", "Arbor Health Systems"), ("C003", "Arbor Health")]:
        names.setdefault(unify.normalize(name), set()).add(client_id)
    return unify.Resolver(names, {"C001": "C001", "C002": "C002", "C003": "C003", "C014": "C001"})


# --- rules ---------------------------------------------------------------------

def test_normalize_strips_case_punctuation_and_legal_suffixes():
    assert unify.normalize("Northwind Capital Partners LLC") == "northwind capital"
    assert unify.normalize("Northwind Cap.") == "northwind cap"
    assert unify.normalize("  HELIOS, Inc ") == "helios"


def test_resolve_by_id_follows_merges():
    r = make_resolver().resolve("C014")
    assert (r.client_id, r.method) == ("C001", "id")


def test_resolve_exact_alias():
    resolver = make_resolver()
    assert resolver.resolve("NWC").client_id == "C001"
    assert resolver.resolve("Northwind Cap.").method == "exact"
    assert resolver.resolve("Northwind Capital Partners LLC").client_id == "C001"  # suffix stripped


@pytest.mark.parametrize("ref, client_id, method, best_match", [
    ("Northwind Capitl", "C001", "fuzzy", None),     # score 97: resolves
    ("Northwnd Cptl", None, "review", "C001"),       # score 87: review queue, not attached
    ("Arbor", None, "unresolved", "C003"),           # score 59: unresolved, mentioned on C003
    ("Zebra Corp", None, "unresolved", None),        # nothing close
])
def test_fuzzy_thresholds(ref, client_id, method, best_match):
    r = make_resolver().resolve(ref)
    assert (r.client_id, r.method, r.best_match) == (client_id, method, best_match)


def test_find_in_text_matches_whole_names_only():
    resolver = make_resolver()
    assert resolver.find_in_text("Helios Energy posts record solar output").client_id == "C002"
    assert resolver.find_in_text("Arbor said it will open three distribution centers").method == "unresolved"
    assert resolver.find_in_text("NWC and Helios signed a deal").method == "ambiguous"


def test_stale_as_ofs_only_flags_old_values_that_are_superseded():
    assert unify.stale_as_ofs(["2026-01-20", "2026-07-17", "2026-10-16"], TODAY) == ["2026-01-20", "2026-07-17"]
    assert unify.stale_as_ofs(["2026-01-20"], TODAY) == []                 # old, but nothing newer
    assert unify.stale_as_ofs(["2026-09-30", "2026-10-16"], TODAY) == []   # newer value, but not old


def test_format_usd():
    assert [unify.format_usd(v) for v in (4200000, 5100000, 50000000, 1200000000, 350000)] == \
        ["$4.2M", "$5.1M", "$50M", "$1.2B", "$350K"]


def test_flags_from_restricted_sources_are_restricted():
    """A conflict built on a restricted opportunity must not leak to users without the entitlement."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(load_structured.SCHEMA + unify.UNIFY_SCHEMA)
    conn.execute("INSERT INTO opportunities VALUES ('OPP-X', 'C001', 'M&A Advisory', 'Lost', 1, 'A', '', "
                 "'2026-10-01', 1, 'restricted_deals')")
    note = Document(doc_id="note_x", doc_type="meeting_note", client_ref="C001", date="2026-09-01",
                    author="A", source="crm_notes", restricted=False, required_entitlement="standard",
                    text="...", claims=[{"type": "commitment", "product": "M&A Advisory",
                                         "amount_usd": 1000000, "due": "2026-12-31"}])
    unify.flag_commitment_conflicts(conn, [note], {"note_x": "C001"})
    assert conn.execute("SELECT required_entitlement FROM data_quality_flags").fetchone()[0] == "restricted_deals"


# --- the planted traps, on the generated data ------------------------------------

@pytest.fixture(scope="module")
def db(unified):
    conn = sqlite3.connect(unified / "briefing.db")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def flags(db, flag_type, client_id=None):
    rows = db.execute("SELECT * FROM data_quality_flags WHERE flag_type = ?", (flag_type,)).fetchall()
    return [dict(r, source_ids=json.loads(r["source_ids"])) for r in rows
            if client_id is None or r["client_id"] == client_id]


def doc_client(db, doc_id):
    row = db.execute("SELECT client_id, method FROM doc_client_map WHERE doc_id = ?", (doc_id,)).fetchone()
    return tuple(row) if row else None


def test_t1_aliases_resolve_to_northwind(db):
    assert doc_client(db, "note_001") == ("C001", "exact")  # "NWC"
    assert doc_client(db, "note_002") == ("C001", "exact")  # "Northwind Cap."


def test_t2_duplicate_client_merged_and_children_follow(db):
    assert [tuple(r) for r in db.execute("SELECT * FROM client_merges")] == [("C001", "C014", "same domain")]
    assert db.execute("SELECT 1 FROM clients WHERE client_id = 'C014'").fetchone() is None
    assert db.execute("SELECT client_id FROM contacts WHERE contact_id = 'CT005'").fetchone()[0] == "C001"
    assert db.execute("SELECT client_id FROM open_actions WHERE action_id = 'A-004'").fetchone()[0] == "C001"
    assert doc_client(db, "email_004") == ("C001", "id")
    assert len(flags(db, "duplicate_client", "C001")) == 1


def test_t3_duplicate_contact_keeps_newest(db):
    rows = db.execute("SELECT contact_id FROM contacts WHERE name = 'Priya Shah'").fetchall()
    assert [r[0] for r in rows] == ["CT003"]
    assert flags(db, "duplicate_contact", "C001")[0]["source_ids"] == ["SQL:contacts:CT003", "SQL:contacts:CT004"]


def test_t4_stale_statement_shows_both_values(db):
    [flag] = flags(db, "stale_statement", "C001")
    assert "$4.2M" in flag["detail"] and "$5.1M" in flag["detail"] and "Using $5.1M" in flag["detail"]
    assert flag["source_ids"] == ["DOC:brief_001", "SQL:revenue_metrics:C001:2026Q3"]


def test_t5_cfo_conflict_prefers_newer_record(db):
    [flag] = [f for f in flags(db, "conflict", "C001") if "DOC:email_001" in f["source_ids"]]
    assert flag["title"] == "Who is the CFO?"
    assert flag["detail"] == ("A June email names Dana Lee, but the contacts record (updated in August) says "
                              "Raj Patel. Using Raj Patel, the newer record. Confirm at the meeting.")
    assert flag["action"] == "Confirm who the CFO is (records say Raj Patel; a June email says Dana Lee)."
    assert flag["severity"] == "high"


def test_t6_commitment_on_lost_opportunity(db):
    [flag] = [f for f in flags(db, "conflict", "C001") if "SQL:opportunities:OPP-NOR-FX" in f["source_ids"]]
    assert "$50M" in flag["detail"] and "Lost" in flag["detail"]


def test_control_claims_that_agree_with_sql_are_not_flagged(db):
    assert flags(db, "conflict", "C002") == []  # note_005: Marcus Webb is CFO; green bond is live


def test_t7_news_without_client_ref_resolved_from_text(db):
    assert doc_client(db, "news_004") == ("C002", "text")


def test_t8_ambiguous_arbor_news_not_attached(db):
    assert doc_client(db, "news_005") is None
    assert db.execute("SELECT 1 FROM chunks WHERE doc_id = 'news_005'").fetchone() is None
    [flag] = flags(db, "unresolved_reference")
    assert flag["client_id"] == "C003" and "not attached" in flag["detail"]
    assert flag["detail"].startswith("A news item mentions “Arbor”")


def test_t9_restricted_records_keep_their_entitlement(db):
    assert db.execute("SELECT client_id FROM opportunities WHERE opp_id = 'OPP-HEL-MA'").fetchone()[0] == "C002"
    assert db.execute("SELECT required_entitlement FROM chunks WHERE doc_id = 'note_004'").fetchone()[0] == \
        "restricted_deals"


def test_t11_unapproved_news_excluded_and_flagged(db):
    assert db.execute("SELECT 1 FROM chunks WHERE doc_id = 'news_003'").fetchone() is None
    [flag] = flags(db, "excluded_source", "C001")
    assert "MarketWhispers Blog" in flag["detail"] and "minority stake" not in flag["detail"]


def test_t12_overdue_action_flagged(db):
    [flag] = flags(db, "overdue")
    assert flag["source_ids"] == ["SQL:open_actions:A-001"] and "due on 31 Oct, 18 days ago" in flag["detail"]


def test_every_pipeline_row_gets_a_client(db):
    assert db.execute("SELECT COUNT(*) FROM opportunities WHERE client_id IS NULL").fetchone()[0] == 0


def test_chunks_cover_resolved_approved_documents_only(db):
    chunked = {r[0] for r in db.execute("SELECT doc_id FROM chunks")}
    assert len(chunked) == 23  # 25 documents minus news_005 (T8) and news_003 (T11)
    assert db.execute("SELECT COUNT(*) FROM chunks WHERE client_id IS NULL").fetchone()[0] == 0


def test_unify_twice_gives_the_same_database(tmp_path):
    # Own folder: the shared fixture's open connection would lock its file on Windows.
    gd.generate(tmp_path)
    dumps = []
    for _ in range(2):
        unify.run(tmp_path)
        conn = sqlite3.connect(tmp_path / "briefing.db")
        dumps.append(list(conn.iterdump()))
        conn.close()
    assert dumps[0] == dumps[1]
