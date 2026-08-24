"""
gem.py
Pulls live job listings from individual companies' Gem-hosted job boards
(jobs.gem.com/{board}), the same per-company, one-call-per-board pattern as
greenhouse.py/ashby.py.

Uses Gem's own public, documented job-board REST API
(api.gem.com/job_board/v0/{vanity_url_path}/job_posts) - confirmed directly,
against multiple real boards, that this returns EVERY posting for a board in
one unauthenticated GET, full plain-text content included (`content_plain`),
no API key or employer credentials needed at all. This replaced an earlier,
more complicated two-step approach (a GraphQL listing call for title/
location, then a second per-job fetch for description text) built on an
earlier, incorrect assumption that Gem's REST API required employer
credentials - it doesn't, for this specific public job-board endpoint, only
for a *different*, permissioned employer-integration surface. Confirmed
directly this was worth fixing: Gem's job DETAIL *pages* (jobs.gem.com/...)
are entirely client-rendered - a candidate's browser fills them in via JS
after load, so scraping the page's raw HTML (what the earlier per-job fetch
did) got almost nothing, which was producing real listings that scored as
"generic title with no details" in the deep-dive panel. This endpoint sidesteps
that problem entirely by returning the real content directly as data.

Deliberately still NOT using any endpoint that needs the employer's own
account/API key (api.gem.com's *other*, permissioned surfaces) - only this
public job-board listing endpoint, the same data a candidate's own browser
already receives when it renders the public careers page.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from sources._common import normalize_title, title_matches_query_word
from utils.extract import extract_salary

GEM_JOB_POSTS_URL = "https://api.gem.com/job_board/v0/{board}/job_posts"

# Company board names as used in their Gem job board URL (jobs.gem.com/{token}).
# Verify at that URL if a company you expect isn't showing up.
DEFAULT_BOARDS = [
    "retool",
]


def _fetch_board(board_token: str, timeout: int = 15) -> list:
    """Fetch every posting (full content included) for one company's Gem
    board. Returns [] on any failure (bad token, board not on Gem, network
    issue) rather than raising, so one dead board doesn't kill a
    multi-board search."""
    try:
        resp = requests.get(GEM_JOB_POSTS_URL.format(board=board_token), timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _location_string(job: dict) -> str:
    location = job.get("location") or {}
    name = location.get("name", "")
    if job.get("location_type") == "remote" and "remote" not in name.lower():
        name = f"{name} (Remote)".strip()
    return name


def search_gem(
    query: str,
    boards: list = None,
    limit: int = 15,
    exclude_titles: list = None,
    require_title_keywords: list = None,
) -> tuple:
    """
    Pull postings from each board in `boards` (defaults to DEFAULT_BOARDS),
    filter by `query` words appearing in the title, then apply the same
    include/exclude title logic as the other sources. Every posting's full
    content comes back in the same listing call - no second per-job fetch
    needed.

    Returns (jobs, meta) where meta = {"boards_checked": [...], "boards_failed": [...]}.
    """
    if boards is None:
        boards = DEFAULT_BOARDS
    query_words = [w.lower() for w in query.split() if w]

    exclude_normalized = [normalize_title(t) for t in (exclude_titles or [])]
    include_normalized = [normalize_title(t) for t in require_title_keywords] if require_title_keywords else None

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
            title = (job.get("title") or "").strip()
            title_lower = title.lower()

            if query_words and not any(title_matches_query_word(w, title_lower) for w in query_words):
                continue

            title_normalized = normalize_title(title)
            if include_normalized is not None and not any(
                ok in title_normalized for ok in include_normalized
            ):
                continue
            if any(bad in title_normalized for bad in exclude_normalized):
                continue

            full_description = (job.get("content_plain") or "").strip()
            salary = extract_salary(full_description)
            departments = job.get("departments") or []
            department = departments[0].get("name", "") if departments else ""
            job_id = job.get("id", "")

            jobs.append(
                {
                    "id": f"gem_{board}_{job_id}",
                    "title": title,
                    "company": board,
                    "url": job.get("absolute_url", "") or f"https://jobs.gem.com/{board}/{job_id}",
                    "location": _location_string(job),
                    "salary": salary,
                    "category": department,
                    "published": job.get("first_published_at", ""),
                    "description": full_description[:4000],
                    "source": "gem",
                    "board": board,
                }
            )
            board_job_count += 1
            # Per-board cap, not a shared global one - see
            # sources/greenhouse.py for why: a global cap starves companies
            # later in iteration order.
            if board_job_count >= limit:
                break

    return jobs, {"boards_checked": boards_checked, "boards_failed": boards_failed}
