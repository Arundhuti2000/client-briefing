"""The briefing reads like a note for a person: no internal IDs, no ISO dates, no "None"."""

import datetime as dt
import re

import pytest

from app import db, orchestrator, tools, wording

# Codes and junk a banker should never see in the briefing text
FORBIDDEN = {
    "document ID": r"\b(?:note|email|brief|news|research)_\d+\b",
    "opportunity ID": r"OPP-",
    "action ID": r"\bA-\d+\b",
    "issue ID": r"\bSI-\d+\b",
    "contact ID": r"\bCT\d+\b",
    "client ID": r"\bC\d{3}\b",
    "user ID": r"\bu\d\b",
    "flag ID": r"\bF\d{3}\b",
    "evidence ID": r"\b(?:SQL|DOC|FLAG):",
    "ISO date": r"\d{4}-\d{2}-\d{2}",
    "None/null/NaN": r"\b(?:None|null|NaN)\b",
    "empty brackets": r"\(\s*\)|\[\s*\]",
}


@pytest.fixture(autouse=True)
def use_unified_db(unified, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", unified / "briefing.db")


def visible_text(b: orchestrator.Briefing) -> list[str]:
    """Everything the page and the Markdown export show as text (IDs may appear only in the
    source panel, the audit log and the citation chips, which are not text)."""
    texts = [b.client_name, b.segment, b.region, b.prepared_for, *b.coverage, *b.contacts, *b.aliases,
             orchestrator.to_markdown(b)]
    texts += [c.text for c in b.what_changed]
    for s in b.sections:
        texts += [s.title, s.question, s.note or "", s.retry_note or "", *(bullet.text for bullet in s.bullets)]
    texts += [f"{m.label} {m.value} {m.change or ''} {m.period or ''}" for m in b.metrics]
    texts += [f"{o.product} {o.stage} {o.value} {o.owner} {o.next_step}" for o in b.opportunities]
    texts += [f"{a.description} {a.owner} {a.status}" for a in b.actions]
    texts += [f"{f.title} {f.detail}" for f in b.flags]
    return texts


@pytest.mark.parametrize("user_id, client_id", [("u2", "C001"), ("u1", "C002"), ("u2", "C003")])
def test_no_internal_ids_iso_dates_or_none_in_visible_text(user_id, client_id):
    briefing = orchestrator.build_briefing(tools.load_user(user_id), client_id)
    for text in visible_text(briefing):
        for what, pattern in FORBIDDEN.items():
            match = re.search(pattern, text)
            assert match is None, f"{what} {match and match.group()!r} in: {text}"


def test_lost_opportunity_reads_plainly():
    briefing = orchestrator.build_briefing(tools.load_user("u2"), "C001")
    fx = next(o for o in briefing.opportunities if o.product == "FX Hedging")
    assert f"{fx.stage}: {fx.next_step}." == "Lost: the client chose another provider."


def test_asks_mark_contradictions_inline_and_do_not_repeat_flags():
    briefing = orchestrator.build_briefing(tools.load_user("u2"), "C001")
    said = next(s for s in briefing.sections if s.id == "client_said").bullets
    commitment = next(b for b in said if "$50M" in b.text)
    assert commitment.text.endswith("⚠ Contradicted: the opportunity was marked Lost in October.")
    assert not any(b.text.startswith(("Who is", "Is the")) for b in said)  # conflicts live in the panel
    points = [b.text for b in next(s for s in briefing.sections if s.id == "talking_points").bullets]
    assert 3 <= len(points) <= 5
    assert "Confirm who the CFO is (records say Raj Patel; a June email says Dana Lee)." in points
    assert "Ask about the $50M FX hedging commitment, since the opportunity was marked Lost." in points

# --- the wording helpers ---------------------------------------------------------------


def test_dates_read_like_people_write_them():
    assert wording.long_date("2026-09-15") == "15 Sep 2026"
    assert wording.day_month("2026-09-15") == "15 Sep" and wording.day_month("2024-03-05") == "5 Mar 2024"
    assert wording.month_of(dt.date(2026, 5, 20)) == "May" and wording.month_of("2024-03-05") == "March 2024"
    assert wording.period_text("2026Q3") == "Q3 2026"


@pytest.mark.parametrize("source, product, metric, label", [
    ("revenue_metrics", None, "revenue_usd", "Revenue"),
    ("revenue_metrics", None, "wallet_share_pct", "Wallet share"),
    ("performance", "Payments", "payment_volume_usd", "Payment volume"),
    ("performance", "Custody", "assets_under_custody_usd", "Assets under custody"),
    ("holdings", "Operating Deposits", None, "Operating deposits"),
    ("holdings", "Revolving Credit Facility", None, "Credit facility balance"),
    ("holdings", "Term Loan", None, "Term loan balance"),
])
def test_metric_labels_come_from_a_rule(source, product, metric, label):
    assert wording.metric_label(source, product, metric) == label


def test_missing_values_are_left_out_not_printed():
    assert wording.clean_note("None - the client chose another provider") == "the client chose another provider"
    assert [wording.clean_note(v) for v in (None, "", "None", "null", "NaN")] == [None] * 5
