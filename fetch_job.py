"""
fetch_job.py
Pulls readable text out of a job listing URL. Best-effort: strips nav/script/
style/form noise (the biggest source of truncation problems — Greenhouse/Ashby/
Lever pages embed the entire application form, including the EEO race/veteran/
disability self-identification sections, as real DOM text, and that can eat
most of the character budget before the real job description is ever reached),
then keeps the rest of the page as plain text with a generous cap. Falls back
gracefully if the site blocks scraping.

An earlier version tried to target known ATS content containers directly
(e.g. div#content) to avoid relying on cap length alone, but that selector
was a guess never verified against Greenhouse's actual template, and an
unverified selector risks silently matching some smaller, wrong element and
cutting off real content with no visible error. Simpler and more reliable to
strip the known noise and keep everything else.

Also does a best-effort posting-liveness check, modeled on signals used by
career-ops's scanner: a redirect to an error page (Greenhouse's pattern when
a role closes), known "this posting is closed" phrases, or suspiciously thin
content where a real job description should be. This matters specifically
for manually-pasted URLs — a bookmarked or search-engine-cached link can be
for a role that's since closed, and scoring/tailoring against a dead posting
wastes the same time this whole tool exists to save.
"""

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PanelFitBot/0.1; +https://github.com/)"
}

_EXPIRED_PHRASES = [
    "no longer accepting applications",
    "no longer available",
    "position has been filled",
    "this job has expired",
    "job posting has closed",
    "job no longer available",
    "this position is no longer",
    "posting has been removed",
]


def fetch_job_page(url: str, timeout: int = 10) -> dict:
    """Fetches and cleans a job page, returning both the text and the final
    URL after redirects — the latter is needed for liveness checking (e.g.
    Greenhouse redirects to a URL containing 'error=true' when a role has
    closed)."""
    resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    cleaned = "\n".join(lines)

    # Generous cap now that forms (the biggest source of bloat) are stripped —
    # this is a safety margin, not the primary defense against noise.
    return {"text": cleaned[:15000], "final_url": resp.url}


def fetch_job_text(url: str, timeout: int = 10) -> str:
    """Backward-compatible wrapper for callers that only want the text."""
    return fetch_job_page(url, timeout)["text"]


def check_liveness(text: str, final_url: str = "") -> dict:
    """Best-effort classification of whether a posting still looks active.
    Never treated as definitive proof either way — a signal to surface to
    the user, not a hard block, since these heuristics can have false
    positives (a legitimately short JD, an unusual but real phrase match)."""
    lower_text = (text or "").lower()

    if "error=true" in (final_url or "").lower():
        return {
            "status": "expired",
            "reason": "The page redirected to an error URL — the pattern Greenhouse uses when a role has closed.",
        }

    for phrase in _EXPIRED_PHRASES:
        if phrase in lower_text:
            return {"status": "expired", "reason": f'The page contains the phrase "{phrase}".'}

    if len(lower_text.strip()) < 300:
        return {
            "status": "unknown",
            "reason": "Very little content came back from this page — could be a closed posting, a scraping block, or a slow-loading page. Worth checking the listing directly before trusting the evaluation.",
        }

    return {"status": "active", "reason": ""}
