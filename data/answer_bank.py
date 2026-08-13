"""
answer_bank.py
Stores previously-written, user-approved answers to common job-application
custom questions (why this company, tools comfort, pattern recognition,
company-specific compliance questions, etc.).

Checked before any new answer is drafted: matching an existing entry is
free and instant, drafting a new one costs an API call and produces text
nobody has reviewed yet, so the cheap deterministic check always goes
first — same reasoning as the two-tier rubric/panel scoring split.

Two-tier matching, in order:
  1. Exact match on `question_text` (normalized: case/whitespace-insensitive).
     Deterministic, zero collision risk — the right tier for company-
     specific questions (visa sponsorship, dealer-partner relationships,
     etc.), which is exactly where keyword matching produced real bugs.
     The recommended workflow: use browser.autofill.scan_questions(url) to
     pull a listing's actual question text first, then write the entry's
     `question_text` as a verbatim (or near-verbatim) copy of what came
     back, rather than reconstructing it by eye from a raw page dump.
  2. Keyword-overlap fallback (>= _MIN_KEYWORD_HITS), for genuinely reusable
     general questions ("why this company," "tools comfort") that get
     worded differently across employers, where an exact match will never
     land. Confirmed directly in testing that a single keyword hit is too
     weak a signal on its own: a contractor-history question ("...name of
     the agency/company") matched a "why this company" entry purely because
     "company" was one of its keywords, and got silently auto-filled with a
     completely unrelated answer. Requiring at least two hits before
     trusting a keyword match is a much stronger bar without needing a real
     similarity model.

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


def is_using_example() -> bool:
    """True until the user has saved their own bank (via the Setup tab, or
    by hand-editing sample_data/answer_bank.json directly)."""
    return not os.path.exists(REAL_PATH)


def save_answer_bank(entries: list) -> None:
    """Writes the real bank - always to REAL_PATH, never EXAMPLE_PATH, same
    reasoning as data.profile.save_profile."""
    with open(REAL_PATH, "w") as f:
        json.dump(entries, f, indent=2)


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
    """Matches an application's custom question against the bank. Tries an
    exact (normalized) match on `question_text` first — deterministic, no
    collision risk — then falls back to keyword overlap for general,
    reusable questions. Returns the matching entry (category, question_text,
    answer) or None if nothing matches closely enough. None means the
    question is genuinely new and needs a fresh, clearly-flagged draft —
    never forces a reuse of the closest entry regardless of actual fit."""
    normalized_question = _normalize(question_text)
    if not normalized_question:
        return None

    bank = load_answer_bank()

    for entry in bank:
        entry_question = entry.get("question_text", "")
        if entry_question and _normalize(entry_question) == normalized_question:
            return entry

    best_entry = None
    best_score = 0
    for entry in bank:
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
