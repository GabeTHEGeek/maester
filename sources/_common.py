"""
sources/_common.py
Tiny, pure helpers shared across every job board integration in this
package. Kept to exactly what's actually identical across all of them
(HTML stripping and title normalization) — the surrounding fetch/parse
code differs meaningfully per vendor (different API shapes: some are one
call, BambooHR is two with a detail-fetch stage, Gem needs a secondary
page scrape), so that part is intentionally NOT unified here.
"""

import re


def strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_title(text: str) -> str:
    return re.sub(r"[\s\-]+", "", text.lower()).strip()
