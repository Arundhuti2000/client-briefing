"""Tests for app/ingest.py: every file format loads into the same Document model."""

import datetime as dt
import json
from collections import Counter

import pytest

from app.ingest import Document, load_documents

ORIGINAL_FIELDS = ["doc_id", "doc_type", "client_ref", "date", "author", "source", "restricted",
                   "required_entitlement", "text", "claims"]


@pytest.fixture(scope="module")
def docs(generated):
    loaded = load_documents(generated / "raw" / "docs", generated / "extracted_claims.json")
    return {d.doc_id: d for d in loaded}


def test_document_model_keeps_the_original_fields():
    assert list(Document.model_fields) == ORIGINAL_FIELDS


def test_every_format_loads(docs):
    counts = Counter(d.doc_type for d in docs.values())
    assert counts == {"email": 7, "meeting_note": 6, "news": 6, "prior_briefing": 3, "research": 3}


def test_email_metadata_comes_from_headers(docs):
    d = docs["email_001"]
    assert (d.client_ref, d.date, d.author, d.source) == ("C001", dt.date(2026, 6, 10), "Priya Shah", "email")
    assert d.text.startswith("July call agenda")  # subject first, then the body
    assert "Dana Lee, our CFO" in d.text


def test_markdown_metadata_comes_from_front_matter(docs):
    d = docs["note_004"]
    assert (d.client_ref, d.date, d.author) == ("HEG", dt.date(2026, 9, 30), "Alex Morgan")
    assert (d.restricted, d.required_entitlement) == (True, "restricted_deals")
    assert d.text.startswith("# Confidential - Project Sunrise")  # front matter is not in the text
    assert docs["research_001"].doc_type == "research"


def test_news_metadata_comes_from_header_lines(docs):
    t7 = docs["news_004"]
    assert t7.client_ref is None  # T7: the feed tagged no client
    assert (t7.source, t7.date) == ("Financial Times", dt.date(2026, 10, 18))
    assert t7.text.startswith("Helios Energy posts record solar output")
    assert docs["news_005"].client_ref == "Arbor"  # T8 keeps its ambiguous reference
    assert docs["news_003"].source == "MarketWhispers Blog"  # T11
    assert not any(d.restricted for d in docs.values() if d.doc_type == "news")


def test_claims_are_attached_by_doc_id(generated, docs):
    claims_file = json.loads((generated / "extracted_claims.json").read_text(encoding="utf-8"))
    assert set(claims_file) <= set(docs)  # no claims for documents that don't exist
    for doc_id, d in docs.items():
        assert d.claims == claims_file.get(doc_id, [])


def test_markdown_without_front_matter_is_rejected(tmp_path):
    (tmp_path / "docs" / "meeting_note").mkdir(parents=True)
    (tmp_path / "docs" / "meeting_note" / "bad.md").write_text("# No front matter\n", encoding="utf-8")
    (tmp_path / "claims.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="missing YAML front matter"):
        load_documents(tmp_path / "docs", tmp_path / "claims.json")
