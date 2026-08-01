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


_ATS_URL_PATTERNS = [
    (re.compile(r"job-boards\.greenhouse\.io/([^/]+)/"), "greenhouse"),
    (re.compile(r"jobs\.ashbyhq\.com/([^/]+)/"), "ashby"),
    (re.compile(r"jobs\.lever\.co/([^/]+)/"), "lever"),
    (re.compile(r"jobs\.gem\.com/([^/]+)/"), "gem"),
    # BambooHR's slug is the SUBDOMAIN, not a path segment after the domain
    # like the other three - e.g. https://blackrock.bamboohr.com/careers/31.
    (re.compile(r"https?://([^./]+)\.bamboohr\.com/"), "bamboohr"),
]


def parse_company_and_source_from_url(url: str) -> tuple:
    """For a manually-pasted URL (no cached search-result metadata to draw
    from), recover the company slug and platform directly from the URL's own
    structure — deterministic, no extra API call needed. Returns ("", "")
    if the URL doesn't match any known ATS pattern (e.g. a custom careers
    page), which is honest — there's nothing reliable to parse there."""
    if not url:
        return "", ""
    for pattern, source in _ATS_URL_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1), source
    return "", ""


_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_CURRENT_ROLE_DATE_RE = re.compile(
    r"\*\s*([A-Za-z]+)\s+(\d{4})\s*[-–—]\s*(?:present|current)[^*]*\*",
    re.IGNORECASE,
)


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(\+?\d[\d ().-]{7,}\d)")


def parse_contact_info(resume_text: str) -> dict:
    """Pulls name/email/phone/location out of the resume's own header, the
    same two lines pdf_export.py already treats as the name line ("# Name")
    and the contact line right below it ("Location | Phone | Email"). Reuses
    the resume as the single source of truth instead of asking for these
    separately, consistent with the no-invention rule elsewhere in the app —
    contact info comes from what the candidate actually wrote, never guessed.
    Returns '' for any field it can't confidently find rather than guessing."""
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    name = ""
    contact_line = ""

    for i, line in enumerate(lines):
        if line.startswith("# "):
            name = line[2:].strip()
            if i + 1 < len(lines):
                contact_line = lines[i + 1]
            break

    email_match = _EMAIL_RE.search(contact_line)
    email = email_match.group(0) if email_match else ""

    phone = ""
    phone_match = _PHONE_RE.search(contact_line)
    if phone_match:
        phone = phone_match.group(0).strip()

    location = ""
    parts = [p.strip() for p in contact_line.split("|")]
    for part in parts:
        if part and part != email and not _PHONE_RE.fullmatch(part):
            location = part
            break

    return {"name": name, "email": email, "phone": phone, "location": location}


def compute_current_role_tenure(resume_text: str) -> str:
    """Finds the first role dated through 'Present' and computes real elapsed
    tenure from its start date to today. Handing the model this as a stated
    fact, instead of asking it to infer tenure from context, closes a real
    failure mode: a resume bullet mentioning how fast an early milestone was
    hit (e.g., "achieved X in first 4 months") gets conflated with how long
    the role has actually lasted, even with an explicit instruction not to.
    Prompt instructions alone weren't reliably preventing this in practice —
    computing the actual number removes the need for the model to infer it
    at all. Returns "" if no current-dated role is found (a resume with no
    ongoing role, or an unexpected date format) rather than guessing."""
    match = _CURRENT_ROLE_DATE_RE.search(resume_text)
    if not match:
        return ""

    month_name, year_str = match.group(1).lower(), match.group(2)
    if month_name not in _MONTH_NAMES:
        return ""

    start = datetime(int(year_str), _MONTH_NAMES[month_name], 1)
    now = datetime.now()
    total_months = (now.year - start.year) * 12 + (now.month - start.month)
    if total_months < 0:
        return ""

    years, months = divmod(total_months, 12)
    if years and months:
        duration = f"{years} year{'s' if years != 1 else ''}, {months} month{'s' if months != 1 else ''}"
    elif years:
        duration = f"{years} year{'s' if years != 1 else ''}"
    else:
        duration = f"{months} month{'s' if months != 1 else ''}"

    return (
        f"The candidate's current role began {match.group(1)} {year_str} and has "
        f"run continuously since — as of today, that is approximately {duration}, "
        f"regardless of any shorter milestone timeframe mentioned inside a bullet "
        f"under that role."
    )
