"""Tests for app/workflow.py and its endpoints: conflict decisions and sharing a briefing."""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from app import audit, db

SAM, ALEX = {"X-User-Id": "u2"}, {"X-User-Id": "u1"}
CFO, FX = "FLAG:F009", "FLAG:F010"     # Northwind's two conflict flags
api = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch, unified):
    """A private copy of the unified database: these tests write decisions, shares and tasks."""
    copy = tmp_path / "briefing.db"
    copy.write_bytes((unified / "briefing.db").read_bytes())
    monkeypatch.setattr(db, "DB_PATH", copy)


def decide(flag, source, headers=SAM, client="C001"):
    return api.post(f"/briefings/{client}/decisions", json={"flag_id": flag, "source_id": source}, headers=headers)


def share(body=None, headers=SAM, client="C001"):
    return api.post(f"/briefings/{client}/share", json=body or {}, headers=headers)


def test_a_decision_is_stored_and_read_back():
    saved = decide(CFO, "DOC:email_001")
    assert saved.status_code == 200 and saved.json()["source_id"] == "DOC:email_001"
    assert decide(CFO, "SQL:contacts:CT001").status_code == 200  # changing your mind replaces it
    state = api.get("/briefings/C001/workflow", headers=SAM).json()
    assert [d["source_id"] for d in state["decisions"]] == ["SQL:contacts:CT001"] and state["open_conflicts"] == 1
    assert api.get("/briefings/C001/workflow", headers=ALEX).json()["open_conflicts"] == 2  # decisions are per banker


@pytest.mark.parametrize("flag, source, status", [
    ("FLAG:F007", "DOC:brief_001", 404),     # a flag, but not a conflict
    ("FLAG:F999", "DOC:email_001", 404),     # no such flag
    (CFO, "SQL:contacts:CT002", 422),        # not one of this conflict's sources
])
def test_decisions_only_for_this_clients_visible_conflicts(flag, source, status):
    assert decide(flag, source).status_code == status
    assert decide(CFO, "DOC:email_001", client="C002").status_code == 404  # another client's conflict


def test_sharing_is_blocked_until_every_conflict_is_decided():
    blocked = share()
    assert blocked.status_code == 409 and "2 open conflict" in blocked.json()["detail"]
    decide(CFO, "SQL:contacts:CT001")
    assert share().status_code == 409
    decide(FX, "SQL:opportunities:OPP-NOR-FX")
    done = share({"follow_ups": [{"description": "Confirm with the client: Who is the CFO?", "source_id": CFO},
                                 {"description": "Overdue: Send Q3 liquidity analysis", "source_id": "SQL:open_actions:A-001"}]})
    assert done.status_code == 201
    body = done.json()
    assert (body["approver"], body["approver_name"]) == ("u2", "Sam Rivera")
    assert body["recipients"] == ["Alex Morgan", "Jordan Kim", "Sam Rivera"]  # the whole coverage team by default
    assert [t["source_id"] for t in body["tasks"]] == [CFO, "SQL:open_actions:A-001"] and len(body["task_ids"]) == 2
    assert api.get("/briefings/C001/workflow", headers=SAM).json()["share"]["share_id"] == body["share_id"]
    steps = [r["tool"] for r in audit.recent(10, user_id="u2")]
    assert "share" in steps and steps.count("create_task") == 2 and "decision" in steps


def test_a_client_without_conflicts_can_be_shared_straight_away():
    assert share({"recipients": ["Alex Morgan"]}, client="C002").json()["recipients"] == ["Alex Morgan"]


def test_recipients_come_from_the_coverage_team_only():
    assert share({"recipients": ["Someone Else"]}, client="C002").status_code == 422


def test_a_follow_up_on_a_restricted_record_is_refused_for_sam():
    body = {"follow_ups": [{"description": "Chase the deal", "source_id": "SQL:opportunities:OPP-HEL-MA"}]}
    refused = share(body, client="C002")
    assert refused.status_code == 404 and "OPP-HEL-MA" not in refused.text  # same answer as a missing source
    assert share(body, headers=ALEX, client="C002").status_code == 201        # Alex may see it


def test_both_endpoints_need_a_known_user_and_client():
    assert decide(CFO, "DOC:email_001", headers={}).status_code == 401
    assert share(headers={}).status_code == 401
    assert share(client="C999").status_code == 404
