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

One deliberate exception to the "flat fact" rule above: years-of-experience
gate questions ("Do you have at least 5 years of Product Management
experience?"). These were originally left OUT on purpose - the answer
depends on the number stated in THAT question, not a static yes/no - and
routed to resume-grounded drafting instead, flagged every time as an
unreviewed AI draft. In real use this meant re-approving the same true fact
("yes, comfortably") on every single listing. The actual underlying fact
(total years of experience, and years specifically in product management)
IS static - it just needs comparing against a per-question threshold, which
is exactly the kind of "check it in code" fix this project favors over
asking a model to get it right by convention. See "experience_years" in the
profile JSON and browser.autofill._resolve_experience_threshold.

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
    matching a topic it already knows, instead of needing exact text.

    Only keys whose value is a LIST OF PHRASINGS qualify - confirmed
    directly this matters: adding "experience_years" (a {"total": 15, ...}
    dict, used by a separate numeric-threshold resolver, not the phrasing
    matcher) made it eligible here too, so the mapping LLM tagged a "5+
    years of experience" question with topic="experience_years", and
    profile_answers_for wrapped the whole dict as a single "phrasing",
    which then crashed trying to fill a dict into a text field. Structural
    facts that aren't a flat list of acceptable strings must never be
    offered as a topic, not just this one - excluded by shape, not by
    name, so a future non-list fact doesn't reintroduce the same bug."""
    return sorted(k for k, v in load_profile().items() if isinstance(v, list))


def experience_years() -> dict:
    """Static, per-domain years-of-experience facts (e.g. {"total": 15,
    "product_management": 7}), used to answer "do you have at least N years
    of X experience" gate questions without redrafting or reapproving the
    same true answer on every listing. Returns {} if not set - callers must
    treat that as "no fact on file," same as any other unmatched question."""
    value = load_profile().get("experience_years")
    return value if isinstance(value, dict) else {}


def profile_answers_for(topic: str) -> list:
    """Every acceptable phrasing for a given topic, in preference order (the
    first is tried first). Returns an empty list if the topic isn't in the
    profile at all, or if its value isn't a plain string/list-of-strings
    (e.g. the "experience_years" dict, which the numeric-threshold resolver
    owns, not this phrasing matcher) - the caller should treat both the
    same as "no saved fact"."""
    value = load_profile().get(topic)
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    return []
