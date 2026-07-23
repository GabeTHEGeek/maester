"""
extract.py
Small shared helpers for pulling salary out of job descriptions when a source
doesn't give us a structured field. Remotive has a real 'salary' field most of
the time; Greenhouse generally doesn't expose one in its public API, so we fall
back to regex over the description text (many US postings include a pay range
inline now due to state pay-transparency laws).
"""

import re

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
