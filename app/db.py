"""SQLite access for the tools: read-only connections and entitlement-aware queries (SPEC.md section 5).

Every SQL query the tools run lives in this file. Three tables can hold
restricted content (opportunities, chunks, data_quality_flags); their queries
take the user's entitlements and filter inside the WHERE clause, so a restricted
row never leaves the database for a user who can't see it: not as a row, not as
part of a count.
"""

import datetime as dt
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "briefing.db"


def connect(readonly: bool = True) -> sqlite3.Connection:
    """Open briefing.db. The tools use read-only mode, so they cannot write even by mistake.
    Neither mode creates the file if it is missing."""
    mode = "ro" if readonly else "rw"
    conn = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode={mode}", uri=True)
    conn.row_factory = sqlite3.Row  # rows readable by column name
    return conn


def entitlement_filter(column: str, entitlements: list[str]) -> tuple[str, list[str]]:
    """SQL condition keeping only rows whose required entitlement the user holds.
    Unrestricted rows carry 'standard', which every user has; no entitlements -> no rows."""
    if not entitlements:
        return "0", []
    placeholders = ", ".join("?" for _ in entitlements)
    return f"{column} IN ({placeholders})", list(entitlements)

# --- clients and people -----------------------------------------------------


def canonical_client_id(conn, client_id: str) -> str | None:
    """The client's current ID, following a merge (C014 -> C001); None if unknown."""
    if conn.execute("SELECT 1 FROM clients WHERE client_id = ?", (client_id,)).fetchone():
        return client_id
    row = conn.execute("SELECT survivor_id FROM client_merges WHERE merged_id = ?", (client_id,)).fetchone()
    return row["survivor_id"] if row else None


def client(conn, client_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,)).fetchone()


def aliases(conn, client_id: str) -> list[str]:
    return [row["alias"] for row in conn.execute(
        "SELECT alias FROM client_aliases WHERE client_id = ? ORDER BY alias", (client_id,))]


def coverage(conn, client_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM coverage WHERE client_id = ? ORDER BY since, banker_name",
                        (client_id,)).fetchall()


def contacts(conn, client_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM contacts WHERE client_id = ? ORDER BY contact_id", (client_id,)).fetchall()


def user(conn, user_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def users(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM users ORDER BY user_id").fetchall()

# --- what a citation chip opens --------------------------------------------------

# For each table: the SQL expression that rebuilds its evidence-ID key (as the tools
# build it), and the column that dates the record. Only these tables can be opened.
SOURCE_TABLES = {
    "clients": ("client_id", "updated_at"),
    "contacts": ("contact_id", "updated_at"),
    "coverage": ("client_id || ':' || banker_name", "since"),
    "revenue_metrics": ("client_id || ':' || period", "as_of"),
    "holdings": ("client_id || ':' || product || ':' || as_of", "as_of"),
    "performance": ("client_id || ':' || product || ':' || metric || ':' || period", "as_of"),
    "opportunities": ("opp_id", "updated_at"),
    "open_actions": ("action_id", "due_date"),
    "service_issues": ("issue_id", "opened"),
}


def source_row(conn, table: str, key: str, entitlements: list[str]) -> sqlite3.Row | None:
    """The record behind an evidence ID like SQL:opportunities:OPP-NOR-TM, if the user may see it."""
    if table not in SOURCE_TABLES:
        return None  # table names are whitelisted, never taken from the request
    key_sql, _ = SOURCE_TABLES[table]
    sql, params = f"SELECT * FROM {table} WHERE {key_sql} = ?", [key]
    if table == "opportunities":  # the only typed table with restricted rows
        condition, extra = entitlement_filter("required_entitlement", entitlements)
        sql, params = f"{sql} AND {condition}", params + extra
    return conn.execute(sql, params).fetchone()


def visible_document(conn, doc_id: str, entitlements: list[str]) -> list[sqlite3.Row]:
    """A document's chunks, if the user may see it. Documents that were never indexed
    (unattached, or from an unapproved news source) can't be opened."""
    condition, params = entitlement_filter("required_entitlement", entitlements)
    return conn.execute(f"SELECT * FROM chunks WHERE doc_id = ? AND {condition} ORDER BY chunk_id",
                        [doc_id, *params]).fetchall()


def visible_flag(conn, flag_id: str, entitlements: list[str]) -> sqlite3.Row | None:
    condition, params = entitlement_filter("required_entitlement", entitlements)
    return conn.execute(f"SELECT * FROM data_quality_flags WHERE flag_id = ? AND {condition}",
                        [flag_id, *params]).fetchone()

# --- numbers --------------------------------------------------------------------

# Every metric series for one client, oldest first. Evidence IDs match app/unify.py.
# The label people see is built from (source, product, metric) by wording.metric_label.
METRIC_ROWS_SQL = """
SELECT 'revenue_metrics' AS source, NULL AS product, 'revenue_usd' AS metric,
       'SQL:revenue_metrics:' || client_id || ':' || period AS evidence_id,
       revenue_usd AS value, 'usd' AS unit, period, as_of
  FROM revenue_metrics WHERE client_id = :client_id
UNION ALL
SELECT 'revenue_metrics', NULL, 'wallet_share_pct', 'SQL:revenue_metrics:' || client_id || ':' || period,
       wallet_share_pct, 'pct', period, as_of
  FROM revenue_metrics WHERE client_id = :client_id
UNION ALL
SELECT 'holdings', product, NULL, 'SQL:holdings:' || client_id || ':' || product || ':' || as_of,
       balance_usd, 'usd', NULL, as_of
  FROM holdings WHERE client_id = :client_id
UNION ALL
SELECT 'performance', product, metric,
       'SQL:performance:' || client_id || ':' || product || ':' || metric || ':' || period,
       value, CASE WHEN metric LIKE '%pct' THEN 'pct' ELSE 'usd' END, period, as_of
  FROM performance WHERE client_id = :client_id
ORDER BY source, product, metric, as_of
"""


def metric_rows(conn, client_id: str) -> list[sqlite3.Row]:
    return conn.execute(METRIC_ROWS_SQL, {"client_id": client_id}).fetchall()

# --- restricted-capable tables: always filtered by entitlement ----------------------


def opportunities(conn, client_id: str, entitlements: list[str]) -> list[sqlite3.Row]:
    condition, params = entitlement_filter("required_entitlement", entitlements)
    return conn.execute(f"SELECT * FROM opportunities WHERE client_id = ? AND {condition} ORDER BY opp_id",
                        [client_id, *params]).fetchall()


def visible_chunks(conn, client_id: str, entitlements: list[str],
                   doc_types: list[str] | None = None, since: dt.date | None = None) -> list[sqlite3.Row]:
    """The client's document chunks this user may see, newest first."""
    condition, params = entitlement_filter("required_entitlement", entitlements)
    sql = f"SELECT * FROM chunks WHERE client_id = ? AND {condition}"
    params = [client_id, *params]
    if doc_types:
        sql += f" AND doc_type IN ({', '.join('?' for _ in doc_types)})"
        params += list(doc_types)
    if since:
        sql += " AND date >= ?"
        params.append(since.isoformat())
    return conn.execute(sql + " ORDER BY date DESC, chunk_id", params).fetchall()


def flags(conn, client_id: str, entitlements: list[str]) -> list[sqlite3.Row]:
    condition, params = entitlement_filter("required_entitlement", entitlements)
    return conn.execute(f"SELECT * FROM data_quality_flags WHERE client_id = ? AND {condition} ORDER BY flag_id",
                        [client_id, *params]).fetchall()

def hidden_restricted_content(conn, entitlements: list[str]) -> list[sqlite3.Row]:
    """Restricted records this user may NOT see, as (record_id, text).
    Only for the validator's leak check: the result is used to reject output and is
    never shown to the user or sent to the LLM."""
    if entitlements:
        hidden = f"required_entitlement NOT IN ({', '.join('?' for _ in entitlements)})"
    else:
        hidden = "1"
    sql = (f"SELECT doc_id AS record_id, text FROM chunks WHERE {hidden} "
           f"UNION ALL SELECT opp_id, product || ': ' || next_step FROM opportunities WHERE {hidden}")
    return conn.execute(sql, [*entitlements, *entitlements]).fetchall()

# --- tables with no restricted content ----------------------------------------------


def actions(conn, client_id: str) -> list[sqlite3.Row]:
    """Open actions first (soonest due first), then done ones."""
    return conn.execute("SELECT * FROM open_actions WHERE client_id = ? "
                        "ORDER BY status = 'Open' DESC, due_date, action_id", (client_id,)).fetchall()


def service_issues(conn, client_id: str) -> list[sqlite3.Row]:
    """Open issues first, newest first."""
    return conn.execute("SELECT * FROM service_issues WHERE client_id = ? "
                        "ORDER BY status = 'Open' DESC, opened DESC, issue_id", (client_id,)).fetchall()
