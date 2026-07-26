"""
job_source_ashby.py
Pulls live job listings directly from individual companies' Ashby job boards,
the same per-company pattern as job_source_greenhouse.py. Ashby's public API
is one call per company: api.ashbyhq.com/posting-api/job-board/{board_name}.

Docs: https://developers.ashbyhq.com/reference/jobboardapi-jobboard-info
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from extract import extract_salary

ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{board}"

# Company board names as used in their Ashby job board URL
# (jobs.ashbyhq.com/{token}). Verify at that URL if a company you expect
# isn't showing up, or if a token below has gone stale — Ashby adoption
# shifts over time and this list isn't guaranteed current.
DEFAULT_BOARDS = [
    "ramp",
    "linear",
    "notion",
    "retool",
    "replit",
    "watershed",
    "runway",
]


def _fetch_board(board_token: str, timeout: int = 15) -> list[dict]:
    """Fetch all postings from one company's Ashby board. Returns [] on any
    failure (bad token, board not on Ashby, network issue) rather than
    raising, so one dead board doesn't kill a multi-board search."""
    try:
        resp = requests.get(
            ASHBY_URL.format(board=board_token),
            params={"includeCompensation": "true"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("jobs", [])
    except Exception:
        return []


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize(text: str) -> str:
    return re.sub(r"[\s\-]+", "", text.lower()).strip()


def _compensation_to_salary(job: dict) -> str:
    """Ashby sometimes returns a structured compensation summary when
    includeCompensation=true is passed. Fall back to '' if absent — the
    caller will try regex extraction on the description next."""
    comp = job.get("compensation") or {}
    summary = comp.get("compensationTierSummary") or comp.get("summaryComponents")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return ""


def search_ashby(
    query: str,
    boards: list[str] | None = None,
    limit: int = 15,
    exclude_titles: list[str] | None = None,
    require_title_keywords: list[str] | None = None,
) -> tuple[list[dict], dict]:
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
            title = job.get("title", "")
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

            full_description = _strip_html(job.get("descriptionHtml", ""))
            salary = _compensation_to_salary(job) or extract_salary(full_description)
            description = full_description[:4000]

            jobs.append(
                {
                    "id": f"ab_{job.get('id')}",
                    "title": title,
                    "company": board,
                    "url": job.get("jobUrl", "") or job.get("applyUrl", ""),
                    "location": job.get("location", ""),
                    "salary": salary,
                    "category": job.get("department", "") or job.get("team", ""),
                    "published": job.get("publishedAt", ""),
                    "description": description,
                    "source": "ashby",
                    "board": board,
                }
            )
            board_job_count += 1
            # Per-board cap, not shared globally — see job_source_greenhouse.py
            # for why: a global cap starves companies later in iteration order.
            if board_job_count >= limit:
                break

    return jobs, {"boards_checked": boards_checked, "boards_failed": boards_failed}
