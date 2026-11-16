"""Phase 1 tests: the raw files look like real exports and every trap is planted."""

import csv
import json
import sqlite3

import pytest

from app.ingest import load_documents
from data import generate_data as gd

RAW_CSVS = {"crm_clients.csv", "crm_contacts.csv", "crm_coverage.csv", "iam_users.csv", "finance_revenue.csv",
            "holdings.csv", "performance.csv", "pipeline_opportunities.csv", "service_issues.csv",
            "open_actions.csv", "approved_news_sources.csv"}

# File format expected in each doc_type folder
FORMATS = {"email": ".eml", "meeting_note": ".md", "prior_briefing": ".md", "research": ".md", "news": ".txt"}

# How a planted_in reference like "contacts:CT003" maps to a typed-table row
KEY_COLUMNS = {
    "clients": "client_id",
    "contacts": "contact_id",
    "opportunities": "opp_id",
    "open_actions": "action_id",
    "revenue_metrics": "client_id || ':' || period",
}

NORTHWIND_REFS = {"C001", "C014", "NWC", "Northwind Cap.", "Northwind Capital", "Northwind Capital Partners"}


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def built(generated):
    conn = sqlite3.connect(generated / "briefing.db")
    docs = load_documents(generated / "raw" / "docs", generated / "extracted_claims.json")
    yield conn, {d.doc_id: d for d in docs}
    conn.close()


def test_raw_folder_has_every_export(generated):
    assert {p.name for p in (generated / "raw").glob("*.csv")} == RAW_CSVS


def test_raw_exports_are_realistically_inconsistent(generated):
    raw = generated / "raw"
    # Different date formats between files
    assert read_csv(raw / "crm_contacts.csv")[0]["updated_at"] == "08/20/2026"
    assert read_csv(raw / "finance_revenue.csv")[-1]["as_of"] == "16-Oct-2026"
    assert read_csv(raw / "open_actions.csv")[0]["due_date"] == "Oct 31, 2026"
    # Money as text in holdings
    assert all(r["balance_usd"].startswith("$") and "," in r["balance_usd"] for r in read_csv(raw / "holdings.csv"))
    # Pipeline names clients instead of using IDs
    pipeline = read_csv(raw / "pipeline_opportunities.csv")
    assert "client_id" not in pipeline[0] and pipeline[0]["client_name"] == "Northwind Capital Partners"
    # Mixed-case status values
    stages = {r["stage"] for r in pipeline}
    assert any(s.isupper() for s in stages) and any(s.islower() for s in stages)


def test_each_doc_type_uses_its_file_format(generated):
    files = [p for p in (generated / "raw" / "docs").rglob("*") if p.is_file()]
    assert len(files) == 25
    for path in files:
        assert path.suffix == FORMATS[path.parent.name], path.name


def test_all_twelve_traps_point_at_real_records(built):
    conn, docs = built
    traps = conn.execute("SELECT trap_id, planted_in FROM planted_traps ORDER BY rowid").fetchall()
    assert [trap_id for trap_id, _ in traps] == [f"T{i}" for i in range(1, 13)]
    for trap_id, planted_in in traps:
        for ref in json.loads(planted_in):
            kind, key = ref.split(":", 1)
            if kind == "doc":
                assert key in docs, (trap_id, ref)
            else:
                row = conn.execute(f"SELECT 1 FROM {kind} WHERE {KEY_COLUMNS[kind]} = ?", (key,)).fetchone()
                assert row, (trap_id, ref)


def test_stale_and_conflict_traps(built):
    conn, docs = built
    # T4: March briefing says $4.2M; the latest SQL revenue is 2026Q3 at $5.1M
    assert docs["brief_001"].claims == [{"type": "metric", "metric": "revenue_usd", "value": 4200000}]
    assert "$4.2M" in docs["brief_001"].text
    latest = conn.execute(
        "SELECT period, revenue_usd FROM revenue_metrics WHERE client_id = 'C001' ORDER BY as_of DESC LIMIT 1"
    ).fetchone()
    assert latest == ("2026Q3", 5100000)

    # T5: email names Dana Lee as CFO; contacts says Raj Patel and was updated later
    cfo_name, cfo_updated = conn.execute(
        "SELECT name, updated_at FROM contacts WHERE client_id = 'C001' AND title = 'CFO'"
    ).fetchone()
    assert cfo_name == "Raj Patel"
    assert docs["email_001"].claims[0]["name"] == "Dana Lee"
    assert docs["email_001"].date.isoformat() < cfo_updated

    # T6: the note's commitment is on a Northwind product whose opportunity is Lost.
    # client_id is filled by unify later, so match on the pipeline's client name.
    product = docs["note_001"].claims[0]["product"]
    stage, client_name = conn.execute(
        "SELECT o.stage, s.client_name FROM opportunities o "
        "JOIN stg_pipeline_opportunities s ON s.opp_id = o.opp_id WHERE o.product = ?", (product,)
    ).fetchone()
    assert (stage, client_name) == ("Lost", "Northwind Capital Partners")


def test_restricted_content_only_in_restricted_records(built):
    conn, docs = built
    # T9: the M&A opportunity needs restricted_deals
    assert conn.execute(
        "SELECT restricted, required_entitlement FROM opportunities WHERE opp_id = 'OPP-HEL-MA'"
    ).fetchone() == (1, "restricted_deals")
    restricted_docs = [doc_id for doc_id, d in docs.items() if d.restricted]
    assert restricted_docs == ["note_004"]
    assert docs["note_004"].required_entitlement == "restricted_deals"
    # No unrestricted document may hint at the deal
    for doc_id, d in docs.items():
        if not d.restricted:
            for secret in ("acquisition", "Project Sunrise", "SunPeak", "OPP-HEL-MA"):
                assert secret not in d.text, (doc_id, secret)


def test_demo_dates(built):
    conn, docs = built
    # Last interaction with Northwind = latest meeting note or prior briefing = 2026-09-15
    interactions = [d.date.isoformat() for d in docs.values()
                    if d.client_ref in NORTHWIND_REFS and d.doc_type in ("meeting_note", "prior_briefing")]
    assert max(interactions) == gd.LAST_INTERACTION == "2026-09-15"
    # T12: exactly one open action is overdue on the meeting date
    overdue = conn.execute("SELECT action_id FROM open_actions WHERE status = 'Open' AND due_date < ?",
                           (gd.MEETING_DATE,)).fetchall()
    assert overdue == [("A-001",)]


def test_generation_is_deterministic(tmp_path):
    snapshots = []
    for run in ("run1", "run2"):
        gd.generate(tmp_path / run)
        snapshots.append({p.relative_to(tmp_path / run).as_posix(): p.read_bytes()
                          for p in (tmp_path / run).rglob("*") if p.is_file()})
    assert snapshots[0] == snapshots[1]
