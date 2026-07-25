"""
job_source_gem.py
Pulls live job listings from individual companies' Gem-hosted job boards
(jobs.gem.com/{board}). Gem exposes a public GraphQL batch endpoint for the
job listing (title, location, department) but full descriptions require a
second, per-job call whose exact schema isn't documented publicly. Rather
than guess at that shape, this reuses fetch_job.fetch_job_text() — the same
generic, already-hardened page scraper used for manually-pasted URLs — on
each title-matching job's page to get the real description text. That means
one extra HTTP request per matching job (not per job on the board — title
filtering happens first, on the cheap listing call), which is the same
tradeoff Greenhouse/Ashby avoid by including full content in one call, but
Gem's API doesn't offer that.
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from extract import extract_salary
from fetch_job import fetch_job_text

GEM_GRAPHQL_URL = "https://jobs.gem.com/api/public/graphql/batch"

# Company board names as used in their Gem job board URL (jobs.gem.com/{token}).
# Verify at that URL if a company you expect isn't showing up.
DEFAULT_BOARDS = [
    "retool",
]

_JOB_BOARD_LIST_QUERY = """query JobBoardList($boardId: String!) {
  oatsExternalJobPostings(boardId: $boardId) {
    jobPostings {
      id
      extId
      title
      locations { id name city isoCountry isRemote }
      job { id department { id name } locationType employmentType }
    }
  }
  jobBoardExternal(vanityUrlPath: $boardId) { id teamDisplayName }
}"""


def _fetch_board(board_token: str, timeout: int = 15) -> list:
    """Fetch the job listing (title/location/department, no description) for
    one company's Gem board. Returns [] on any failure rather than raising,
    so one dead board doesn't kill a multi-board search."""
    try:
        payload = [{
            "operationName": "JobBoardList",
            "variables": {"boardId": board_token},
            "query": _JOB_BOARD_LIST_QUERY,
        }]
        resp = requests.post(
            GEM_GRAPHQL_URL,
            json=payload,
            headers={"Content-Type": "application/json", "batch": "true"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()[0].get("data", {})
        return data.get("oatsExternalJobPostings", {}).get("jobPostings", []) or []
    except Exception:
        return []


def _normalize(text: str) -> str:
    return re.sub(r"[\s\-]+", "", text.lower()).strip()


def _location_string(locations: list) -> str:
    if not locations:
        return ""
    loc = locations[0]
    parts = [p for p in [loc.get("city"), loc.get("isoCountry")] if p]
    label = ", ".join(parts) or loc.get("name", "")
    if loc.get("isRemote"):
        label = f"{label} (Remote)".strip()
    return label


def search_gem(
    query: str,
    boards: list = None,
    limit: int = 15,
    exclude_titles: list = None,
    require_title_keywords: list = None,
) -> tuple:
    """
    Pull postings from each board in `boards` (defaults to DEFAULT_BOARDS),
    filter by `query` words and title allow/blocklists on the cheap listing
    call, then fetch full description text only for jobs that pass — one
    extra request per matching job, not per job on the board.

    Returns (jobs, meta) where meta = {"boards_checked": [...], "boards_failed": [...]}.
    """
    boards = boards or DEFAULT_BOARDS
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

        matched = []
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

            matched.append(job)
            if len(matched) >= limit:
                break

        # Fetch full description text only for jobs that passed title
        # filtering — keeps the per-job page-fetch cost proportional to
        # relevant results, not every posting on the board.
        def _enrich(job):
            ext_id = job.get("extId") or job.get("id")
            url = f"https://jobs.gem.com/{board}/{ext_id}"
            try:
                description = fetch_job_text(url)
            except Exception:
                description = ""
            salary = extract_salary(description)
            job_info = job.get("job") or {}
            department = (job_info.get("department") or {}).get("name", "")
            return {
                "id": f"gem_{board}_{ext_id}",
                "title": job.get("title", ""),
                "company": board,
                "url": url,
                "location": _location_string(job.get("locations", [])),
                "salary": salary,
                "category": department,
                "published": "",
                "description": description[:4000],
                "source": "gem",
                "board": board,
            }

        if matched:
            with ThreadPoolExecutor(max_workers=min(5, len(matched))) as executor:
                for result in executor.map(_enrich, matched):
                    jobs.append(result)

    return jobs, {"boards_checked": boards_checked, "boards_failed": boards_failed}
