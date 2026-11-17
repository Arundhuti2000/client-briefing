"""Phase 4 tests: a full briefing in mock mode, access control, and graceful failure."""

import datetime as dt
import json

import pytest

from app import audit, db, llm, orchestrator, tools
from app.orchestrator import PLAN, BriefingError, build_briefing
from app.tools import ToolResult


@pytest.fixture(autouse=True)
def use_unified_db(unified, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", unified / "briefing.db")


@pytest.fixture
def sam(use_unified_db):
    return tools.load_user("u2")


@pytest.fixture
def alex(use_unified_db):
    return tools.load_user("u1")


@pytest.fixture
def northwind(sam):
    return build_briefing(sam, "C001")


def generated_text(briefing) -> str:
    """Everything the system wrote (not the source documents behind the citation chips)."""
    return json.dumps([briefing.model_dump(mode="json", include={"sections", "what_changed", "metrics",
                                                                  "opportunities", "actions", "flags"})])


def test_full_briefing_in_mock_mode(northwind):
    assert [s.id for s in northwind.sections] == [name for name, _, _ in PLAN]
    assert all(s.check.passed and s.status == "ok" for s in northwind.sections)
    assert {s.written_by for s in northwind.sections} == {"mock", "code"}
    assert {s.author for s in northwind.sections} == {"template", "code"}  # mock is never labelled AI
    assert northwind.prepared_for == "Sam Rivera (Analyst)"
    cited = {c for s in northwind.sections for b in s.bullets for c in b.citations}
    assert cited and cited <= set(northwind.evidence)  # every citation chip opens something


def test_profile_panels_show_unification(northwind):
    assert northwind.aliases == ["NWC", "Northwind Cap.", "Northwind Capital", "Northwind Capital Partners LLC"]
    assert "Raj Patel, CFO" in northwind.contacts and "Tom Becker, COO" in northwind.contacts  # T2 merged
    assert northwind.evidence["DOC:news_001"].source == "Reuters"


def test_numbers_come_from_sql_and_are_formatted_in_code(northwind):
    revenue = northwind.metrics[0]
    assert (revenue.label, revenue.value, revenue.change, revenue.as_of) == ("Revenue", "$5.1M", "+$300K",
                                                                            dt.date(2026, 10, 16))
    assert next(s for s in northwind.sections if s.id == "metrics").written_by == "code"


def test_what_changed_since_the_last_interaction(northwind):
    assert northwind.last_interaction == dt.date(2026, 9, 15)
    changes = [c.text for c in northwind.what_changed]
    assert changes[0] == "Revenue is $5.1M, up $300K since 15 Sep."
    assert "3 emails and 2 news items since 15 Sep." in changes
    assert "New action for Alex Morgan: schedule treasury management workshop, due 25 Nov." in changes
    assert "FX Hedging opportunity marked Lost on 20 Oct." in changes


def test_opportunities_ranked_by_code_and_lost_is_not_live(northwind):
    ranked = [(o.opp_id, o.rank) for o in northwind.opportunities if o.live]
    assert ranked == [("OPP-NOR-TM", 1), ("OPP-NOR-CF", 2)]  # expected value: $210K before $120K
    fx = next(o for o in northwind.opportunities if o.opp_id == "OPP-NOR-FX")
    assert (fx.live, fx.rank) == (False, None)  # T6


def test_uncertain_panel_shows_the_traps(northwind):
    assert {"stale_statement", "conflict", "overdue", "excluded_source"} <= {f.flag_type for f in northwind.flags}
    assert northwind.flags[0].severity == "high"  # conflicts first
    assert next(a for a in northwind.actions if a.action_id == "A-001").overdue  # T12


def test_injected_instruction_never_appears_in_the_briefing(northwind):
    assert "DOC:email_002" in northwind.evidence  # the email is used as data...
    assert "triple their mandate" not in generated_text(northwind)  # ...but its instruction is never repeated


def test_sam_and_alex_get_different_helios_briefings(sam, alex):
    for_sam, for_alex = build_briefing(sam, "C002"), build_briefing(alex, "C002")
    everything_sam_got = for_sam.model_dump_json()  # including the evidence behind the chips
    for secret in ("OPP-HEL-MA", "note_004", "acquisition", "Project Sunrise", "SunPeak"):
        assert secret not in everything_sam_got, secret
    assert [o.opp_id for o in for_sam.opportunities] == ["OPP-HEL-GB"]
    assert "OPP-HEL-MA" in [o.opp_id for o in for_alex.opportunities]
    assert for_sam.last_interaction == for_alex.last_interaction  # the hidden note doesn't shift the date


def test_a_failed_tool_makes_only_its_section_unavailable(sam, monkeypatch):
    monkeypatch.setattr(tools, "get_news", lambda user, **kwargs: ToolResult(ok=False, error="data_unavailable"))
    briefing = build_briefing(sam, "C001")
    status = {s.id: s.status for s in briefing.sections}
    assert status["news"] == "unavailable"
    assert all(v == "ok" for k, v in status.items() if k != "news")


def test_invented_number_is_retried_once_then_falls_back_to_evidence(sam, monkeypatch):
    calls = []

    def fake_write_sections(sections, feedback=None):
        calls.append((sorted(s.section for s in sections), feedback))
        data = llm.mock_completion(sections, notes=[]).data
        for section in data["sections"]:
            if section["section"] == "opportunities":  # this section always invents a number
                section["bullets"][0]["text"] += " Worth $9M."
        return llm.Completion(data=data, provider="fake", model="fake-model")

    monkeypatch.setattr(llm, "write_sections", fake_write_sections)
    briefing = build_briefing(sam, "C001")
    assert len(calls) == 2 and calls[1][0] == ["opportunities"]  # only the failed section is retried
    assert "numbers not in its cited evidence: ['$9M']" in calls[1][1]["opportunities"][0]
    section = next(s for s in briefing.sections if s.id == "opportunities")
    assert (section.status, section.written_by, section.check.passed) == ("fallback", "evidence (fallback)", True)
    assert section.retry_note == ("First draft rejected: a number wasn't in its source. The second draft "
                                  "failed too, so this shows the source facts directly.")
    assert "$9M" in section.retry_errors[0]  # technical detail, behind "Details"
    rejected = [r for r in audit.recent(20) if r["tool"] == "validator"]
    assert rejected and "$9M" in rejected[0]["error"]  # and in the audit log
    assert not any("$9M" in bullet.text for s in briefing.sections for bullet in s.bullets)  # never displayed
    assert next(s for s in briefing.sections if s.id == "news").written_by == "fake-model"


def test_markdown_export(northwind):
    markdown = orchestrator.to_markdown(northwind)
    assert markdown.startswith("# Northwind Capital Partners")
    assert "prepared for Sam Rivera (Analyst)" in markdown
    assert "## Uncertain, conflicting, or unavailable" in markdown
    assert "- **Who is the CFO?** A June email names Dana Lee" in markdown
    assert "| Revenue | $5.1M | +$300K | 16 Oct 2026 |" in markdown
    assert "## Sources" in markdown and "1. " in markdown  # numbered footnotes instead of IDs


def test_unknown_client_is_an_error(sam):
    with pytest.raises(BriefingError):
        build_briefing(sam, "C999")
