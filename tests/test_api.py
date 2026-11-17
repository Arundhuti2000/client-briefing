"""Phase 5 tests for api/main.py: the six endpoints, identity, entitlements, CORS."""

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from api.main import app
from app import db

SAM = {"X-User-Id": "u2"}
ALEX = {"X-User-Id": "u1"}
api = TestClient(app)


@pytest.fixture(autouse=True)
def use_unified_db(unified, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", unified / "briefing.db")


def source(evidence_id, headers):
    return api.get(f"/sources/{quote(evidence_id)}", headers=headers)


def test_users_lists_demo_users_with_their_entitlements():
    users = {u["user_id"]: u for u in api.get("/users").json()}
    assert users["u1"]["entitlements"] == ["standard", "restricted_deals"]
    assert (users["u2"]["name"], users["u2"]["entitlements"]) == ("Sam Rivera", ["standard"])


@pytest.mark.parametrize("headers", [{}, {"X-User-Id": "nobody"}])
def test_unknown_or_missing_user_is_rejected(headers):
    assert api.get("/audit", headers=headers).status_code == 401


@pytest.mark.parametrize("query, client_id, matched_by", [
    ("NWC", "C001", "exact"), ("Northwind Cap.", "C001", "exact"), ("C014", "C001", "id"),
])
def test_resolve_shows_alias_resolution(query, client_id, matched_by):
    body = api.get("/clients/resolve", params={"q": query}, headers=SAM).json()
    assert (body["client"]["client_id"], body["client"]["legal_name"], body["matched_by"]) == \
        (client_id, "Northwind Capital Partners", matched_by)


def test_unresolved_name_offers_candidates():
    body = api.get("/clients/resolve", params={"q": "Arbor"}, headers=SAM).json()
    assert body["client"] is None and body["error"] == "client_not_found"
    assert [c["legal_name"] for c in body["candidates"]] == ["Arbor Health Systems"]


def test_briefing_differs_by_user():
    for_sam = api.post("/briefings", json={"client_id": "C002"}, headers=SAM)
    for_alex = api.post("/briefings", json={"client_id": "C002"}, headers=ALEX)
    assert for_sam.status_code == for_alex.status_code == 200
    assert "OPP-HEL-MA" not in for_sam.text and "acquisition" not in for_sam.text
    assert "OPP-HEL-MA" in for_alex.text
    body = for_sam.json()
    assert len(body["sections"]) == 8 and all(s["check"]["passed"] for s in body["sections"])
    assert body["markdown"].startswith("# Helios Energy Group")
    assert body["prepared_for"] == "Sam Rivera (Analyst)"


def test_briefing_errors():
    assert api.post("/briefings", json={"client_id": "C999"}, headers=SAM).status_code == 404
    assert api.post("/briefings", json={"client_id": "X1"}, headers=SAM).status_code == 422


def test_sources_open_records_documents_and_flags():
    revenue = source("SQL:revenue_metrics:C001:2026Q3", SAM).json()
    assert revenue["details"]["revenue_usd"] == 5100000
    holdings = source("SQL:holdings:C001:Operating Deposits:2026-09-30", SAM)  # spaces in the key
    assert holdings.json()["details"]["balance_usd"] == 214000000
    assert "Dana Lee, our CFO" in source("DOC:email_001", SAM).json()["value"]
    assert "$4.2M" in source("FLAG:F007", SAM).json()["value"]


def test_restricted_and_nonexistent_sources_look_identical():
    hidden = source("SQL:opportunities:OPP-HEL-MA", SAM)
    missing = source("SQL:opportunities:OPP-NOPE", SAM)
    assert (hidden.status_code, hidden.json()) == (missing.status_code, missing.json()) == \
        (404, {"detail": "This source is not available."})
    assert source("DOC:note_004", SAM).status_code == 404
    assert source("SQL:opportunities:OPP-HEL-MA", ALEX).status_code == 200
    assert "Project Sunrise" in source("DOC:note_004", ALEX).json()["value"]


def test_excluded_news_cannot_be_opened():
    for headers in (SAM, ALEX):  # T11: the unapproved blog was never indexed
        assert source("DOC:news_003", headers).status_code == 404


def test_tasks_are_created_and_audited():
    response = api.post("/tasks", headers=SAM, json={"client_id": "C001", "description": "Send the Q3 analysis",
                                                     "due_date": "2026-11-20", "source_id": "SQL:open_actions:A-001"})
    assert response.status_code == 201
    task = response.json()
    assert (task["user_id"], task["client_id"], task["status"]) == ("u2", "C001", "Open")
    latest = api.get("/audit", params={"limit": 1}, headers=SAM).json()[0]
    assert (latest["tool"], latest["result_ids"]) == ("create_task", [task["task_id"]])
    assert api.post("/tasks", headers=SAM, json={"client_id": "C999", "description": "x" * 5}).status_code == 404
    assert api.post("/tasks", headers=SAM, json={"client_id": "C001", "description": "ok!", "owner": "me"}
                    ).status_code == 422  # unknown fields are rejected


def test_audit_shows_only_the_callers_own_rows():
    api.get("/sources/SQL:opportunities:OPP-HEL-MA", headers=ALEX)  # Alex's audit row names the deal
    rows = api.get("/audit", params={"limit": 200}, headers=SAM).json()
    assert rows and all(r["user_id"] == "u2" for r in rows)
    # Sam's own args may contain what Sam typed; nothing *returned* to Sam names the deal
    assert not any("OPP-HEL-MA" in result_id for r in rows for result_id in r["result_ids"])


def test_cors_allows_only_the_react_dev_server():
    def preflight(origin):
        return api.options("/users", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
    assert preflight("http://localhost:5173").headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in preflight("https://evil.example").headers


def test_clients_lists_meetings_with_what_needs_checking_and_no_llm(monkeypatch):
    from app import llm
    monkeypatch.setattr(llm, "write_sections", lambda *a, **k: pytest.fail("the meetings list must not call the LLM"))
    rows = {r["client_id"]: r for r in api.get("/clients", headers=SAM).json()}
    assert list(rows) == ["C003", "C002", "C001"]  # by name: Arbor, Helios, Northwind
    northwind = rows["C001"]
    assert (northwind["client_name"], northwind["primary_banker"]) == ("Northwind Capital Partners", "Alex Morgan")
    assert northwind["meeting_date"] == "2026-11-18" and "NWC" in northwind["aliases"]
    assert northwind["conflicts"] == ["Who is the CFO?", "Is the FX hedging deal still live?"]
    assert northwind["heads_up"] == ["Revenue figure is out of date", "Overdue action"]  # housekeeping left out
    assert rows["C002"]["conflicts"] == [] and api.get("/clients").status_code == 401
