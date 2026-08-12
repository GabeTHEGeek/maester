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
BANNED_PHRASES_NEEDING_REWRITE = [
    "i'm drawn to",
    "i am drawn to",
]


def find_banned_phrase(text: str) -> str:
    lower_text = text.lower()
    for phrase in BANNED_PHRASES_NEEDING_REWRITE:
        if phrase in lower_text:
            return phrase
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
