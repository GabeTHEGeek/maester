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

Some ATS platforms (Ashby in particular) render job pages as a JS-only
single-page app — a plain requests+BeautifulSoup fetch only sees a "You need
to enable JavaScript to run this app" placeholder, not the real content, even
though the posting is genuinely live and full of detail. Confirmed directly:
a real, active Ashby posting returned almost no body text this way, which the
liveness check correctly (but misleadingly) flagged as "very little content."
The actual job description is still recoverable without a full headless
browser, though — it's duplicated into Open Graph / Twitter Card meta tags,
meant for social link previews, and those ARE present in the initial HTML.
Falling back to those when the body text comes back too thin fixes this for
Ashby and any other platform following the same OG-meta pattern.

Also does a best-effort posting-liveness check, modeled on signals used by
career-ops's scanner: a redirect to an error page (Greenhouse's pattern when
a role closes), known "this posting is closed" phrases, or suspiciously thin
content where a real job description should be. This matters specifically
for manually-pasted URLs — a bookmarked or search-engine-cached link can be
for a role that's since closed, and scoring/tailoring against a dead posting
wastes the same time this whole tool exists to save.
"""

import re
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PanelFitBot/0.1; +https://github.com/)"
}

# A real desktop Chrome UA, used only for the render fallback below - some
# client-rendered career sites (confirmed: Medallia's Jibe/iCIMS-powered
# site) return a flat 403 to the generic bot UA above, but load normally for
# something that looks like an actual browser.
_REALISTIC_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# All Playwright work for this module's render fallback runs on one
# dedicated background thread, same reasoning and same pattern as
# browser/autofill.py's _executor: Playwright's sync API is thread-bound to
# whichever OS thread created it, and Streamlit runs each script rerun on a
# fresh thread, so touching a Playwright object from the caller's (ever-
# changing) thread directly crashes on the second use. This is a SEPARATE
# executor/browser from autofill.py's - that one is deliberately visible
# (headless=False) for manual review; this one is headless and silent,
# purely for reading text, and popping a visible window open every time
# someone pastes a URL to score would be a jarring, unwanted surprise.
_render_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="maester-fetch-render")
_render_playwright = None
_render_browser = None


def _get_render_browser():
    global _render_playwright, _render_browser
    if _render_browser is not None and not _render_browser.is_connected():
        _render_playwright = None
        _render_browser = None
    if _render_browser is None:
        _render_playwright = sync_playwright().start()
        _render_browser = _render_playwright.chromium.launch(headless=True)
    return _render_browser


def _render_text_job(url: str, timeout_ms: int) -> str:
    browser = _get_render_browser()
    context = browser.new_context(viewport={"width": 1600, "height": 1000}, user_agent=_REALISTIC_USER_AGENT)
    try:
        page = context.new_page()
        page.goto(url, wait_until="load", timeout=timeout_ms)
        page.wait_for_timeout(2000)
        text = page.inner_text("body")
    finally:
        context.close()
    return text


def fetch_rendered_text(url: str, timeout_ms: int = 20000) -> str:
    """Renders the page with a real (headless) browser and a realistic
    desktop User-Agent, then reads the DOM's actual text - the fallback for
    client-rendered career pages a plain requests+BeautifulSoup fetch can't
    see. Confirmed directly against a real listing: Medallia's Jibe/iCIMS-
    powered career site returns only nav/footer/EEO-legal boilerplate to a
    static scrape (real job description included), and 403s the generic bot
    User-Agent outright. Thin wrapper: submits to _render_executor so every
    Playwright object this touches stays on one dedicated thread for the
    life of the process (see the comment above _get_render_browser)."""
    return _render_executor.submit(_render_text_job, url, timeout_ms).result()


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

# Below this length, the body text is almost certainly a JS-app placeholder,
# not real content — worth trying the meta-tag fallback rather than trusting
# it as-is.
_THIN_CONTENT_THRESHOLD = 300


def _extract_meta_description(soup: BeautifulSoup) -> str:
    """Recovers job description text from Open Graph / Twitter Card meta
    tags when the visible body text is too thin to be real (a JS-only SPA
    that never rendered). These tags exist specifically so links preview
    correctly when shared on social platforms, so ATS systems that are
    otherwise JS-only tend to still populate them with the full JD."""
    for attrs in ({"property": "og:description"}, {"name": "twitter:description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


_TITLE_SUFFIX_RE = re.compile(r"\s*[|\-–—]\s*[^|\-–—]*$")


def _extract_page_title(soup: BeautifulSoup) -> str:
    """Best-effort job title for a manually-pasted URL with no other source
    of one (e.g. Search & Score's "paste a URL" path, which has no search-
    result metadata to draw a title from the way a real search does). Most
    ATS <title> tags are "{Job Title} - {Company}" or "{Job Title} | {Company}",
    so strip one trailing "- Company"/"| Company" segment if present - a
    rough heuristic, not a guarantee, but far better than "Unknown role"
    for the common case."""
    if not soup.title or not soup.title.string:
        return ""
    raw = soup.title.string.strip()
    return _TITLE_SUFFIX_RE.sub("", raw).strip() or raw


# Real job descriptions overwhelmingly use at least one of these, regardless
# of ATS platform or exact template wording - if NONE of them appear
# anywhere in a scrape, that's a strong signal the page is nav/footer/EEO-
# legal boilerplate, not a real posting, even when the raw character count
# clears _THIN_CONTENT_THRESHOLD (confirmed directly: Medallia's scrape came
# back at 2198 chars, well above the threshold, but every one of those
# characters was "Skip to Main Content" / "Equal Opportunity Employer" /
# "Accessibility Statement" boilerplate - a length-only check missed it).
_JD_SIGNAL_PHRASES = [
    "responsibilit", "requirement", "qualification", "what you'll do",
    "who you are", "about the role", "about this role",
    "we are seeking", "years of experience",
]

# Real JDs run long - a genuine short one that happens to avoid all the
# signal phrases above is a plausible false positive, but a LONG page that
# still trips zero of them essentially never is, so the render fallback
# below only fires under this length too, not unconditionally.
_BOILERPLATE_LENGTH_CAP = 4000


def _looks_like_real_job_description(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in _JD_SIGNAL_PHRASES)


def fetch_job_page(url: str, timeout: int = 10) -> dict:
    """Fetches and cleans a job page, returning the text, the final URL
    after redirects (needed for liveness checking - e.g. Greenhouse
    redirects to a URL containing 'error=true' when a role has closed),
    and a best-effort title parsed from the page's own <title> tag."""
    resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Meta tags and <title> need to be read before the <head>'s contents get
    # stripped below, and BeautifulSoup's parsed tree is shared, so grab
    # both first.
    meta_description = _extract_meta_description(soup)
    page_title = _extract_page_title(soup)

    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    cleaned = "\n".join(lines)

    if len(cleaned) < _THIN_CONTENT_THRESHOLD and len(meta_description) > len(cleaned):
        cleaned = meta_description

    # Static scrape came back boilerplate-only (nav/footer/EEO-legal text,
    # no real job content) - a genuinely client-rendered page a plain
    # requests+BeautifulSoup fetch can never see correctly, regardless of
    # length. Try a real (headless) browser render instead; if THAT also
    # fails or comes back short, keep the static scrape rather than lose it
    # entirely - a partial/wrong-looking result beats a hard failure here.
    if len(cleaned) < _BOILERPLATE_LENGTH_CAP and not _looks_like_real_job_description(cleaned):
        try:
            rendered = fetch_rendered_text(url)
            rendered_lines = [line.strip() for line in rendered.splitlines()]
            rendered_cleaned = "\n".join(line for line in rendered_lines if line)
            if len(rendered_cleaned) > len(cleaned):
                cleaned = rendered_cleaned
        except Exception:
            pass

    # Generous cap now that forms (the biggest source of bloat) are stripped —
    # this is a safety margin, not the primary defense against noise.
    return {"text": cleaned[:15000], "final_url": resp.url, "title": page_title}


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
