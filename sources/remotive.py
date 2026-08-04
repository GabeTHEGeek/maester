"""
remotive.py
Pulls live job listings from Remotive's free public API (no key required).
This is the "search" half of the agent loop: given a query, fetch real,
current listings rather than requiring the user to paste one in.

Remotive docs: https://remotive.com/api-documentation
"""

import re

import requests

from sources._common import normalize_title, strip_html
from utils.extract import extract_salary

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"

# Seniority/level modifiers that make a literal search phrase too narrow —
# Remotive is a small board and a 3-word exact-ish match like "Principal Product
# Manager" can legitimately return zero even when plenty of Senior/Staff/Director
# PM roles exist. Strip these and retry broader rather than silently returning
# nothing; the rubric scorer already judges seniority fit, so it's fine to let
# more listings through and have it flag the level mismatch itself.
LEVEL_WORDS = [
    "principal",
    "staff",
    "senior",
    "junior",
    "associate",
    "director",
    "vp",
    "vice president",
    "chief",
    "head of",
    "group",
    "entry level",
    "entry-level",
    "lead",
]


def _strip_level_words(query: str) -> str:
    q = query
    for word in LEVEL_WORDS:
        q = re.sub(rf"\b{re.escape(word)}\b", "", q, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", q).strip()


def _fetch_raw(query: str, category: str | None) -> list[dict]:
    params = {"search": query}
    if category:
        params["category"] = category
    resp = requests.get(REMOTIVE_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("jobs", [])


def _filter_and_shape(
    raw_jobs: list[dict],
    limit: int,
    exclude_normalized: list[str],
    include_normalized: list[str] | None,
) -> list[dict]:
    jobs = []
    for job in raw_jobs:
        title = job.get("title", "")
        title_normalized = normalize_title(title)

        if include_normalized is not None and not any(
            ok in title_normalized for ok in include_normalized
        ):
            continue
        if any(bad in title_normalized for bad in exclude_normalized):
            continue

        full_description = strip_html(job.get("description", ""))
        salary = job.get("salary", "") or extract_salary(full_description)
        description = full_description[:4000]

        jobs.append(
            {
                "id": job.get("id"),
                "title": title,
                "company": job.get("company_name", ""),
                "url": job.get("url", ""),
                "location": job.get("candidate_required_location", ""),
                "salary": salary,
                "category": job.get("category", ""),
                "published": job.get("publication_date", ""),
                "description": description,
                "source": "remotive",
                "board": "remotive",
            }
        )
        if len(jobs) >= limit:
            break
    return jobs


def search_jobs(
    query: str,
    limit: int = 15,
    category: str | None = "product",
    exclude_titles: list[str] | None = None,
    require_title_keywords: list[str] | None = None,
) -> tuple[list[dict], dict]:
    """
    Search live remote job listings matching `query`.

    `category`: Remotive category slug to try first (e.g. "product"). This is a
    soft preference, not a hard filter — Remotive's own category tagging is
    inconsistent (a real listing can be tagged "all-others"), so if the
    category-scoped search comes back empty, this automatically retries without
    the category restriction before giving up. `exclude_titles`/`require_title_keywords`
    do the real categorization work via the title, not Remotive's tags - the
    caller (app.py) supplies these from the active role_profiles.RoleProfile;
    this module has no opinion of its own about what kind of role is wanted,
    same as every other job source.
    `exclude_titles`: case-insensitive substrings; any listing whose title contains
    one of these is dropped before scoring. Pass an empty list or None to disable.
    `require_title_keywords`: if set, a listing's title must contain at least one
    of these substrings to be kept. Pass None to disable.

    If nothing matches even after dropping the category restriction, retries again
    with seniority/level words stripped from the query (e.g. "Principal Product
    Manager" -> "Product Manager"), since a small board can have zero listings at
    an exact level while still having relevant roles at other levels — the rubric
    scorer judges seniority fit on its own, so it's better to show those.

    Returns (jobs, meta) where meta has:
      {"broadened": bool, "used_query": str, "used_category": str|None, "original_query": str}
    """
    exclude_titles = exclude_titles or []
    exclude_normalized = [normalize_title(t) for t in exclude_titles]
    include_normalized = [normalize_title(t) for t in require_title_keywords] if require_title_keywords else None

    broader_query = _strip_level_words(query)
    has_broader = bool(broader_query) and broader_query.lower() != query.lower()

    # Try, in order: exact query + category, exact query without category,
    # broader query + category, broader query without category.
    attempts = [(query, category)]
    if category:
        attempts.append((query, None))
    if has_broader:
        if category:
            attempts.append((broader_query, category))
        attempts.append((broader_query, None))

    for attempt_query, attempt_category in attempts:
        raw_jobs = _fetch_raw(attempt_query, attempt_category)
        jobs = _filter_and_shape(raw_jobs, limit, exclude_normalized, include_normalized)
        if jobs:
            meta = {
                "broadened": (attempt_query, attempt_category) != attempts[0],
                "used_query": attempt_query,
                "used_category": attempt_category,
                "original_query": query,
            }
            return jobs, meta

    return [], {
        "broadened": False,
        "used_query": query,
        "used_category": category,
        "original_query": query,
    }
