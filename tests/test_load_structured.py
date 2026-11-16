"""Tests for app/load_structured.py: raw CSVs -> stg_ tables -> clean, typed tables."""

import json
import re
import shutil
import sqlite3

import pytest

from app import load_structured as ls

SPEC_COLUMNS = {
    "clients": ["client_id", "legal_name", "domain", "segment", "region", "status", "updated_at"],
    "client_aliases": ["alias", "client_id", "source"],
    "contacts": ["contact_id", "client_id", "name", "title", "relationship_role", "email",
                 "last_contact_date", "updated_at"],
    "coverage": ["client_id", "banker_name", "coverage_role", "since"],
    "users": ["user_id", "name", "role", "entitlements"],
    "revenue_metrics": ["client_id", "period", "revenue_usd", "wallet_share_pct", "as_of"],
    "holdings": ["client_id", "product", "balance_usd", "as_of"],
    "performance": ["client_id", "product", "metric", "value", "period", "as_of"],
    "opportunities": ["opp_id", "client_id", "product", "stage", "est_value_usd", "owner", "next_step",
                      "updated_at", "restricted", "required_entitlement"],
    "service_issues": ["issue_id", "client_id", "summary", "severity", "status", "opened", "closed"],
    "open_actions": ["action_id", "client_id", "description", "owner", "due_date", "status", "source_doc_id"],
    "approved_news_sources": ["source_name"],
    "planted_traps": ["trap_id", "description", "planted_in", "expected_behavior"],
}

DATE_COLUMNS = {
    "clients": ["updated_at"],
    "contacts": ["last_contact_date", "updated_at"],
    "coverage": ["since"],
    "revenue_metrics": ["as_of"],
    "holdings": ["as_of"],
    "performance": ["as_of"],
    "opportunities": ["updated_at"],
    "service_issues": ["opened", "closed"],
    "open_actions": ["due_date"],
}

STATUS_COLUMNS = [
    ("clients", "status", ls.CLIENT_STATUSES),
    ("opportunities", "stage", ls.STAGES),
    ("service_issues", "severity", ls.SEVERITIES),
    ("service_issues", "status", ls.ISSUE_STATUSES),
    ("open_actions", "status", ls.ACTION_STATUSES),
]


@pytest.fixture(scope="module")
def conn(generated):
    connection = sqlite3.connect(generated / "briefing.db")
    yield connection
    connection.close()


# --- the value cleaners -------------------------------------------------------

@pytest.mark.parametrize("source, raw, expected", [
    ("crm_clients", "2026-10-01T14:32:00Z", "2026-10-01"),
    ("crm_contacts", "08/20/2026", "2026-08-20"),            # US: month first
    ("service_issues", "02/06/2026", "2026-06-02"),          # UK: day first
    ("finance_revenue", "16-Oct-2026", "2026-10-16"),
    ("holdings", "2026/09/30", "2026-09-30"),
    ("pipeline_opportunities", "2026-10-20 16:05:00", "2026-10-20"),
    ("open_actions", "Oct 31, 2026", "2026-10-31"),
    ("service_issues", "", None),                            # blank closed date
])
def test_to_date_uses_each_sources_format(source, raw, expected):
    assert ls.to_date(raw, source) == expected


def test_to_money_strips_symbols():
    assert ls.to_money("$12,400,000") == 12400000


def test_to_status_normalizes_case_and_rejects_unknown_values():
    assert ls.to_status("LOST", ls.STAGES) == "Lost"
    assert ls.to_status(" proposal ", ls.STAGES) == "Proposal"
    with pytest.raises(ValueError):
        ls.to_status("Closed-Lost", ls.STAGES)


# --- the loaded database ------------------------------------------------------

def test_staging_keeps_raw_values(conn):
    assert conn.execute("SELECT balance_usd, as_of FROM stg_holdings LIMIT 1").fetchone() == \
        ("$182,000,000", "2026/06/30")
    assert conn.execute("SELECT stage FROM stg_pipeline_opportunities WHERE opp_id = 'OPP-NOR-FX'").fetchone() == \
        ("LOST",)


def test_typed_tables_have_spec_columns(conn):
    for table, columns in SPEC_COLUMNS.items():
        actual = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
        assert actual == columns, table


def test_every_typed_date_is_iso(conn):
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for table, columns in DATE_COLUMNS.items():
        for column in columns:
            for (value,) in conn.execute(f"SELECT {column} FROM {table}"):
                assert value is None or iso.match(value), (table, column, value)


def test_every_status_is_canonical(conn):
    for table, column, allowed in STATUS_COLUMNS:
        values = {v for (v,) in conn.execute(f"SELECT {column} FROM {table}")}
        assert values <= allowed, (table, column, values)


def test_money_and_lists_are_typed(conn):
    assert conn.execute("SELECT balance_usd FROM holdings WHERE client_id = 'C002' AND product = 'Term Loan'"
                        ).fetchone() == (250000000,)
    aliases = {a for (a,) in conn.execute("SELECT alias FROM client_aliases WHERE client_id = 'C001'")}
    assert aliases == {"Northwind Capital", "NWC", "Northwind Cap."}
    entitlements = conn.execute("SELECT entitlements FROM users WHERE user_id = 'u1'").fetchone()[0]
    assert json.loads(entitlements) == ["standard", "restricted_deals"]


def test_contact_emails_keep_their_case_for_unify(conn):
    emails = {e for (e,) in conn.execute("SELECT email FROM contacts WHERE name = 'Priya Shah'")}
    assert emails == {"priya.shah@northwindcap.com", "Priya.Shah@NorthwindCap.com"}  # T3 left for unify


def test_pipeline_client_id_waits_for_unify(conn):
    rows = conn.execute("SELECT o.client_id, s.client_name FROM opportunities o "
                        "JOIN stg_pipeline_opportunities s ON s.opp_id = o.opp_id").fetchall()
    assert len(rows) == 6
    assert all(client_id is None and client_name for client_id, client_name in rows)


def test_loading_is_deterministic(generated, tmp_path):
    # Load a copy of the same raw files a second time and compare every row.
    shutil.copytree(generated / "raw", tmp_path / "raw")
    shutil.copy(generated / "planted_traps.json", tmp_path / "planted_traps.json")
    ls.load(tmp_path)
    dumps = []
    for db in (generated / "briefing.db", tmp_path / "briefing.db"):
        c = sqlite3.connect(db)
        dumps.append(list(c.iterdump()))
        c.close()
    assert dumps[0] == dumps[1]
