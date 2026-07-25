"""
extract.py
Small shared helpers for pulling salary out of job descriptions when a source
doesn't give us a structured field. Remotive has a real 'salary' field most of
the time; Greenhouse generally doesn't expose one in its public API, so we fall
back to regex over the description text (many US postings include a pay range
inline now due to state pay-transparency laws).
"""

import re
from datetime import datetime, timezone

# Matches range patterns like "$120,000 - $150,000", "$120k-$150k", "$80,000-$100,000/yr",
# "USD 150,250 - 215,250", now including em dash and en dash.
_RANGE_PATTERNS = [
    re.compile(
        r"(?:USD|US\$|\$)\s?\d{1,3}(?:,\d{3}|k)\s?(?:-|to|–|—)\s?(?:USD|US\$|\$)?\s?\d{1,3}(?:,\d{3}|k)",
        re.IGNORECASE,
    ),
    # Hourly rate ranges with bare 2-3 digit numbers, gated on an explicit /hour or /hr
    # suffix so we don't falsely match unrelated small numbers elsewhere in the text.
    re.compile(
        r"(?:USD|US\$|\$)\s?\d{1,3}\s?(?:-|to|–|—)\s?(?:USD|US\$|\$)?\s?\d{1,3}\s?/\s?(?:hour|hr)\b",
        re.IGNORECASE,
    ),
]

# Fallback for a single stated figure, no range: "$150,000 per year", "$150K", "$36k".
_SINGLE_PATTERNS = [
    re.compile(
        r"(?:USD|US\$|\$)\s?\d{1,3}(?:,\d{3}|k)\s?(?:/\s?(?:yr|year|hour|hr)|per\s?(?:year|yr|hour))?",
        re.IGNORECASE,
    ),
]


def extract_salary(text: str) -> str:
    """Best-effort salary extraction from free text. Tries ranges first (more
    informative), then falls back to a single stated figure. Returns '' if
    nothing matches — never fabricates a number."""
    if not text:
        return ""
    for pattern in _RANGE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0).strip()
    for pattern in _SINGLE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0).strip()
    return ""


def _parse_published(raw: str):
    """Shared date parser: Lever gives raw milliseconds-since-epoch, the rest
    give ISO 8601 (date-only or full datetime). Returns None rather than
    guessing if the format isn't recognized."""
    if not raw:
        return None

    raw_str = str(raw).strip()
    parsed = None

    if raw_str.isdigit():
        try:
            parsed = datetime.fromtimestamp(int(raw_str) / 1000, tz=timezone.utc)
        except (ValueError, OSError):
            parsed = None

    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw_str.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            parsed = None

    return parsed


def format_published_date(raw: str) -> str:
    """Normalizes the wildly different 'posted' formats across sources into
    a readable 'X days ago' (or the date itself if older) — Remotive and
    Ashby give ISO date/datetime strings, Greenhouse gives an ISO datetime,
    Lever gives a raw milliseconds-since-epoch integer (as a string), and
    Gem doesn't expose a date at all. Returns '' rather than guessing if the
    format isn't recognized, never fabricates a date."""
    parsed = _parse_published(raw)
    if parsed is None:
        return ""

    now = datetime.now(timezone.utc)
    delta_days = (now - parsed).days

    if delta_days < 0:
        return parsed.strftime("%b %d, %Y")
    if delta_days == 0:
        return "today"
    if delta_days == 1:
        return "1 day ago"
    if delta_days < 30:
        return f"{delta_days} days ago"
    return parsed.strftime("%b %d, %Y")
