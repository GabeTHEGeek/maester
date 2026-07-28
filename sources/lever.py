"""
job_source_lever.py
Pulls live job listings directly from individual companies' Lever job boards,
the same per-company pattern as job_source_greenhouse.py and job_source_ashby.py.
Lever's public API is one call per company, no auth required:

    GET https://api.lever.co/v0/postings/{company}?mode=json

Docs: https://github.com/lever/postings-api
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from utils.extract import extract_salary

LEVER_URL = "https://api.lever.co/v0/postings/{company}"

# Company slugs as used in their Lever job board URL (jobs.lever.co/{slug}).
# Verify at that URL if a company you expect isn't showing up, or if a token
# below has gone stale — Lever doesn't publish a customer list, so these are
# only as good as whoever last checked them.
DEFAULT_BOARDS = [
    "netflix",
    "palantir",
    "attentive",
    "benchling",
    "anduril",
]


def _fetch_board(board_token: str, timeout: int = 15) -> list:
    """Fetch all postings from one company's Lever board. Returns [] on any
    failure (bad token, board not on Lever, network issue) rather than
    raising, so one dead board doesn't kill a multi-board search."""
    try:
        resp = requests.get(
            LEVER_URL.format(company=board_token),
            params={"mode": "json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        # Lever returns a bare JSON array, not a wrapped object like
        # Greenhouse/Ashby — an unexpected shape here (e.g. an error page
        # that still returned 200) means treat it as no postings found.
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize(text: str) -> str:
    return re.sub(r"[\s\-]+", "", text.lower()).strip()


def _full_description(job: dict) -> str:
    """Lever splits content across description + descriptionPlain + a 'lists'
    array of extra sections (Responsibilities, Requirements, etc.) — join
    all of it so extraction (salary, panel context) sees the complete JD,
    not just the intro paragraph."""
    parts = [job.get("descriptionPlain") or _strip_html(job.get("description", ""))]
    for section in job.get("lists") or []:
        section_title = section.get("text", "")
        section_content = _strip_html(section.get("content", ""))
        if section_content:
            parts.append(f"{section_title}: {section_content}" if section_title else section_content)
    additional = job.get("additionalPlain") or _strip_html(job.get("additional", ""))
    if additional:
        parts.append(additional)
    return "\n\n".join(p for p in parts if p)


def _salary_from_categories(job: dict) -> str:
    """Lever sometimes includes a structured salary range; fall back to
    regex extraction over the full description otherwise."""
    salary_range = job.get("salaryRange") or {}
    lo, hi = salary_range.get("min"), salary_range.get("max")
    currency = salary_range.get("currency", "USD")
    if lo and hi:
        return f"{currency} {lo:,} - {hi:,}"
    return ""


def search_lever(
    query: str,
    boards: list = None,
    limit: int = 15,
    exclude_titles: list = None,
    require_title_keywords: list = None,
) -> tuple:
    """
    Pull postings from each board in `boards` (defaults to DEFAULT_BOARDS),
    filter by `query` words appearing in the title, then apply the same
    include/exclude title logic as the other sources.

    Returns (jobs, meta) where meta = {"boards_checked": [...], "boards_failed": [...]}.
    """
    if boards is None:
        boards = DEFAULT_BOARDS
    query_words = [w.lower() for w in query.split() if w]

    exclude_normalized = [_normalize(t) for t in (exclude_titles or [])]
    include_normalized = [_normalize(t) for t in require_title_keywords] if require_title_keywords else None

    jobs = []
    boards_checked = []
    boards_failed = []

    raw_by_board = {}
    with ThreadPoolExecutor(max_workers=min(8, len(boards) or 1)) as executor:
        future_to_board = {executor.submit(_fetch_board, board): board for board in boards}
        for future in as_completed(future_to_board):
            board = future_to_board[future]
            raw_by_board[board] = future.result()

    for board in boards:
        raw_jobs = raw_by_board.get(board, [])
        if not raw_jobs:
            boards_failed.append(board)
            continue
        boards_checked.append(board)

        board_job_count = 0
        for job in raw_jobs:
            title = job.get("text", "")
            title_lower = title.lower()

            if query_words and not any(w in title_lower for w in query_words):
                continue

            title_normalized = _normalize(title)
            if include_normalized is not None and not any(
                ok in title_normalized for ok in include_normalized
            ):
                continue
            if any(bad in title_normalized for bad in exclude_normalized):
                continue

            categories = job.get("categories") or {}
            location = categories.get("location", "")

            full_description = _full_description(job)
            salary = _salary_from_categories(job) or extract_salary(full_description)
            description = full_description[:4000]

            jobs.append(
                {
                    "id": f"lv_{job.get('id')}",
                    "title": title,
                    "company": board,
                    "url": job.get("hostedUrl", "") or job.get("applyUrl", ""),
                    "location": location,
                    "salary": salary,
                    "category": categories.get("department", "") or categories.get("team", ""),
                    "published": job.get("createdAt", ""),
                    "description": description,
                    "source": "lever",
                    "board": board,
                }
            )
            board_job_count += 1
            # Per-board cap, not shared globally — see job_source_greenhouse.py
            # for why: a global cap starves companies later in iteration order.
            if board_job_count >= limit:
                break

    return jobs, {"boards_checked": boards_checked, "boards_failed": boards_failed}
