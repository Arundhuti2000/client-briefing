"""Plain-English wording for people: dates, money, labels (used by unify, tools, orchestrator).

The briefing must read like a short note a banker can scan in two minutes, so
everything a person sees is worded here: no internal IDs, no ISO dates, no "None".
Numbers still come from SQL; these helpers only format them.
"""

import datetime as dt
import re

AS_OF_DATE = dt.date(2026, 11, 18)  # demo "today" = the meeting date; in production, the run date

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
FULL_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December"]

DOC_NAMES = {"email": "email", "meeting_note": "meeting note", "prior_briefing": "prior briefing",
             "research": "research note", "news": "news item"}
SOURCE_NAMES = {"email": "email", "crm_notes": "meeting note", "briefing_archive": "prior briefing",
                "internal_research": "research note"}  # anything else is a news publication, e.g. Reuters

# --- dates ---------------------------------------------------------------------


def as_date(value) -> dt.date:
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value)[:10])


def long_date(value) -> str:
    """Tables and headers: '2026-09-15' -> '15 Sep 2026'"""
    d = as_date(value)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def day_month(value) -> str:
    """In sentences: '2026-09-15' -> '15 Sep' (the year is added when it isn't this year)"""
    d = as_date(value)
    text = f"{d.day} {MONTHS[d.month - 1]}"
    return text if d.year == AS_OF_DATE.year else f"{text} {d.year}"


def month_of(value) -> str:
    """In sentences: '2026-05-20' -> 'May'; '2024-03-05' -> 'March 2024'"""
    d = as_date(value)
    month = FULL_MONTHS[d.month - 1]
    return month if d.year == AS_OF_DATE.year else f"{month} {d.year}"


def days_before(value, later=AS_OF_DATE) -> int:
    return (as_date(later) - as_date(value)).days


def period_text(period: str | None) -> str:
    """'2026Q3' -> 'Q3 2026'"""
    match = re.fullmatch(r"(\d{4})Q([1-4])", period or "")
    return f"Q{match[2]} {match[1]}" if match else (period or "")

# --- money and changes ------------------------------------------------------------


def format_usd(amount: float) -> str:
    """4200000 -> '$4.2M', 50000000 -> '$50M', 1450000000 -> '$1.45B' (up to two decimals)"""
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(amount) >= size:
            return f"${amount / size:.2f}".rstrip("0").rstrip(".") + suffix
    return f"${amount:,.0f}"


def value_text(value: float, unit: str) -> str:
    """'13.6%' for percentages, '$5.1M' for dollars"""
    return f"{value:g}%" if unit == "pct" else format_usd(value)


def signed_change(change: float, unit: str) -> str:
    """For tables: '+$300K', '-$15M', '+0.8 pts'"""
    sign = "+" if change >= 0 else "-"
    return f"{sign}{abs(change):g} pts" if unit == "pct" else f"{sign}{format_usd(abs(change))}"


def change_words(change: float, unit: str) -> str:
    """For sentences: 'up $300K', 'down $15M', 'up 0.8 points', 'unchanged'"""
    if change == 0:
        return "unchanged"
    direction = "up" if change > 0 else "down"
    amount = f"{abs(change):g} points" if unit == "pct" else format_usd(abs(change))
    return f"{direction} {amount}"

# --- words ---------------------------------------------------------------------------


def article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def first_lower(text: str) -> str:
    """'Send Q3 analysis' -> 'send Q3 analysis' (an acronym like 'FX' stays as it is)"""
    first = text.split(" ", 1)[0]
    return text if first.isupper() and len(first) > 1 else text[:1].lower() + text[1:]


def plain_words(text: str) -> str:
    """For use mid-sentence: 'FX Hedging' -> 'FX hedging', 'Green Bond Issuance' -> 'green bond issuance'"""
    return " ".join(w if w.isupper() and len(w) > 1 else w.lower() for w in text.split())


def sentence_case(text: str) -> str:
    """'Operating Deposits' -> 'Operating deposits'"""
    return capitalize(plain_words(text))


def join_words(items: list[str]) -> str:
    """['a', 'b', 'c'] -> 'a, b and c'"""
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def doc_phrase(doc_type: str, date) -> str:
    """'a June email', 'an August meeting note', 'a March prior briefing'"""
    month = month_of(date)
    return f"{article(month)} {month} {DOC_NAMES[doc_type]}"


def source_name(source: str | None) -> str:
    """Where a document came from, for people: 'meeting note', 'email', or the publication."""
    return SOURCE_NAMES.get(source or "", source or "source")


NONE_PREFIX = re.compile(r"^\s*(none|n/a|null)\s*[-–:]\s*", re.IGNORECASE)


def clean_note(text) -> str | None:
    """Data junk out: 'None - the client chose another provider' -> 'the client chose another provider';
    None, '', 'null', 'NaN' -> None (so callers leave it out instead of printing it)."""
    if text is None:
        return None
    cleaned = NONE_PREFIX.sub("", str(text)).strip().rstrip(".")
    return None if cleaned.lower() in ("", "none", "null", "nan", "n/a") else cleaned

# --- metric labels ------------------------------------------------------------------

LENDING_WORDS = ("loan", "facility", "credit")  # balances of these products are money owed
QUALIFIERS = {"revolving"}                       # dropped from short labels


def metric_label(source: str, product: str | None, metric: str | None) -> str:
    """A short label from the column names, by rule:
    revenue_usd -> 'Revenue', wallet_share_pct -> 'Wallet share',
    assets_under_custody_usd -> 'Assets under custody', payment_volume_usd -> 'Payment volume',
    holdings 'Operating Deposits' -> 'Operating deposits',
    holdings 'Revolving Credit Facility' -> 'Credit facility balance'."""
    if source == "holdings":
        name = sentence_case(" ".join(w for w in (product or "").split() if w.lower() not in QUALIFIERS))
        return f"{name} balance" if any(word in name.lower() for word in LENDING_WORDS) else name
    words = re.sub(r"_(usd|pct)$", "", metric or "").replace("_", " ")
    return capitalize(words)
