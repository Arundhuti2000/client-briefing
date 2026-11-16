"""Phase 3 tests for app/tools.py: contracts, entitlement filtering, typed errors, audit."""

import datetime as dt
import json
import sqlite3

import pytest

from app import audit, db, tools

SINCE_LAST_INTERACTION = dt.date(2026, 9, 15)

# Anything that would reveal the Helios deal (T9) to someone without restricted_deals
RESTRICTED_MARKERS = ["OPP-HEL-MA", "note_004", "acquisition", "Project Sunrise", "SunPeak", "M&A"]
PROBING_QUERIES = ["acquisition", "Project Sunrise", "M&A advisory engagement letter", "valuation materials",
                   "Marcus Webb board interest", ""]


@pytest.fixture(autouse=True)
def use_unified_db(unified, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", unified / "briefing.db")


@pytest.fixture
def alex(use_unified_db):
    return tools.load_user("u1")


@pytest.fixture
def sam(use_unified_db):
    return tools.load_user("u2")


def ids(result):
    return [fact.evidence_id for fact in result.facts]


def every_result_for(user):
    """Call every tool for every client, including searches aimed at the restricted deal."""
    results = []
    for client_id in ("C001", "C002", "C003"):
        results += [tools.get_client_profile(user, client_id=client_id),
                    tools.get_metrics(user, client_id=client_id, since=dt.date(2026, 1, 1)),
                    tools.get_opportunities(user, client_id=client_id),
                    tools.get_open_items(user, client_id=client_id),
                    tools.get_news(user, client_id=client_id),
                    tools.get_data_quality_flags(user, client_id=client_id)]
        for query in PROBING_QUERIES:
            results.append(tools.search_documents(user, client_id=client_id, query=query, top_k=20))
            results.append(tools.search_documents(user, client_id=client_id, query=query,
                                                  doc_types=["meeting_note"], top_k=20))
    for name in ("Helios", "HEG", "Project Sunrise", "SunPeak Renewables"):
        results.append(tools.resolve_client(user, name_or_alias=name))
    return results


# --- T9: restricted data -------------------------------------------------------

def test_sam_can_never_see_restricted_records(sam):
    assert sam.entitlements == ["standard"]
    everything = json.dumps([r.model_dump(mode="json") for r in every_result_for(sam)])
    for marker in RESTRICTED_MARKERS:
        assert marker not in everything, marker


def test_sam_sees_no_trace_in_counts(sam):
    assert ids(tools.get_opportunities(sam, client_id="C002")) == ["SQL:opportunities:OPP-HEL-GB"]
    notes = tools.search_documents(sam, client_id="C002", query="", doc_types=["meeting_note"], top_k=20)
    assert ids(notes) == ["DOC:note_005"]


def test_alex_does_see_restricted_records(alex):
    """Positive control: proves the leakage test above would catch a leak."""
    everything = json.dumps([r.model_dump(mode="json") for r in every_result_for(alex)])
    for marker in ("OPP-HEL-MA", "note_004", "acquisition", "Project Sunrise"):
        assert marker in everything, marker


def test_users_and_entitlements_come_from_the_database(alex):
    assert alex.entitlements == ["standard", "restricted_deals"]
    assert tools.load_user("nobody") is None


# --- each tool --------------------------------------------------------------------

@pytest.mark.parametrize("name, client_id", [
    ("NWC", "C001"), ("Northwind Cap.", "C001"), ("C014", "C001"), ("Helios Energy Group", "C002"),
])
def test_resolve_client(sam, name, client_id):
    result = tools.resolve_client(sam, name_or_alias=name)
    assert result.ok and result.facts[0].details["client_id"] == client_id


@pytest.mark.parametrize("name, error, candidates", [
    ("Arbor", "client_not_found", ["C003"]),        # T8: too weak to resolve; offered as "did you mean"
    ("Northwnd Cptl", "ambiguous_client", ["C001"]),  # review band
    ("", "invalid_input", []),
])
def test_resolve_client_errors(sam, name, error, candidates):
    result = tools.resolve_client(sam, name_or_alias=name)
    assert (result.ok, result.error, result.candidates, result.facts) == (False, error, candidates, [])


def test_client_profile_reflects_unification(sam):
    profile = tools.get_client_profile(sam, client_id="C001")
    assert profile.facts[0].value == "Northwind Capital Partners"
    contacts = [f.evidence_id for f in profile.facts if f.source == "contacts"]
    assert "SQL:contacts:CT005" in contacts       # T2: moved from C014
    assert "SQL:contacts:CT004" not in contacts   # T3: duplicate removed
    cfo = next(f for f in profile.facts if f.label == "CFO")
    assert cfo.value == "Raj Patel"               # T5: the newer record


def test_metrics_include_change_since_last_interaction(sam):
    result = tools.get_metrics(sam, client_id="C001", since=SINCE_LAST_INTERACTION)
    facts = {(f.evidence_id, f.label): f for f in result.facts}
    revenue = facts[("SQL:revenue_metrics:C001:2026Q3", "Revenue")]
    assert revenue.value == 5100000 and revenue.details["change"] == 300000
    baseline = facts[("SQL:revenue_metrics:C001:2026Q2", "Revenue at last interaction")]
    assert baseline.value == 4800000
    wallet = facts[("SQL:revenue_metrics:C001:2026Q3", "Wallet share")]
    assert wallet.details == {"unit": "pct", "period": "2026Q3", "role": "latest", "change": 0.8,
                              "baseline_evidence_id": "SQL:revenue_metrics:C001:2026Q2"}


def test_opportunities_carry_stage_for_ranking(sam):
    facts = tools.get_opportunities(sam, client_id="C001").facts
    assert {f.details["opp_id"]: f.details["stage"] for f in facts} == \
        {"OPP-NOR-CF": "Discovery", "OPP-NOR-FX": "Lost", "OPP-NOR-TM": "Proposal"}


def test_open_items_mark_overdue_and_follow_the_merge(sam):
    facts = {f.evidence_id: f for f in tools.get_open_items(sam, client_id="C001").facts}
    assert facts["SQL:open_actions:A-001"].details["overdue"] is True    # T12
    assert facts["SQL:open_actions:A-002"].details["overdue"] is False
    assert "SQL:open_actions:A-004" in facts                              # T2: moved from C014
    assert facts["SQL:service_issues:SI-002"].details["status"] == "Closed"


def test_search_ranks_and_filters(sam):
    assert ids(tools.search_documents(sam, client_id="C001", query="liquidity analysis"))[0] == "DOC:note_001"
    emails = tools.search_documents(sam, client_id="C001", query="credit facility", doc_types=["email"])
    assert emails.facts and all(f.details["doc_type"] == "email" for f in emails.facts)
    recent = tools.search_documents(sam, client_id="C001", query="", since=dt.date(2026, 10, 1), top_k=20)
    assert recent.facts and all(f.as_of >= dt.date(2026, 10, 1) for f in recent.facts)
    nothing = tools.search_documents(sam, client_id="C001", query="zebra")
    assert nothing.ok and nothing.facts == []


def test_news_is_recent_and_approved_only(sam):
    news = tools.get_news(sam, client_id="C001", since=SINCE_LAST_INTERACTION)
    assert sorted(ids(news)) == ["DOC:news_001", "DOC:news_002"]  # news_003 (T11) was never indexed
    assert {f.source for f in news.facts} == {"Reuters", "Bloomberg"}


def test_data_quality_flags(sam):
    flags = tools.get_data_quality_flags(sam, client_id="C001").facts
    assert {"stale_statement", "conflict", "overdue", "excluded_source"} <= {f.label for f in flags}
    assert all(f.evidence_id.startswith("FLAG:") for f in flags)


def test_evidence_ids_are_stable(sam):
    first = ids(tools.get_metrics(sam, client_id="C001", since=SINCE_LAST_INTERACTION))
    assert first == ids(tools.get_metrics(sam, client_id="C001", since=SINCE_LAST_INTERACTION))

# --- typed errors, read-only, audit --------------------------------------------------


@pytest.mark.parametrize("call, error", [
    (lambda u: tools.get_opportunities(u, client_id="X1"), "invalid_input"),        # bad ID format
    (lambda u: tools.get_opportunities(u, client_id="C999"), "client_not_found"),
    (lambda u: tools.get_metrics(u, client="C001", since="2026-09-15"), "invalid_input"),  # misspelled argument
    (lambda u: tools.search_documents(u, client_id="C001", query="x", doc_types=["tweet"]), "invalid_input"),
])
def test_bad_calls_return_typed_errors(sam, call, error):
    result = call(sam)
    assert (result.ok, result.error, result.facts) == (False, error, [])


def test_missing_database_is_an_error_not_an_exception(sam, monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "missing.db")
    result = tools.get_opportunities(sam, client_id="C001")
    assert (result.ok, result.error) == (False, "data_unavailable")
    assert not (tmp_path / "missing.db").exists()  # neither the tool nor the audit created it


def test_tool_connections_are_read_only():
    conn = db.connect()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM opportunities")
    conn.close()


def test_every_call_is_audited_including_failures(sam):
    tools.get_opportunities(sam, client_id="C002")
    tools.get_opportunities(sam, client_id="C999")
    failed, ok = audit.recent(2)
    assert (ok["user_id"], ok["tool"], ok["args"], ok["result_ids"], ok["error"]) == \
        ("u2", "get_opportunities", {"client_id": "C002"}, ["SQL:opportunities:OPP-HEL-GB"], None)
    assert (failed["result_ids"], failed["error"]) == ([], "client_not_found")
