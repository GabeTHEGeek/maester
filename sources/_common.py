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


# Crude suffix-stripping stemmer - just enough to bridge common word-form
# mismatches ("engineering" vs "engineer", "managers" vs "manager") without
# pulling in a real NLP dependency. Longest/most-specific suffixes checked
# first so "managers" strips via "ers" (-> "manag") rather than the shorter
# "s" catching it first and leaving "manager" unstemmed.
_STEM_SUFFIXES = ("ing", "ers", "er", "es", "s")


def _stem(word: str) -> str:
    for suffix in _STEM_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def title_matches_query_word(query_word: str, title_lower: str) -> bool:
    """True if `query_word` (already lowercased) is a reasonable match
    against `title_lower` (already lowercased). Checks the exact substring
    first (unchanged prior behavior - never weakens a match that already
    worked), then falls back to comparing STEMMED forms so a natural
    word-form mismatch doesn't silently exclude a real listing.

    Confirmed directly on a real search: querying "engineering" against
    Anthropic's live Greenhouse board returned 0-4 results depending on
    role profile, even though 85+ genuinely matching listings ("Software
    Engineer," "Data Engineer," etc.) were on the board - "engineering" is
    simply never a substring of "engineer," the word almost every real
    title actually uses. Stemming both sides ("engineering" and "engineer"
    both reduce toward "engine") lets that match without a full NLP
    dependency; the len>=3 stem-length guard keeps short/common suffixes
    like "-s" from producing noisy accidental matches."""
    if query_word in title_lower:
        return True
    stemmed_query = _stem(query_word)
    if len(stemmed_query) < 3:
        return False
    return any(
        stemmed_query in _stem(title_word) or _stem(title_word) in stemmed_query
        for title_word in title_lower.split()
    )
