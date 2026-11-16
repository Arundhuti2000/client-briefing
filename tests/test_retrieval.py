"""Tests for app/retrieval.py: hybrid search (BM25 + vectors, merged with RRF), filtered first."""

import sqlite3

import numpy as np
import pytest

from app import db, retrieval, tools


@pytest.fixture(autouse=True)
def use_unified_db(unified, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", unified / "briefing.db")


@pytest.fixture
def sam(use_unified_db):
    return tools.load_user("u2")


def test_reciprocal_rank_fusion_rewards_agreement():
    scores = retrieval.reciprocal_rank_fusion(["a", "b"], ["b", "c"])
    assert scores == pytest.approx({"a": 1 / 61, "b": 1 / 62 + 1 / 61, "c": 1 / 62})
    assert max(scores, key=scores.get) == "b"  # ranked by both lists, so it wins


def test_keywords_ignore_stopwords():
    assert retrieval.keywords("Who is the CFO of NWC?") == ["cfo", "nwc"]


def test_unify_saves_one_normalized_vector_per_chunk(unified):
    vectors = retrieval.load_embeddings(unified)
    conn = sqlite3.connect(unified / "briefing.db")
    chunk_ids = {row[0] for row in conn.execute("SELECT chunk_id FROM chunks")}
    conn.close()
    assert set(vectors) == chunk_ids
    for vector in vectors.values():
        assert vector.shape == (384,) and np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-5)


def test_vectors_find_meaning_without_shared_words(sam):
    conn = db.connect()
    candidates = db.visible_chunks(conn, "C001", sam.entitlements)
    conn.close()
    assert retrieval.bm25_ranking(candidates, "currency risk") == []  # no shared words: BM25 alone finds nothing
    result = tools.search_documents(sam, client_id="C001", query="currency risk")
    assert result.facts[0].evidence_id == "DOC:research_001"          # the FX hedging research note


def test_unrelated_queries_return_nothing(sam):
    assert tools.search_documents(sam, client_id="C002", query="football results").facts == []


def test_restricted_chunks_are_never_scored(sam, monkeypatch):
    """Filter first: the restricted Helios note is not even a candidate for either ranker."""
    scored = []
    for ranker in ("bm25_ranking", "vector_ranking"):
        original = getattr(retrieval, ranker)

        def spy(candidates, *args, _original=original):
            scored.extend(chunk["chunk_id"] for chunk in candidates)
            return _original(candidates, *args)
        monkeypatch.setattr(retrieval, ranker, spy)

    result = tools.search_documents(sam, client_id="C002", query="acquisition sustainable financing")
    assert scored and "note_004#0" not in scored
    assert "DOC:note_004" not in [f.evidence_id for f in result.facts]
