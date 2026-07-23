"""
fetch_job.py
Pulls readable text out of a job listing URL. Best-effort: strips nav/script/style,
falls back gracefully if the site blocks scraping (many ATS pages do).
"""

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PanelFitBot/0.1; +https://github.com/)"
}


def fetch_job_text(url: str, timeout: int = 10) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    cleaned = "\n".join(lines)

    # Job pages are often bloated with nav/footer boilerplate; cap length so
    # we don't blow the context budget on menus.
    return cleaned[:8000]
