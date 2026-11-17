"""End to end through the API, the way the UI uses it (template mode, no model):
resolve "NWC" -> briefing -> sharing blocked -> both conflict decisions -> share -> a follow-up
question -> open a cited source. Then, as Sam, every surface he can reach (briefing, Markdown,
follow-up answers, sources, workflow, clients list, audit log and MCP) must never show the
restricted Helios records: not their IDs, and not any five-word phrase of their text."""

import json
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from api.main import app
from app import db, validate
from mcp_server.server import run_tool

SAM, ALEX = {"X-User-Id": "u2"}, {"X-User-Id": "u1"}
api = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch, unified):
    """A private copy of the unified dev database: the workflow writes decisions, shares and tasks."""
    copy = tmp_path / "briefing.db"
    copy.write_bytes((unified / "briefing.db").read_bytes())
    monkeypatch.setattr(db, "DB_PATH", copy)


def test_the_banker_workflow_end_to_end():
    resolved = api.get("/clients/resolve", params={"q": "NWC"}, headers=SAM).json()
    client_id = resolved["client"]["client_id"]
    assert client_id == "C001"

    briefing = api.post("/briefings", json={"client_id": client_id}, headers=SAM)
    assert briefing.status_code == 200
    b = briefing.json()
    conflicts = [f for f in b["flags"] if f["flag_type"] == "conflict"]
    assert len(conflicts) == 2

    blocked = api.post(f"/briefings/{client_id}/share", json={}, headers=SAM)
    assert blocked.status_code == 409  # sharing waits for every conflict decision

    for flag in conflicts:
        assert all(s in b["evidence"] for s in flag["source_ids"])  # both sides can be opened in Check
        decided = api.post(f"/briefings/{client_id}/decisions",
                           json={"flag_id": flag["evidence_id"], "source_id": flag["uses"]}, headers=SAM)
        assert decided.status_code == 200
    assert api.get(f"/briefings/{client_id}/workflow", headers=SAM).json()["open_conflicts"] == 0

    action = b["actions"][0]
    shared = api.post(f"/briefings/{client_id}/share", headers=SAM,
                      json={"follow_ups": [{"description": f"Follow up: {action['description']}",
                                            "source_id": action["evidence_id"]}]})
    assert shared.status_code == 201
    record = shared.json()
    assert record["approver"] == "u2" and record["recipients"] and len(record["task_ids"]) == 1

    answer = api.post(f"/briefings/{client_id}/ask", json={"question": "Is the FX hedging deal still live?"},
                      headers=SAM).json()
    assert answer["status"] == "answered" and answer["route"] == "pipeline" and answer["bullets"]
    cited = answer["bullets"][0]["citations"][0]
    source = api.get(f"/sources/{cited}", headers=SAM)
    assert source.status_code == 200 and source.json()["evidence_id"] == cited

    chip = next(c for s in b["sections"] for bullet in s["bullets"] for c in bullet["citations"])
    assert api.get(f"/sources/{chip}", headers=SAM).status_code == 200  # a citation chip opens


def test_sam_never_sees_the_restricted_helios_records_anywhere():
    with closing(db.connect()) as conn:
        hidden = db.hidden_restricted_content(conn, ["standard"])
    restricted_ids = sorted({row["record_id"] for row in hidden})
    assert "OPP-HEL-MA" in restricted_ids  # the check below has something to find

    # 1. What Sam sees when he asks nothing about the hidden records (as the eval's leak check,
    #    text Sam typed himself doesn't count, so these questions name nothing restricted)
    seen = []
    briefing = api.post("/briefings", json={"client_id": "C002"}, headers=SAM).json()
    seen += [json.dumps(briefing), briefing["markdown"]]
    for question in ("Is the board considering an acquisition?", "Which deals are in the pipeline?",
                     "Any recent news about them?", "What should I double-check before the meeting?"):
        answer = api.post("/briefings/C002/ask", json={"question": question}, headers=SAM).json()
        seen.append(json.dumps({k: v for k, v in answer.items() if k != "question"}))
    seen += [api.get("/briefings/C002/workflow", headers=SAM).text, api.get("/clients", headers=SAM).text]
    for tool, arguments in (("get_opportunities", {"client_id": "C002"}), ("get_data_quality_flags", {"client_id": "C002"}),
                            ("search_documents", {"client_id": "C002", "query": "board acquisition"}),
                            ("get_open_items", {"client_id": "C002"})):
        seen.append(json.dumps(run_tool(tool, {"user_id": "u2", **arguments})))
    seen.append(json.dumps([row["result_ids"] for row in api.get("/audit", headers=SAM, params={"limit": 200}).json()]))
    sent = "\n".join(seen)
    assert not [rid for rid in restricted_ids if rid in sent]
    assert not [row["record_id"] for row in hidden if validate.word_ngrams(row["text"]) & validate.word_ngrams(sent)]

    # 2. When Sam names a hidden record himself, he gets exactly what a record that doesn't exist gets
    missing = api.get("/sources/DOC:note_999", headers=SAM)
    for evidence_id in ("SQL:opportunities:OPP-HEL-MA", "DOC:note_004"):
        refused = api.get(f"/sources/{evidence_id}", headers=SAM)
        assert (refused.status_code, refused.json()) == (missing.status_code, missing.json())
        assert run_tool("get_source", {"user_id": "u2", "evidence_id": evidence_id}) == \
            run_tool("get_source", {"user_id": "u2", "evidence_id": "DOC:note_999"})  # MCP too
    attach = api.post("/briefings/C002/share", headers=SAM, json={
        "follow_ups": [{"description": "Chase the deal", "source_id": "SQL:opportunities:OPP-HEL-MA"}]})
    assert attach.status_code == 404  # can't attach a source he may not see
    probe = api.post("/briefings/C002/ask", json={"question": "What is Project Sunrise?"}, headers=SAM).json()
    answered = json.dumps({k: v for k, v in probe.items() if k != "question"})
    assert not [rid for rid in restricted_ids if rid in answered] and "Sunrise" not in answered

    alex = api.post("/briefings", json={"client_id": "C002"}, headers=ALEX).json()
    assert "OPP-HEL-MA" in json.dumps(alex)  # and Alex, who may, does see it
