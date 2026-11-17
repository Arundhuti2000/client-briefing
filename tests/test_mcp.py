"""Tests for mcp_server/server.py over a real MCP client session (in memory): the tools and their
schemas, and that Sam (u2) can't get restricted records through MCP."""

import asyncio
import json

import pytest
from mcp import Client

from app import audit, db
from mcp_server import server


@pytest.fixture(autouse=True)
def use_unified_db(unified, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", unified / "briefing.db")


def session(*calls):
    """List the tools and make the given calls through an MCP client connected to our server."""
    async def run():
        async with Client(server.server) as client:
            listed = await client.list_tools()
            results = [await client.call_tool(name, arguments) for name, arguments in calls]
            return listed, results
    return asyncio.run(run())


def payload(result) -> dict:
    return json.loads(result.content[0].text)


def test_the_read_only_tools_are_listed_with_their_pydantic_schemas_and_a_user_id():
    listed, _ = session()
    tools = {t.name: t for t in listed.tools}
    assert {"get_metrics", "get_opportunities", "search_documents", "get_source"} <= set(tools)
    schema = tools["search_documents"].input_schema
    assert schema["required"][0] == "user_id" and {"client_id", "query"} <= set(schema["properties"])
    assert tools["get_metrics"].description and all(t.annotations.read_only_hint for t in tools.values())
    assert "create_task" not in tools  # the one write is not exposed


def test_sam_cannot_get_restricted_records_through_mcp():
    _, (sam_opps, alex_opps, sam_source, sam_search) = session(
        ("get_opportunities", {"user_id": "u2", "client_id": "C002"}),
        ("get_opportunities", {"user_id": "u1", "client_id": "C002"}),
        ("get_source", {"user_id": "u2", "evidence_id": "SQL:opportunities:OPP-HEL-MA"}),
        ("search_documents", {"user_id": "u2", "client_id": "C002", "query": "Project Sunrise acquisition"}),
    )
    assert "OPP-HEL-MA" not in json.dumps(payload(sam_opps)) and "OPP-HEL-MA" in json.dumps(payload(alex_opps))
    assert payload(sam_source) == {"ok": False, "facts": [], "error": "not_found", "candidates": []}
    assert sam_source.is_error and "note_004" not in json.dumps(payload(sam_search))
    assert [r["tool"] for r in audit.recent(5, user_id="u2")][:3] == ["search_documents", "get_source", "get_opportunities"]


def test_a_caller_cannot_raise_its_own_access():
    _, (no_user, unknown, extra) = session(
        ("get_opportunities", {"client_id": "C002"}),
        ("get_opportunities", {"user_id": "nobody", "client_id": "C002"}),
        ("get_opportunities", {"user_id": "u2", "client_id": "C002", "entitlements": ["restricted_deals"]}),
    )
    assert payload(no_user)["error"] == payload(unknown)["error"] == "unknown_user"
    assert payload(extra)["error"] == "invalid_input"  # entitlements can't be passed in
