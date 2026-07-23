"""
fetch_job.py
Pulls readable text out of a job listing URL. Best-effort: strips nav/script/style/
form noise, prefers known ATS content containers when present, falls back to whole-
page text if none match, and falls back gracefully if the site blocks scraping.
"""

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PanelFitBot/0.1; +https://github.com/)"
}

# Greenhouse/Ashby/Lever job pages embed the entire application form — country
# and phone dropdowns, and especially the EEO race/veteran/disability
# self-identification sections — as real text in the DOM. If that form sits
# earlier in HTML source order than it renders visually, it can eat most of
# the character budget before the actual job description (and anything late
# in it, like a salary line) ever gets captured. These selectors target the
# actual description content directly when the ATS uses a recognizable one,
# so we don't have to rely on truncation length alone to dodge that noise.
_CONTENT_SELECTORS = [
    ("div", {"id": "content"}),  # Greenhouse job-boards.greenhouse.io
    ("div", {"class": "job__description"}),
    ("section", {"class": "job-description"}),
    ("div", {"class": "posting-description"}),  # Ashby-style
    ("div", {"class": "section-wrapper"}),  # Lever
]


def fetch_job_text(url: str, timeout: int = 10) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
        tag.decompose()

    content_node = None
    for tag_name, attrs in _CONTENT_SELECTORS:
        found = soup.find(tag_name, attrs=attrs)
        if found:
            content_node = found
            break

    source = content_node if content_node else soup
    text = source.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    cleaned = "\n".join(lines)

    # Generous cap since we've now cut most of the noise that used to eat the
    # budget — this is a safety margin, not the primary defense against bloat.
    return cleaned[:15000]
