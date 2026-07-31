"""
profile.py
Structured, static personal facts (work authorization, demographics,
logistics) used to answer job-application questions whose real answer is a
fixed truth about the candidate — not something the resume states in prose,
and not something that depends on how a specific question is worded.

This is the direct fix for a fragility the exact-text answer bank
(answer_bank.py) can't solve on its own: two employers asking the same real
question in different words ("Are you currently authorized to work in the
U.S.?" vs. "Are you currently eligible to work in the United States of
America?") used to need two separate bank entries, because the bank only
ever matched exact text or keyword overlap. The fix isn't a matching trick —
it's recognizing that the field-mapping LLM is already reading each question
anyway, so it can tag a question with a stable TOPIC key (see
known_topics()) based on what it's actually asking, regardless of exact
wording. The profile is keyed by those same topic strings, so a new
question worded completely differently still resolves to the same stored
fact instead of needing a new entry every time.

Each profile value is a LIST of acceptable phrasings, not a single string —
confirmed directly this matters: "Man" and "Male" mean the same real fact
but don't substring-match each other, and different employers' dropdowns
use one or the other. find_profile_answer tries each phrasing against the
field's real options (via browser.fields' existing exact/substring matcher)
until one lands, rather than assuming a single canonical string will always
match every employer's own wording.

Deliberately NOT included here: anything that depends on how a specific
question is worded rather than a flat fact (e.g. "do you have at least 5
years of X experience" - the actual answer depends on the number in THAT
question, not a static yes/no) - those stay on the existing resume-grounded
drafting path in browser/autofill.py, which already reasons about the
specific wording correctly.

sample_data/profile.json is the user's real profile and is gitignored on
purpose, same as resume.md and answer_bank.json. profile.example.json is
the fictional placeholder shipped in the repo so the matching logic has
something to run against out of the box.
"""

import json
import os

_DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_PATH = os.path.join(_DATA_DIR, "sample_data", "profile.json")
EXAMPLE_PATH = os.path.join(_DATA_DIR, "sample_data", "profile.example.json")


def load_profile() -> dict:
    path = REAL_PATH if os.path.exists(REAL_PATH) else EXAMPLE_PATH
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def known_topics() -> list:
    """The topic keys this profile has real answers for, fed to the
    field-mapping LLM so it can recognize a differently-worded question as
    matching a topic it already knows, instead of needing exact text."""
    return sorted(load_profile().keys())


def profile_answers_for(topic: str) -> list:
    """Every acceptable phrasing for a given topic, in preference order (the
    first is tried first). Returns an empty list if the topic isn't in the
    profile at all - the caller should treat that as "no saved fact," the
    same as any other unmatched question."""
    value = load_profile().get(topic)
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
