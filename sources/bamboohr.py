"""
bamboohr.py
Pulls live job listings directly from individual companies' BambooHR
careers pages, the same per-company pattern as greenhouse.py/ashby.py.
BambooHR's public, unauthenticated careers API is two calls per company:
  1. https://{subdomain}.bamboohr.com/careers/list — a flat list of open
     postings (id, title, department, location). No description text.
  2. https://{subdomain}.bamboohr.com/careers/{id}/detail — full detail
     for ONE posting (description HTML, compensation, share URL).
Confirmed directly against a real, live BambooHR-hosted careers page
(both endpoint shapes above, field names included).

Docs: https://documentation.bamboohr.com/docs/api-details (that's the
authenticated, per-company API key surface — not used here). The two
endpoints above are the same public, unauthenticated ones BambooHR's own
hosted careers page JS calls to render itself, the same category of
public JSON endpoint Greenhouse/Ashby expose for their own hosted pages.

Unlike Greenhouse/Ashby, the list endpoint alone isn't enough to filter-and
-return — it has no description text to extract salary from or to hand to
the scorer. Detail is fetched only for postings whose TITLE already
matches the query, so total request count stays proportional to actual
matches, not to a board's total posting count.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from sources._common import normalize_title, strip_html
from utils.extract import extract_salary

BAMBOOHR_LIST_URL = "https://{board}.bamboohr.com/careers/list"
BAMBOOHR_DETAIL_URL = "https://{board}.bamboohr.com/careers/{job_id}/detail"

# BambooHR customers span every industry, not just tech — there's no small,
# well-known curated set the way Greenhouse/Ashby have. Left empty on
# purpose; real boards come from the bulk-imported registry (companies.csv)
# via tokens_for_platform("bamboohr"), same as the other bulk-imported
# platforms.
DEFAULT_BOARDS: list = []


def _fetch_list(board_token: str, timeout: int = 15) -> list:
    """Fetch one company's open postings (no description text). Returns []
    on any failure (bad subdomain, board not on BambooHR, network issue)
    rather than raising, so one dead board doesn't kill a multi-board
    search."""
    try:
        resp = requests.get(BAMBOOHR_LIST_URL.format(board=board_token), timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("result", [])
    except Exception:
        return []


def _fetch_detail(board_token: str, job_id, timeout: int = 15) -> dict:
    """Fetch one posting's full detail. Returns {} on any failure — the
    caller falls back to the list-endpoint's bare fields rather than
    dropping the posting entirely over a single flaky detail request."""
    try:
        resp = requests.get(
            BAMBOOHR_DETAIL_URL.format(board=board_token, job_id=job_id), timeout=timeout
        )
        resp.raise_for_status()
        return resp.json().get("result", {}).get("jobOpening", {})
    except Exception:
        return {}


def search_bamboohr(
    query: str,
    boards: list = None,
    limit: int = 15,
    exclude_titles: list = None,
    require_title_keywords: list = None,
) -> tuple:
    """
    Pull postings from each board in `boards` (defaults to DEFAULT_BOARDS,
    normally empty — real boards come from the registry), filter by `query`
    words appearing in the title, then apply the same include/exclude title
    logic as the other sources. Only title-matching postings get a detail
    fetch for the real description/salary/share-URL.

    Returns (jobs, meta) where meta = {"boards_checked": [...], "boards_failed": [...]}.
    """
    if boards is None:
        boards = DEFAULT_BOARDS
    query_words = [w.lower() for w in query.split() if w]

    exclude_normalized = [normalize_title(t) for t in (exclude_titles or [])]
    include_normalized = [normalize_title(t) for t in require_title_keywords] if require_title_keywords else None

    boards_checked = []
    boards_failed = []

    raw_by_board = {}
    with ThreadPoolExecutor(max_workers=min(8, len(boards) or 1)) as executor:
        future_to_board = {executor.submit(_fetch_list, board): board for board in boards}
        for future in as_completed(future_to_board):
            board = future_to_board[future]
            raw_by_board[board] = future.result()

    # Title-matching pass first (cheap, no extra requests) — only postings
    # that pass go on to a detail fetch, per-board capped at `limit`, same
    # as every other source.
    matched_by_board = {}
    for board in boards:
        raw_jobs = raw_by_board.get(board, [])
        if not raw_jobs:
            boards_failed.append(board)
            continue
        boards_checked.append(board)

        matches = []
        for job in raw_jobs:
            title = job.get("jobOpeningName", "")
            title_lower = title.lower()
            if query_words and not any(w in title_lower for w in query_words):
                continue
            title_normalized = normalize_title(title)
            if include_normalized is not None and not any(
                ok in title_normalized for ok in include_normalized
            ):
                continue
            if any(bad in title_normalized for bad in exclude_normalized):
                continue
            matches.append(job)
            if len(matches) >= limit:
                break
        matched_by_board[board] = matches

    # Detail fetch, in parallel, only for postings that already matched —
    # keeps request count proportional to real matches, not total postings.
    detail_targets = [
        (board, job.get("id"))
        for board, matches in matched_by_board.items()
        for job in matches
        if job.get("id")
    ]
    details_by_key = {}
    if detail_targets:
        with ThreadPoolExecutor(max_workers=min(8, len(detail_targets))) as executor:
            future_to_key = {
                executor.submit(_fetch_detail, board, job_id): (board, job_id)
                for board, job_id in detail_targets
            }
            for future in as_completed(future_to_key):
                key = future_to_key[future]
                details_by_key[key] = future.result()

    jobs = []
    for board in boards:
        for job in matched_by_board.get(board, []):
            job_id = job.get("id")
            detail = details_by_key.get((board, job_id), {})

            location_bits = []
            loc = job.get("location") or {}
            if loc.get("city"):
                location_bits.append(loc["city"])
            if loc.get("state"):
                location_bits.append(loc["state"])
            location = ", ".join(location_bits)

            full_description = strip_html(detail.get("description", ""))
            # BambooHR's own "compensation" field is often just the literal
            # string "Negotiated" rather than a real figure - fall back to
            # regex extraction on the description in that case, same as
            # Greenhouse/Ashby do when their own structured field is absent.
            comp = (detail.get("compensation") or "").strip()
            salary = comp if comp and comp.lower() != "negotiated" else extract_salary(full_description)
            description = full_description[:4000]

            url = detail.get("jobOpeningShareUrl") or f"https://{board}.bamboohr.com/careers/{job_id}"

            jobs.append(
                {
                    "id": f"bh_{board}_{job_id}",
                    "title": job.get("jobOpeningName", ""),
                    "company": board,
                    "url": url,
                    "location": location,
                    "salary": salary,
                    "category": job.get("departmentLabel", ""),
                    "published": detail.get("datePosted", ""),
                    "description": description,
                    "source": "bamboohr",
                    "board": board,
                }
            )

    return jobs, {"boards_checked": boards_checked, "boards_failed": boards_failed}
