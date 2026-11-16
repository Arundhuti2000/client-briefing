"""Load the raw CSV exports into SQLite (SPEC.md section 3).

Two deterministic steps, no LLM:
  1. Staging: copy every data/raw/*.csv as-is into a stg_<file> table (all TEXT),
     so the original values stay queryable for audit and debugging.
  2. Cleaning: convert dates, money and status values into the typed tables.

Only formats are fixed here. Entity problems (aliases, duplicate clients and
contacts, conflicts) are left for app/unify.py, which also fills
opportunities.client_id by resolving stg_pipeline_opportunities.client_name.

Run:  make load   (or: python -m app.load_structured)
"""

import csv
import datetime as dt
import json
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Each source system exports dates its own way. The format is configured per
# source because it can't be guessed: "02/06/2026" is 2 June in the UK file
# and would be 6 February in the US file.
DATE_FORMATS = {
    "crm_clients": "%Y-%m-%dT%H:%M:%SZ",
    "crm_contacts": "%m/%d/%Y",
    "crm_coverage": "%Y-%m-%d",
    "finance_revenue": "%d-%b-%Y",
    "holdings": "%Y/%m/%d",
    "performance": "%Y-%m-%d",
    "pipeline_opportunities": "%Y-%m-%d %H:%M:%S",
    "service_issues": "%d/%m/%Y",
    "open_actions": "%b %d, %Y",
}

CLIENT_STATUSES = {"Active", "Inactive"}
STAGES = {"Discovery", "Proposal", "Negotiation", "Won", "Lost"}
SEVERITIES = {"Low", "Medium", "High"}
ISSUE_STATUSES = {"Open", "Closed"}
ACTION_STATUSES = {"Open", "Done"}

# Typed tables: the tables and columns from SPEC.md section 3, plus planted_traps.
# Dates are ISO text (YYYY-MM-DD), so SQLite compares them correctly as strings.
SCHEMA = """
CREATE TABLE clients (
    client_id   TEXT PRIMARY KEY,
    legal_name  TEXT NOT NULL,
    domain      TEXT,
    segment     TEXT,
    region      TEXT,
    status      TEXT,
    updated_at  TEXT
);
CREATE TABLE client_aliases (
    alias      TEXT NOT NULL,
    client_id  TEXT NOT NULL,
    source     TEXT
);
CREATE TABLE contacts (
    contact_id         TEXT PRIMARY KEY,
    client_id          TEXT NOT NULL,
    name               TEXT,
    title              TEXT,
    relationship_role  TEXT,
    email              TEXT,
    last_contact_date  TEXT,
    updated_at         TEXT
);
CREATE TABLE coverage (
    client_id      TEXT NOT NULL,
    banker_name    TEXT,
    coverage_role  TEXT,            -- primary, secondary, product
    since          TEXT
);
CREATE TABLE users (
    user_id       TEXT PRIMARY KEY,
    name          TEXT,
    role          TEXT,
    entitlements  TEXT              -- JSON list, e.g. ["standard"]
);
CREATE TABLE revenue_metrics (
    client_id         TEXT NOT NULL,
    period            TEXT,         -- e.g. 2026Q3
    revenue_usd       INTEGER,
    wallet_share_pct  REAL,
    as_of             TEXT
);
CREATE TABLE holdings (
    client_id    TEXT NOT NULL,
    product      TEXT,
    balance_usd  INTEGER,
    as_of        TEXT
);
CREATE TABLE performance (
    client_id  TEXT NOT NULL,
    product    TEXT,
    metric     TEXT,
    value      REAL,
    period     TEXT,
    as_of      TEXT
);
CREATE TABLE opportunities (
    opp_id                TEXT PRIMARY KEY,
    client_id             TEXT,     -- NULL until unify resolves the client name
    product               TEXT,
    stage                 TEXT,     -- Discovery, Proposal, Negotiation, Won, Lost
    est_value_usd         INTEGER,
    owner                 TEXT,
    next_step             TEXT,
    updated_at            TEXT,
    restricted            INTEGER,  -- 0 or 1
    required_entitlement  TEXT
);
CREATE TABLE service_issues (
    issue_id   TEXT PRIMARY KEY,
    client_id  TEXT NOT NULL,
    summary    TEXT,
    severity   TEXT,
    status     TEXT,
    opened     TEXT,
    closed     TEXT
);
CREATE TABLE open_actions (
    action_id      TEXT PRIMARY KEY,
    client_id      TEXT NOT NULL,
    description    TEXT,
    owner          TEXT,
    due_date       TEXT,
    status         TEXT,            -- Open or Done
    source_doc_id  TEXT
);
CREATE TABLE approved_news_sources (
    source_name  TEXT PRIMARY KEY
);
CREATE TABLE planted_traps (
    trap_id            TEXT PRIMARY KEY,
    description        TEXT,
    planted_in         TEXT,        -- JSON list like ["doc:note_001", "clients:C014"]
    expected_behavior  TEXT
);
"""

# ---------------------------------------------------------------------------
# Value cleaners
# ---------------------------------------------------------------------------


def to_date(text: str, source: str) -> str | None:
    """Parse a date in that source's format and return ISO YYYY-MM-DD; blank -> None."""
    if not text.strip():
        return None
    return dt.datetime.strptime(text.strip(), DATE_FORMATS[source]).date().isoformat()


def to_money(text: str) -> int:
    """'$12,400,000' -> 12400000"""
    return int(text.replace("$", "").replace(",", "").strip())


def to_status(text: str, allowed: set[str]) -> str:
    """'LOST', 'lost', ' Lost ' -> 'Lost'. An unknown value is an error, not a guess."""
    value = text.strip().capitalize()
    if value not in allowed:
        raise ValueError(f"unexpected status {text!r}; expected one of {sorted(allowed)}")
    return value


def split_list(text: str) -> list[str]:
    """'Helios; HEG' -> ['Helios', 'HEG']"""
    return [item.strip() for item in text.split(";") if item.strip()]

# ---------------------------------------------------------------------------
# Step 1: staging
# ---------------------------------------------------------------------------


def load_staging(conn: sqlite3.Connection, raw_dir: Path) -> None:
    """Copy each CSV into stg_<file name>, every column TEXT, values untouched."""
    for csv_path in sorted(raw_dir.glob("*.csv")):
        with csv_path.open(encoding="utf-8", newline="") as f:
            header, *rows = list(csv.reader(f))
        table = f"stg_{csv_path.stem}"  # file names come from our own raw/ folder
        columns = ", ".join(f'"{name}" TEXT' for name in header)
        conn.execute(f"CREATE TABLE {table} ({columns})")
        placeholders = ", ".join("?" for _ in header)
        conn.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)


def staged(conn: sqlite3.Connection, source: str) -> list[dict]:
    """All rows of stg_<source> as dicts keyed by column name."""
    cursor = conn.execute(f"SELECT * FROM stg_{source}")
    names = [col[0] for col in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def insert(conn: sqlite3.Connection, table: str, *values) -> None:
    placeholders = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO {table} VALUES ({placeholders})", values)

# ---------------------------------------------------------------------------
# Step 2: cleaning, one function per typed table
# ---------------------------------------------------------------------------


def clean_clients(conn):
    for r in staged(conn, "crm_clients"):
        insert(conn, "clients", r["client_id"], r["legal_name"], r["domain"], r["segment"], r["region"],
               to_status(r["status"], CLIENT_STATUSES), to_date(r["updated_at"], "crm_clients"))
        for alias in split_list(r["aliases"]):
            insert(conn, "client_aliases", alias, r["client_id"], "crm")


def clean_contacts(conn):
    # Emails keep their letter case: spotting duplicate contacts is unify's job (T3).
    for r in staged(conn, "crm_contacts"):
        insert(conn, "contacts", r["contact_id"], r["client_id"], r["name"], r["title"], r["relationship_role"],
               r["email"], to_date(r["last_contact_date"], "crm_contacts"), to_date(r["updated_at"], "crm_contacts"))


def clean_coverage(conn):
    for r in staged(conn, "crm_coverage"):
        insert(conn, "coverage", r["client_id"], r["banker_name"], r["coverage_role"],
               to_date(r["since"], "crm_coverage"))


def clean_users(conn):
    for r in staged(conn, "iam_users"):
        insert(conn, "users", r["user_id"], r["name"], r["role"], json.dumps(split_list(r["entitlements"])))


def clean_revenue_metrics(conn):
    for r in staged(conn, "finance_revenue"):
        insert(conn, "revenue_metrics", r["client_id"], r["period"], int(r["revenue_usd"]),
               float(r["wallet_share_pct"]), to_date(r["as_of"], "finance_revenue"))


def clean_holdings(conn):
    for r in staged(conn, "holdings"):
        insert(conn, "holdings", r["client_id"], r["product"], to_money(r["balance_usd"]),
               to_date(r["as_of"], "holdings"))


def clean_performance(conn):
    for r in staged(conn, "performance"):
        insert(conn, "performance", r["client_id"], r["product"], r["metric"], float(r["value"]),
               r["period"], to_date(r["as_of"], "performance"))


def clean_opportunities(conn):
    # client_id stays NULL: the export only has a client name, which unify resolves.
    for r in staged(conn, "pipeline_opportunities"):
        insert(conn, "opportunities", r["opp_id"], None, r["product"], to_status(r["stage"], STAGES),
               int(r["est_value_usd"]), r["owner"], r["next_step"],
               to_date(r["updated_at"], "pipeline_opportunities"), int(r["restricted"]),
               r["required_entitlement"])


def clean_service_issues(conn):
    for r in staged(conn, "service_issues"):
        insert(conn, "service_issues", r["issue_id"], r["client_id"], r["summary"],
               to_status(r["severity"], SEVERITIES), to_status(r["status"], ISSUE_STATUSES),
               to_date(r["opened"], "service_issues"), to_date(r["closed"], "service_issues"))


def clean_open_actions(conn):
    for r in staged(conn, "open_actions"):
        insert(conn, "open_actions", r["action_id"], r["client_id"], r["description"], r["owner"],
               to_date(r["due_date"], "open_actions"), to_status(r["status"], ACTION_STATUSES),
               r["source_doc_id"])


def clean_approved_news_sources(conn):
    for r in staged(conn, "approved_news_sources"):
        insert(conn, "approved_news_sources", r["source_name"].strip())


CLEANERS = [
    clean_clients, clean_contacts, clean_coverage, clean_users, clean_revenue_metrics, clean_holdings,
    clean_performance, clean_opportunities, clean_service_issues, clean_open_actions,
    clean_approved_news_sources,
]

TYPED_TABLES = [
    "clients", "client_aliases", "contacts", "coverage", "users", "revenue_metrics", "holdings",
    "performance", "opportunities", "service_issues", "open_actions", "approved_news_sources",
    "planted_traps",
]

# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def load(data_dir: Path) -> None:
    """Rebuild data_dir/briefing.db from data_dir/raw/*.csv and planted_traps.json."""
    db_path = data_dir / "briefing.db"
    db_path.unlink(missing_ok=True)  # start from scratch so every load is identical
    conn = sqlite3.connect(db_path)
    try:
        load_staging(conn, data_dir / "raw")
        conn.executescript(SCHEMA)
        for clean in CLEANERS:
            clean(conn)
        traps = json.loads((data_dir / "planted_traps.json").read_text(encoding="utf-8"))
        for t in traps:
            insert(conn, "planted_traps", t["trap_id"], t["description"], json.dumps(t["planted_in"]),
                   t["expected_behavior"])
        conn.commit()
    finally:
        conn.close()


def print_summary(data_dir: Path) -> None:
    """Print row counts for the staging tables and the typed tables."""
    conn = sqlite3.connect(data_dir / "briefing.db")
    try:
        print(f"Loaded {data_dir / 'raw'} into {data_dir / 'briefing.db'}")
        staging = [name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'stg%' ORDER BY name")]
        for title, tables in (("Staging tables (raw text, as exported)", staging),
                              ("Typed tables (cleaned)", TYPED_TABLES)):
            print(f"\n{title}:")
            for table in tables:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                print(f"  {table:<30}{count:>3}")
        pending = conn.execute("SELECT COUNT(*) FROM opportunities WHERE client_id IS NULL").fetchone()[0]
        print(f"\nOpportunities waiting for client_id from unify: {pending}")
    finally:
        conn.close()


def main() -> None:
    load(DATA_DIR)
    print_summary(DATA_DIR)


if __name__ == "__main__":
    main()
