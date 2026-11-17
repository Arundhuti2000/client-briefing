"""Tests for eval/quality.py (the quality metrics report) and data/generate_holdout.py."""

import json

import pytest
import yaml

from app import db, tools
from app.orchestrator import build_briefing
from app.validate import Bullet
from data import generate_holdout
from eval import quality, run_eval


@pytest.fixture
def use_dev(unified, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", unified / "briefing.db")


def test_the_metric_maths():
    assert quality.ndcg(["a", "b"], {"a", "b"}) == 1.0 and quality.ndcg(["x", "a"], {"a"}) < 1.0
    tally = quality.Tally()
    tally.add(True, True, "hit")
    tally.add(False, True, "false alarm")
    tally.add(True, False, "miss")
    tally.add(False, False, "quiet")
    report = tally.report()
    assert (report["precision"], report["recall"], report["cases"]) == (0.5, 0.5, 4)
    assert report["false_positives"] == ["false alarm"] and report["false_negatives"] == ["miss"]


def test_retrieval_is_scored_per_method_and_never_retrieves_restricted_documents(use_dev, monkeypatch):
    questions = yaml.safe_load(run_eval.RETRIEVAL_SETS["dev"].read_text(encoding="utf-8"))
    report = quality.retrieval_metrics(questions)
    assert set(report["methods"]) == {"bm25", "vector", "hybrid"} and report["scored"] >= 25
    assert report["restricted_retrieved"] == 0
    assert report["methods"]["hybrid"]["recall@5"] >= 0.9  # a floor, not a target: the labels are hand-made
    monkeypatch.setattr(db, "entitlement_filter", lambda column, entitlements: ("1", []))  # what eval-break does
    assert quality.retrieval_metrics(questions)["restricted_retrieved"] > 0


def test_the_detectors_get_200_plus_perturbations_and_their_mistakes_are_listed(use_dev):
    report = quality.detector_metrics()
    assert report["cases"] >= 200
    detectors = report["detectors"]
    assert detectors["Stale metrics"]["f1"] == 1.0 and detectors["Entity resolution"]["precision"] == 1.0
    # Known limitations, listed rather than hidden (a regression marker if they ever change):
    assert any("double space" in fp for fp in detectors["Role conflicts"]["false_positives"])
    assert any("program" in fn for fn in detectors["Commitment conflicts"]["false_negatives"])


def test_the_router_report_has_a_confusion_table():
    questions = yaml.safe_load(run_eval.ROUTER_SET.read_text(encoding="utf-8"))
    report = quality.router_metrics(questions)
    assert 30 <= report["questions"] <= 40 and len(report["confusion"]) == len(report["routes"])
    assert sum(map(sum, report["confusion"])) == report["questions"] and 0 < report["accuracy"] <= 1


def test_faithfulness_counts_only_ai_written_claims(use_dev):
    briefing = build_briefing(tools.load_user("u2"), "C001")
    assert quality.faithfulness([briefing])["claims"] == 0  # template mode: nothing written by AI
    section = next(s for s in briefing.sections if s.id == "client_said")
    section.author = "ai"
    section.bullets = [Bullet(text="Raj Patel said the client has committed to $50M of FX hedging by Q4.",
                              citations=["DOC:note_001"]),
                       Bullet(text="The client plans to triple their mandate with us.", citations=["DOC:note_001"])]
    report = quality.faithfulness([briefing])
    assert (report["claims"], report["supported"]) == (2, 1) and "triple" in report["unsupported"][0]


def test_the_holdout_dataset_is_separate(tmp_path):
    generate_holdout.generate(tmp_path)
    traps = json.loads((tmp_path / "planted_traps.json").read_text(encoding="utf-8"))
    docs = list((tmp_path / "raw" / "docs").rglob("*.*"))
    assert len(traps) == 12 and len(docs) == len(generate_holdout.DOCUMENTS)
    text = " ".join(p.read_text(encoding="utf-8") for p in [*docs, *(tmp_path / "raw").glob("*.csv")])
    assert not any(name in text for name in ("Northwind", "Helios", "Arbor", "Raj Patel"))  # no dev names
