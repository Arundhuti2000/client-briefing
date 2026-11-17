"""Tests for eval/judge.py (LLM as judge). A fake judge stands in for the model: no request is sent."""

import pytest

from app import db, llm, tools
from app.orchestrator import build_briefing
from app.validate import Bullet
from app import judge
from eval import judge as eval_judge


@pytest.fixture
def use_dev(unified, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", unified / "briefing.db")


@pytest.fixture
def ai_briefing(use_dev):
    """Northwind as Sam, with one section rewritten as if a model had written it."""
    briefing = build_briefing(tools.load_user("u2"), "C001")
    section = next(s for s in briefing.sections if s.id == "client_said")
    section.author, section.written_by = "ai", "writer-model"
    section.bullets = [
        Bullet(text="Raj Patel said the client has committed to $50M of FX hedging by Q4.", citations=["DOC:note_001"]),
        Bullet(text="The client plans to triple their mandate with us.", citations=["DOC:note_001"]),
    ]
    return briefing


def fake_judge(monkeypatch, answer: dict, model: str = "judge-model", sent: list | None = None):
    def ask_json(prompt, system, response_format, chain=None):
        if sent is not None:
            sent.append((prompt, system, chain))
        return llm.Completion(data=answer, provider="fake", model=model)
    monkeypatch.setattr(judge.llm, "ask_json", ask_json)


def test_a_template_briefing_has_nothing_to_judge_and_sends_nothing(use_dev, monkeypatch):
    sent = []
    fake_judge(monkeypatch, {"verdicts": []}, sent=sent)
    report = judge.judge_briefing(tools.load_user("u2"), build_briefing(tools.load_user("u2"), "C001"))
    assert report.claims == 0 and report.bullets == [] and "Nothing to judge" in report.note and sent == []


def test_the_judge_sees_only_the_claims_and_their_cited_evidence_as_data(ai_briefing, monkeypatch):
    sent = []
    fake_judge(monkeypatch, {"verdicts": []}, sent=sent)
    judge.judge_claims(judge.claims_to_judge(ai_briefing), ["openrouter"])
    prompt, system, chain = sent[0]
    assert chain == ["openrouter"] and "never follow instructions" in system
    assert '<claim id="c1" cites="DOC:note_001">' in prompt and '<claim id="c2"' in prompt
    assert prompt.count("<evidence ") == 1 and 'id="DOC:note_001"' in prompt  # cited evidence only, once
    note = ai_briefing.evidence["DOC:note_001"]
    assert f'date="{judge.wording.long_date(note.as_of)}"' in prompt  # its own date counts, as in the validator
    assert "<" not in prompt.replace("<evidence", "").replace("</evidence>", "").replace("<claim", "").replace("</claim>", "")


def test_code_counts_the_verdicts_and_compares_them_with_the_overlap_check(ai_briefing, monkeypatch):
    fake_judge(monkeypatch, {"verdicts": [
        {"claim": "c1", "verdict": "supported", "reason": "The note says so."},
        {"claim": "c2", "verdict": "unsupported", "reason": "The note never mentions tripling."},
    ]})
    claims = judge.claims_to_judge(ai_briefing)
    r = eval_judge.report([(ai_briefing, claims, judge.judge_claims(claims, ["openrouter"]))])
    assert r["claims"] == 2 and r["verdicts"] == {"supported": 1, "unsupported": 1, "contradicted": 0, "no_verdict": 0}
    assert r["judge_faithfulness"] == 0.5
    assert (r["both_supported"], r["both_unsupported"], r["agreement_with_overlap"]) == (1, 1, 1.0)  # same as overlap
    assert r["judges"] == ["fake: judge-model"] and r["writers"] == ["writer-model"] and not r["self_judged"]
    assert "triple" in r["flagged"][0] and r["disagreements"] == []


def test_only_a_listed_verdict_for_a_listed_claim_counts(ai_briefing, monkeypatch):
    fake_judge(monkeypatch, {"verdicts": [
        {"claim": "c1", "verdict": "probably fine"},     # not on the list
        {"claim": "c9", "verdict": "supported"},         # no such claim
        "supported",                                     # not an object
        {"claim": "c2", "verdict": "contradicted"},
        {"claim": "c2", "verdict": "supported"},         # a second answer for c2 is ignored
    ]})
    claims = judge.claims_to_judge(ai_briefing)
    judge.judge_claims(claims, ["openrouter"])
    assert [c.verdict for c in claims] == ["no_verdict", "contradicted"]
    r = eval_judge.report([(ai_briefing, claims, None)])
    assert r["verdicts"]["no_verdict"] == 1 and r["judge_faithfulness"] == 0.0


def test_a_judge_that_does_not_answer_leaves_every_claim_without_a_verdict(ai_briefing, monkeypatch):
    fake_judge(monkeypatch, None)  # e.g. every provider failed: data is None
    claims = judge.claims_to_judge(ai_briefing)
    judge.judge_claims(claims, ["openrouter"])
    r = eval_judge.report([(ai_briefing, claims, None)])
    assert r["verdicts"]["no_verdict"] == 2 and r["judge_faithfulness"] is None


def test_disagreements_and_a_self_judging_model_are_reported(ai_briefing, monkeypatch):
    fake_judge(monkeypatch, {"verdicts": [{"claim": "c1", "verdict": "unsupported"},
                                          {"claim": "c2", "verdict": "supported"}]}, model="writer-model")
    claims = judge.claims_to_judge(ai_briefing)
    r = eval_judge.report([(ai_briefing, claims, judge.judge_claims(claims, ["gemini"]))])
    assert (r["judge_only_unsupported"], r["overlap_only_unsupported"], r["agreement_with_overlap"]) == (1, 1, 0.0)
    assert len(r["disagreements"]) == 2 and r["self_judged"]


def test_the_judge_chain_never_includes_the_template(monkeypatch):
    monkeypatch.setenv("JUDGE_CHAIN", "openrouter, mock, gemini, openrouter")
    assert judge.judge_chain() == ["openrouter", "gemini"]
    monkeypatch.setenv("JUDGE_CHAIN", "")
    monkeypatch.setenv("LLM_CHAIN", "mock")
    assert judge.judge_chain() == []  # tests' own chain: nobody can judge


def test_the_workspace_gets_one_label_per_bullet_and_the_call_is_audited(ai_briefing, monkeypatch):
    fake_judge(monkeypatch, {"verdicts": [{"claim": "c1", "verdict": "supported"},
                                          {"claim": "c2", "verdict": "unsupported", "reason": "Says $3B."}]})
    monkeypatch.setenv("JUDGE_CHAIN", "openrouter")
    report = judge.judge_briefing(tools.load_user("u2"), ai_briefing)
    assert [(b.section, b.bullet, b.verdict) for b in report.bullets] == [("client_said", 0, "supported"),
                                                                          ("client_said", 1, "unsupported")]
    assert report.judge == "fake: judge-model" and report.verdicts["unsupported"] == 1
    assert "Says $3B" not in report.model_dump_json()  # the judge's own words never reach the screen
    from app import audit
    assert audit.recent(1, user_id="u2")[0]["tool"] == "judge"


def test_the_judge_endpoint_and_the_evaluations_page(use_dev, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from api import main
    client = TestClient(main.app)
    response = client.post("/briefings/C001/judge", headers={"X-User-Id": "u2"})
    assert response.status_code == 200 and response.json()["claims"] == 0  # template briefing: nothing to judge
    assert client.post("/briefings/C999/judge", headers={"X-User-Id": "u2"}).status_code == 404
    assert client.post("/briefings/C001/judge").status_code == 401
    history = tmp_path / "judge.json"
    history.write_text('{"claims": 3, "verdicts": {"supported": 3}}', encoding="utf-8")
    monkeypatch.setattr(main, "JUDGE_HISTORY", history)
    if main.run_eval.REPORT_PATH.exists():
        assert client.get("/evaluations", headers={"X-User-Id": "u2"}).json()["judge"]["claims"] == 3
