"""Hybrid search over document chunks: BM25 + vectors, merged with RRF (SPEC.md sections 4 and 5).

Filter first, rank second: SQL selects only the chunks this user may see for
this client (app/db.py). Both rankers then score just those candidates, so a
restricted chunk is never even a candidate: it can't appear in results or shift
another chunk's score.

  - Keyword ranking: BM25Plus (rank_bm25). Plus, not classic Okapi, because
    per-client corpora are tiny and Okapi scores common words as zero or less.
  - Vector ranking: cosine similarity on all-MiniLM-L6-v2 embeddings, which
    finds meaning without shared words ("currency risk" -> the FX hedging note).
  - Reciprocal Rank Fusion (k = 60) merges the two rankings by rank, not score,
    so the two different score scales never need to be compared.

The embeddings are computed once by app/unify.py and saved next to briefing.db
as embeddings.npy (one normalized row per chunk) plus embeddings_index.json
(the chunk_id of each row). Only the query is embedded at search time.
"""

import datetime as dt
import functools
import json
import re
import sqlite3
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Plus

from app import db

MODEL_NAME = "all-MiniLM-L6-v2"
RRF_K = 60             # standard Reciprocal Rank Fusion constant (SPEC section 4)
MIN_SIMILARITY = 0.25  # measured on our chunks: related text scores ~0.3-0.55, unrelated <= 0.11

STOPWORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does", "for", "from", "has", "have",
             "how", "in", "is", "it", "of", "on", "or", "our", "the", "their", "this", "to", "was", "we", "were",
             "what", "when", "which", "who", "with"}

# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def model():
    """Load the embedding model once per process. Uses the local copy when there is one,
    so searches never touch the network; downloads (~90 MB) only the first time."""
    from sentence_transformers import SentenceTransformer  # slow import; only when needed
    try:
        return SentenceTransformer(MODEL_NAME, local_files_only=True)
    except Exception:
        return SentenceTransformer(MODEL_NAME)


def encode(texts: list[str]) -> np.ndarray:
    """Normalized vectors, so a dot product is the cosine similarity."""
    return model().encode(texts, normalize_embeddings=True, show_progress_bar=False).astype(np.float32)


def save_embeddings(data_dir: Path, chunk_ids: list[str], vectors: np.ndarray) -> None:
    np.save(data_dir / "embeddings.npy", vectors)
    (data_dir / "embeddings_index.json").write_text(json.dumps(chunk_ids), encoding="utf-8")


def load_embeddings(data_dir: Path) -> dict[str, np.ndarray]:
    """chunk_id -> vector"""
    vectors = np.load(data_dir / "embeddings.npy")
    chunk_ids = json.loads((data_dir / "embeddings_index.json").read_text(encoding="utf-8"))
    return dict(zip(chunk_ids, vectors))

# ---------------------------------------------------------------------------
# The two rankers and the fusion
# ---------------------------------------------------------------------------


def keywords(text: str) -> list[str]:
    return [word for word in re.findall(r"\w+", text.lower()) if word not in STOPWORDS]


def bm25_ranking(candidates: list[sqlite3.Row], query: str) -> list[str]:
    """chunk_ids that share a keyword with the query, best BM25 score first."""
    terms = keywords(query)
    chunk_words = [keywords(chunk["text"]) for chunk in candidates]
    scores = BM25Plus(chunk_words).get_scores(terms)
    hits = [(score, chunk["date"], chunk["chunk_id"])
            for chunk, words, score in zip(candidates, chunk_words, scores) if set(terms) & set(words)]
    return [chunk_id for _, _, chunk_id in sorted(hits, reverse=True)]


def vector_ranking(candidates: list[sqlite3.Row], query: str, vectors: dict[str, np.ndarray]) -> list[str]:
    """chunk_ids whose meaning is close to the query, most similar first."""
    query_vector = encode([query])[0]
    hits = [(float(vectors[chunk["chunk_id"]] @ query_vector), chunk["date"], chunk["chunk_id"])
            for chunk in candidates]
    return [chunk_id for similarity, _, chunk_id in sorted(hits, reverse=True) if similarity >= MIN_SIMILARITY]


def reciprocal_rank_fusion(*rankings: list[str]) -> dict[str, float]:
    """Each ranking adds 1 / (k + rank) to an item's score; items ranked well by both win."""
    scores = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (RRF_K + rank)
    return scores

# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search(conn, client_id: str, query: str, entitlements: list[str], doc_types: list[str] | None = None,
           since: dt.date | None = None, top_k: int = 5) -> list[tuple[sqlite3.Row, float]]:
    """Best visible chunks as (chunk, RRF score). An empty query returns the newest chunks."""
    candidates = db.visible_chunks(conn, client_id, entitlements, doc_types, since)  # 1. filter first
    if not candidates or not keywords(query):
        return [(chunk, 0.0) for chunk in candidates[:top_k]]
    vectors = load_embeddings(db.DB_PATH.parent)
    fused = reciprocal_rank_fusion(bm25_ranking(candidates, query),                  # 2. rank two ways
                                   vector_ranking(candidates, query, vectors))
    by_id = {chunk["chunk_id"]: chunk for chunk in candidates}
    best = sorted(fused, key=lambda cid: (fused[cid], by_id[cid]["date"], cid), reverse=True)  # 3. merge
    return [(by_id[cid], fused[cid]) for cid in best[:top_k]]
