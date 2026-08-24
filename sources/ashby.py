"""
ashby.py
Pulls live job listings directly from individual companies' Ashby job boards,
the same per-company pattern as greenhouse.py. Ashby's public API
is one call per company: api.ashbyhq.com/posting-api/job-board/{board_name}.

Docs: https://developers.ashbyhq.com/reference/jobboardapi-jobboard-info
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from sources._common import normalize_title, strip_html, title_matches_query_word
from utils.extract import extract_salary

ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{board}"

# Many companies embed an Ashby job board on their OWN custom careers domain
# instead of using jobs.ashbyhq.com directly - a "?ashby_jid=<uuid>" query
# param on their own domain (e.g. a real one confirmed directly:
# 1mind.com/careers?ashby_jid=5a6b1b8f-7ad0-4afd-8916-538eb18627d9). Same
# root problem as the Greenhouse embed case in sources/greenhouse.py: the
# embedding page is itself client-rendered, so a generic scrape gets nav
# chrome, not the job. The embed widget's own inline <script> IS present in
# the static HTML though, and sets window.__ashbyBaseJobBoardUrl to the real
# jobs.ashbyhq.com/<board> URL - that board token is what search_ashby needs.
# Unlike Greenhouse there's no single-job-by-id endpoint in Ashby's public
# API, so resolution fetches the whole board and matches by id instead.
_ASHBY_JID_RE = re.compile(r"[?&]ashby_jid=([a-zA-Z0-9-]+)")
_EMBED_BOARD_TOKEN_RE = re.compile(r"ashbyBaseJobBoardUrl\s*=\s*[\"']https?://jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)")

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


def _compensation_to_salary(job: dict) -> str:
    """Ashby sometimes returns a structured compensation summary when
    includeCompensation=true is passed. Fall back to '' if absent — the
    caller will try regex extraction on the description next."""
    comp = job.get("compensation") or {}
    summary = comp.get("compensationTierSummary") or comp.get("summaryComponents")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return ""


def _normalize_job(job: dict, board: str) -> dict:
    """Builds the same result shape search_ashby's loop produces, factored
    out so resolve_embedded_job doesn't duplicate it."""
    full_description = strip_html(job.get("descriptionHtml", ""))
    salary = _compensation_to_salary(job) or extract_salary(full_description)
    return {
        "id": f"ab_{job.get('id')}",
        "title": job.get("title", ""),
        "company": board,
        "url": job.get("jobUrl", "") or job.get("applyUrl", ""),
        "location": job.get("location", ""),
        "salary": salary,
        "category": job.get("department", "") or job.get("team", ""),
        "published": job.get("publishedAt", ""),
        "description": full_description[:4000],
        "source": "ashby",
        "board": board,
    }


def resolve_embedded_job(url: str, timeout: int = 15) -> dict:
    """Resolves an Ashby job embedded on a company's own custom careers
    domain (a "?ashby_jid=<uuid>" URL, not jobs.ashbyhq.com) by recovering
    the board token from the embed widget's own script tag and matching the
    jid against that board's full listing - see the module comment above for
    why. Returns None if the URL doesn't look like an Ashby embed at all (no
    ashby_jid param), the page fetch fails, the embed script isn't found in
    the page's static HTML, or the jid isn't in the board's current listing
    (stale bookmark, closed role) - callers should fall back to a generic
    page fetch in that case, not treat it as fatal."""
    jid_match = _ASHBY_JID_RE.search(url)
    if not jid_match:
        return None
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return None
    board_match = _EMBED_BOARD_TOKEN_RE.search(resp.text)
    if not board_match:
        return None
    board = board_match.group(1)
    jid = jid_match.group(1)
    for job in _fetch_board(board, timeout=timeout):
        if job.get("id") == jid:
            return _normalize_job(job, board)
    return None


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
            title = job.get("title", "")
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

            jobs.append(_normalize_job(job, board))
            board_job_count += 1
            # Per-board cap, not shared globally — see job_source_greenhouse.py
            # for why: a global cap starves companies later in iteration order.
            if board_job_count >= limit:
                break

    return jobs, {"boards_checked": boards_checked, "boards_failed": boards_failed}
