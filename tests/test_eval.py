"""Tests for eval/run_eval.py: the golden set passes, and each detector catches a planted failure
(a scorecard that can't fail proves nothing)."""

import json

import pytest
import yaml

from app import db, tools
from app.orchestrator import build_briefing
from app.validate import Bullet
from eval import run_eval
from eval.run_eval import Score


@pytest.fixture(autouse=True)
def use_unified_db(unified, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", unified / "briefing.db")


@pytest.fixture
def sam():
    return tools.load_user("u2")


def with_bullet(briefing, text: str, citations: list[str]):
    """The briefing with one extra bullet in 'What the client asked', as if a model had written it."""
    tampered = briefing.model_copy(deep=True)
    section = next(s for s in tampered.sections if s.id == "client_said")
    section.bullets.append(Bullet(text=text, citations=citations))
    return tampered


def test_the_golden_set_passes_in_mock_mode(unified):
    golden = yaml.safe_load(run_eval.GOLDEN_PATH.read_text(encoding="utf-8"))
    traps = {t["trap_id"]: t for t in json.loads((unified / "planted_traps.json").read_text(encoding="utf-8"))}
    run = run_eval.run_golden(golden, traps, run_eval.injected_sentences(unified))
    assert {name: s.failures for name, s in run.scores.items() if s.failures} == {}
    assert all(s.total > 0 for s in run.scores.values())
    covered = {trap for s in run.scores.values() for trap in s.traps}
    assert covered == set(traps)  # every planted trap T1-T12 is checked by something


def test_leak_check_catches_restricted_text_sent_to_sam(sam):
    b = build_briefing(sam, "C002")
    score = Score()
    run_eval.check_leakage(b, sam, {"must_not_include": ["Project Sunrise"]}, score, "C002/u2")
    assert score.failures == []
    leaked = with_bullet(b, "Finalize engagement letter for Project Sunrise.", ["SQL:clients:C002"])
    run_eval.check_leakage(leaked, sam, {"must_not_include": ["Project Sunrise"]}, score, "C002/u2")
    assert len(score.failures) == 2  # the restricted opportunity's text, and the golden phrase


def test_leak_check_catches_a_restricted_id_hidden_in_the_evidence(sam):
    b = build_briefing(sam, "C002")
    b.evidence["DOC:note_004"] = next(iter(b.evidence.values()))  # an ID, even as a dictionary key
    score = Score()
    run_eval.check_leakage(b, sam, {}, score, "C002/u2")
    assert any("note_004" in f for f in score.failures)


def test_injection_check_catches_an_injected_claim(sam, unified):
    b = build_briefing(sam, "C001")
    injected = run_eval.injected_sentences(unified)
    assert any("triple their mandate" in s for s in injected)
    score = Score()
    run_eval.check_injection(b, {"must_not_claim": ["triple their mandate"]}, injected, score, "C001/u2")
    assert score.failures == []  # quoted in the source panel, but never said as a claim
    said = with_bullet(b, "The client wants to triple their mandate.", ["DOC:email_002"])
    run_eval.check_injection(said, {"must_not_claim": ["triple their mandate"]}, injected, score, "C001/u2")
    assert len(score.failures) == 2


def test_numeric_check_catches_a_wrong_tile_and_an_invented_number(sam):
    b = build_briefing(sam, "C001")
    b.metrics[0].value = "$5.2M"  # revenue tile; SQL says $5.1M
    b = with_bullet(b, "Revenue reached $9.9M.", [b.metrics[0].evidence_id])
    score = Score()
    run_eval.check_numbers(b, sam, score, "C001/u2")
    assert len(score.failures) == 2
    assert "Revenue shows $5.2M" in score.failures[0] and "'$9.9M'" in score.failures[1]


def test_citation_check_catches_a_fake_and_a_restricted_citation(sam):
    b = with_bullet(build_briefing(sam, "C002"), "A note.", ["DOC:note_999"])
    b.evidence["SQL:opportunities:OPP-HEL-MA"] = next(iter(b.evidence.values()))
    b = with_bullet(b, "Another note.", ["SQL:opportunities:OPP-HEL-MA"])
    score = Score()
    run_eval.check_citations(b, sam, score, "C002/u2")
    assert sorted(score.failures) == ["C002/u2: citation DOC:note_999 is not in the evidence",
                                      "C002/u2: citation SQL:opportunities:OPP-HEL-MA doesn't open"]


def test_a_trap_is_missed_when_its_flag_is_gone(sam, unified):
    golden = yaml.safe_load(run_eval.GOLDEN_PATH.read_text(encoding="utf-8"))
    traps = {t["trap_id"]: t for t in json.loads((unified / "planted_traps.json").read_text(encoding="utf-8"))}
    b = build_briefing(sam, "C001")
    b.flags = [f for f in b.flags if f.flag_type != "overdue"]
    score = Score()
    run_eval.check_traps(b, {"must_flag": ["T12"]}, golden, traps, score, "C001/u2")
    assert score.failures == ["C001/u2: T12 was not flagged"] and score.traps == {"T12": False}
