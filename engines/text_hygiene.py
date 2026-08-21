"""
engines/text_hygiene.py
Shared post-generation cleanup backstops for anything an LLM writes in the
candidate's own voice — cover letters and job-application custom-question
answers. Both are free text a model drafts on the candidate's behalf, and
both are held to the same "zero em dashes, no AI-sounding filler phrases"
bar, but a prompt instruction is a request, not a guarantee (the recurring
lesson in CLAUDE.md). This started as private functions inside
engines/tailor.py for the cover letter only; pulled out here once
browser/fields.py's custom-answer drafts needed the identical backstop and
duplicating it risked drifting out of sync — same reasoning that already
moved strip_html/normalize_title/extract_json into sources/_common.py.
"""

import re

# Phrases the prompt already explicitly bans by name but that have been
# observed slipping through anyway ("I'm drawn to" specifically was
# reported in real use). Stays intentionally short — full-sentence phrases
# worth a dedicated rewrite pass, not every word in the larger banned-
# vocabulary list in engines/tailor.py's prompt text.
#
# Regexes, not plain substrings: a real generated letter used "I'm
# PARTICULARLY drawn to Neighborly's mission..." - the plain substring
# check for "i'm drawn to" never matches with a word inserted in the
# middle, so it slipped straight through undetected. Each pattern allows
# up to 3 filler words (an adverb or two) between the subject and "drawn
# to" so "I'm particularly/really/especially drawn to" are all still
# caught, without matching something genuinely unrelated further away in
# the sentence.
_BANNED_PHRASE_PATTERNS = [
    re.compile(r"\bi(?:'m|\s+am)\s+(?:\w+\s+){0,3}drawn to\b", re.IGNORECASE),
]


def find_banned_phrase(text: str) -> str:
    """Returns the actual matched text (not just the canonical pattern), so
    a caller passing this into a rewrite prompt points at exactly what's
    really there - "I'm particularly drawn to," not a generic stand-in that
    doesn't match what the model actually wrote."""
    for pattern in _BANNED_PHRASE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return ""


def strip_em_dashes(text: str) -> str:
    """Hard backstop: prompts instruct zero em dashes, but that's a request,
    not a guarantee. Replaces any that slip through with a comma, the
    closest single-character substitute for how em dashes are typically
    used in this kind of writing (a soft parenthetical pause), then cleans
    up any resulting double punctuation/spacing."""
    text = text.replace(" — ", ", ").replace("—", ", ")
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r",\s*\.", ".", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text
