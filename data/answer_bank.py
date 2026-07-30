"""
answer_bank.py
Stores previously-written, user-approved answers to common job-application
custom questions (why this company, tools comfort, pattern recognition,
etc.), keyed by keyword so a genuinely new question can be told apart from
a rephrasing of one already answered and approved.

Checked before any new answer is drafted: matching an existing entry is
free and instant, drafting a new one costs an API call and produces text
nobody has reviewed yet, so the cheap deterministic check always goes
first — same reasoning as the two-tier rubric/panel scoring split.

sample_data/answer_bank.json is the user's real, curated bank and is
gitignored on purpose, same as sample_data/resume.md. answer_bank.example.json
is the fictional placeholder that ships in the repo so the matching logic has
something to run against out of the box.
"""

import json
import os

_DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_PATH = os.path.join(_DATA_DIR, "sample_data", "answer_bank.json")
EXAMPLE_PATH = os.path.join(_DATA_DIR, "sample_data", "answer_bank.example.json")


def load_answer_bank() -> list:
    path = REAL_PATH if os.path.exists(REAL_PATH) else EXAMPLE_PATH
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def _normalize(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else " " for ch in text).strip()


# A single keyword hit is too weak a signal on its own — confirmed directly
# in testing: a contractor-history question ("...name of the agency/
# company") matched the "why_this_company" entry purely because "company"
# is one of its keywords, and got silently auto-filled with a completely
# unrelated answer. Requiring at least two independent keyword hits before
# trusting a match is a much stronger confidence bar without needing a real
# similarity model, and it's a straightforward code-level minimum, not a
# tunable the caller has to remember to set.
_MIN_KEYWORD_HITS = 2


def find_answer(question_text: str) -> dict | None:
    """Matches an application's custom question against the bank by keyword
    overlap. Returns the matching entry (category, question_example, answer)
    or None if nothing matches closely enough. None means the question is
    genuinely new and needs a fresh, clearly-flagged draft — never forces a
    reuse of the closest entry regardless of actual fit."""
    normalized_question = _normalize(question_text)
    if not normalized_question:
        return None

    best_entry = None
    best_score = 0
    for entry in load_answer_bank():
        keywords = [_normalize(k) for k in entry.get("keywords", [])]
        score = sum(1 for k in keywords if k and k in normalized_question)
        if score > best_score:
            best_score = score
            best_entry = entry

    # Below the minimum, treat it as "no confident match" rather than
    # trusting a single coincidental word overlap - see _MIN_KEYWORD_HITS.
    if best_score < _MIN_KEYWORD_HITS:
        return None
    return best_entry
