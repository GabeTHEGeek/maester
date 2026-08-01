"""
greenhouse.py
Pulls live job listings directly from individual companies' Greenhouse job boards.

Unlike Remotive, Greenhouse has no aggregate search endpoint — each company has
its own board at boards-api.greenhouse.io/v1/boards/{board_token}/jobs. We fetch
every posting from each configured board and filter client-side, which sidesteps
the full-text-match noise problem entirely (Greenhouse just gives us a flat list
of real postings per company; there's no "search" to fool).

Docs: https://developers.greenhouse.io/job-board.html
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from sources._common import normalize_title, strip_html
from utils.extract import extract_salary

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"

# Company board tokens to check by default. These are the slugs Greenhouse uses
# in the URL, which don't always match the company's public name — verify at
# https://boards.greenhouse.io/{token} if a company you expect isn't showing up,
# or if a token below has gone stale.
DEFAULT_BOARDS = [
    "anthropic",
    "openai",
    "databricks",
    "notion",
    "airtable",
    "ramp",
    "scaleai",
    "webflow",
    "vercel",
    "mercury",
]


def _fetch_board(board_token: str, timeout: int = 15) -> list[dict]:
    """Fetch all postings from one company's Greenhouse board. Returns [] on any failure
    (bad token, board not on Greenhouse, network issue) rather than raising, so one
    dead board doesn't kill a multi-board search."""
    try:
        resp = requests.get(
            GREENHOUSE_URL.format(board=board_token),
            params={"content": "true"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("jobs", [])
    except Exception:
        return []




def search_greenhouse(
    query: str,
    boards: list[str] | None = None,
    limit: int = 15,
    exclude_titles: list[str] | None = None,
    require_title_keywords: list[str] | None = None,
) -> tuple[list[dict], dict]:
    """
    Pull postings from each board in `boards` (defaults to DEFAULT_BOARDS), filter
    by `query` words appearing in the title, then apply the same include/exclude
    title logic as the Remotive source.

    Returns (jobs, meta) where meta = {"boards_checked": [...], "boards_failed": [...]}
    so the caller can show which boards actually returned data.
    """
    if boards is None:
        boards = DEFAULT_BOARDS
    query_words = [w.lower() for w in query.split() if w]

    exclude_normalized = [normalize_title(t) for t in (exclude_titles or [])]
    include_normalized = [normalize_title(t) for t in require_title_keywords] if require_title_keywords else None

    jobs = []
    boards_checked = []
    boards_failed = []

    # Fetch every board's postings in parallel — this is the network-bound
    # part, and boards don't depend on each other, so there's no reason to
    # wait on them one at a time. Filtering afterward is cheap and stays
    # sequential (in board order) so results are deterministic.
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

            # Query match: at least one query word appears in the title (loose,
            # since Greenhouse boards are usually small enough that over-matching
            # isn't a real problem the way it was with Remotive's full-text search).
            if query_words and not any(w in title_lower for w in query_words):
                continue

            title_normalized = normalize_title(title)
            if include_normalized is not None and not any(
                ok in title_normalized for ok in include_normalized
            ):
                continue
            if any(bad in title_normalized for bad in exclude_normalized):
                continue

            location = ""
            if job.get("location") and job["location"].get("name"):
                location = job["location"]["name"]

            full_description = strip_html(job.get("content", ""))

            # Some Greenhouse boards expose a structured pay range (pay-transparency
            # compliance); most don't. Fall back to scanning the FULL description
            # text (before truncation — comp info often sits late in a long JD,
            # after the company blurb and requirements).
            salary = ""
            pay_ranges = job.get("pay_input_ranges") or []
            if pay_ranges:
                r = pay_ranges[0]
                lo, hi = r.get("min_cents"), r.get("max_cents")
                currency = r.get("currency_type", "USD")
                if lo and hi:
                    salary = f"{currency} {lo // 100:,} - {hi // 100:,}"
            if not salary:
                salary = extract_salary(full_description)

            description = full_description[:4000]

            jobs.append(
                {
                    "id": f"gh_{job.get('id')}",
                    "title": title,
                    "company": board,
                    "url": job.get("absolute_url", ""),
                    "location": location,
                    "salary": salary,
                    "category": "",
                    "published": job.get("updated_at", ""),
                    "description": description,
                    "source": "greenhouse",
                    "board": board,
                }
            )
            board_job_count += 1
            # Per-board cap, not a shared global one — a global cap meant
            # companies later in iteration order could get zero results
            # purely from bad luck in list ordering, even with plenty of
            # relevant openings. Each board gets its own fair shot up to
            # `limit`, so more companies selected means more total results,
            # not fewer per company.
            if board_job_count >= limit:
                break

    return jobs, {"boards_checked": boards_checked, "boards_failed": boards_failed}
