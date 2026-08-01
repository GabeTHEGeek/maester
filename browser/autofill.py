"""
autofill.py
Opens a real, visible browser on a job application page and fills in what
Maester already knows: contact info from the resume, the tailored resume and
cover letter PDFs, and answers to custom questions (reused from the profile/
answer bank when one matches, freshly drafted and flagged when none does).
Then it stops.

This module is the orchestrator only. Two things it deliberately doesn't own
anymore, split out because they turned out to need very different kinds of
change over time:
- browser/vendors/ — how to find and label fields on a SPECIFIC ATS
  platform's markup. Confirmed directly this session: Ashby's forms use a
  custom Yes/No button-toggle widget and native fieldset-wrapped radio/
  checkbox groups found nowhere else, tied to Ashby's own stable class
  names - none of which means anything on a Greenhouse or Lever form. A
  vendor gets detected from the URL (reusing utils.extract's existing
  platform detection) and supplies its own SCAN_FIELDS_JS and reveal-button
  logic; unrecognized platforms fall back to vendors.base's generic,
  already-tested behavior.
- browser/fields.py — how to FILL and VERIFY a field once its tag/options
  are known. This part doesn't need to know which vendor produced the tag,
  only what the tag means (a native <select>, a radiogroup, a yesnogroup,
  etc.), so it stays vendor-agnostic.

HARD RULE, the single non-negotiable constraint of this entire module: this
code never clicks anything that submits an application. That is enforced
structurally, not by asking a model nicely and hoping it holds — the same
lesson this project has already learned the hard way for em dashes, banned
phrases, and JSON truncation (see CLAUDE.md), applied here to something
irreversible instead of cosmetic.

There are exactly two click-eligible categories, kept structurally distinct:
  1. REVEAL clicks (vendors.base.Adapter.find_reveal_button): opens/scrolls
     to the actual application form. Decided entirely in code against a
     small closed allowlist of exact button/link text ("Apply", "Apply Now",
     etc.) — never left to the field-mapping LLM's judgment. Excludes any
     element with type="submit" outright, and is independently re-checked
     against a submit-word denylist even though the allowlist and denylist
     don't overlap by construction — belt and suspenders on the one rule
     that actually matters.
  2. SUBMIT clicks: still categorically absent. There is no allowlist, no
     category, no code path anywhere in this file (or fields.py, or any
     vendor module) that clicks a submit button or anything matching the
     submit-word denylist.

A third, narrower click exists inside fields.py's _fill_field: some custom
dropdown widgets (react-select and similar) only register a value when a
visible `role="option"` element is clicked, typed text alone doesn't commit
a selection. This is part of *filling* a field the caller already decided to
fill, not a new capability boundary. A fourth uses `.check()` on checkboxes
explicitly categorized as "consent_checkbox" (agreeing to the employer's
privacy policy — real, informed opt-in, done only because the user
explicitly chose to auto-check it after being told exactly what it means).
"""

import json
import re

from playwright.sync_api import sync_playwright

from browser import fields
from browser.vendors import get_adapter
from data.answer_bank import find_answer
from data.profile import experience_years, known_topics, profile_answers_for
from engines.llm_fallback import call_with_fallback
from utils.fetch_job import check_liveness, fetch_job_page

FIELD_MAPPING_MODEL = fields.FIELD_MAPPING_MODEL

FIELD_MAPPING_SYSTEM_PROMPT_TEMPLATE = """You map a job application form's raw fields to a
known set of categories, using each field's tag, type, name, placeholder, and
label text. Respond ONLY with valid JSON, no markdown fences, no prose:
{{"fields": [{{"index": <int>, "category": "<category>", "question_text": "<only for custom_question and demographic_question, the actual question being asked, verbatim from the label>", "topic": "<optional, see below>"}}]}}

TOPIC MATCHING (the fix for a real fragility: two employers asking the exact
same real question in different words used to need two separate saved
answers, because matching only ever compared exact text): for a
"demographic_question" or "custom_question" field, if what it's REALLY
asking - regardless of exact wording - matches one of these already-known
topics, include that EXACT topic string as "topic" in your response for that
field: {known_topics}
This is a semantic judgment, not a text match - "Are you currently
authorized to work in the U.S.?" and "Are you currently eligible to work in
the United States of America?" are the SAME real question and should get the
SAME topic. If a question is genuinely new, or you're not confident it
matches one of these, omit "topic" entirely rather than guessing - a wrong
topic match reuses the wrong saved fact, which is worse than drafting fresh.
Never invent a new topic string of your own; only ever use one from the list
above, or none at all.

Some fields represent a whole group of radio buttons, checkboxes, or a
custom Yes/No button-toggle widget (tag "radiogroup"/"checkboxgroup"/
"yesnogroup") rather than a single input - you'll see an "options" list of
the actual choices (e.g. "Yes"/"No", or a list of gender identities).
Categorize the GROUP as a whole using its own label_text, the same as any
other field - you never need to pick which specific option to
select, that's handled separately using whatever answer is decided on.

Valid categories:
- "first_name", "last_name" - use these, NOT "name", whenever first and last
  name have SEPARATE fields (the overwhelmingly common case: distinct
  "First Name*" / "Last Name*" boxes). Getting this wrong means the full
  name gets typed into both boxes, which is wrong data, not just imprecise -
  treat first/last name detection carefully, never default to "name" when
  two separate name fields are present.
- "name" - for a field meant to hold the candidate's whole name at once
  (e.g. a single "First and Last Name" box). A form can have MORE THAN ONE
  such field (e.g. separate "Preferred Name" and "Legal Name" boxes asking
  for the full name each time) - map EVERY one of them to "name", always,
  never "custom_question". A name field is never a free-text question that
  needs drafting, regardless of how many of them a form has or what
  they're labeled - treat this as a fixed rule, not a judgment call per
  field, since the same form has been observed categorizing this
  inconsistently between otherwise-identical runs.
- "skip" (not "custom_question") for any OTHER name-adjacent field that
  isn't first/last/whole/middle name - "Nickname," "Preferred
  Pronunciation," and similar - since there's no real answer to draft for
  these and guessing would mean inventing a fact, not answering a question.
- "email", "phone", "country", "city", "state" - standard contact fields
  ("country", "city", "state" mean location of residence, e.g. an address
  section - not a work-authorization or visa question, those are
  "custom_question"). Confirmed directly this distinction matters: a
  "Current State of Residency" field was mis-categorized as "city" before
  "state" existed as its own option, which tried to fill the candidate's
  city name into a field expecting a US state - use "state" specifically
  for a field asking for a state/province, never "city" for it.
- "linkedin_url", "portfolio_url", "github_url" - profile link fields
- "resume_upload" - a file input for a resume/CV
- "cover_letter_upload" - a file input for a cover letter
- "demographic_question" - voluntary EEO/self-identification questions:
  gender identity, transgender experience, sexual orientation, disability
  status, veteran status, race/ethnicity, AND pronouns (confirmed directly:
  a bare "Pronouns" field with checkbox options like "She/her/hers,"
  "He/him/his," "They/them/theirs" was being mis-categorized as "skip"
  before this was spelled out explicitly - it belongs here, not "skip" or
  "custom_question"). Distinct from "custom_question" on purpose: these are
  only ever filled from a pre-approved saved answer, NEVER freshly drafted,
  since a resume has no basis to state a person's identity and guessing
  would mean fabricating it.
- "middle_name" - a field specifically asking for a middle name. Distinct
  from "skip" on purpose: there's no real middle name to give, but "N/A" is
  the standard, non-fabricated convention for a REQUIRED field asking for
  one - filled automatically when required, left blank (flagged) when
  optional. Never "custom_question" or "skip" for this.
- "consent_checkbox" - a checkbox agreeing to the employer's privacy policy
  or to processing of the candidate's own application/survey data as part
  of applying. NOT a marketing-email opt-in or anything unrelated to the
  application itself - if genuinely unsure which this is, use "skip".
- "custom_question" - a free-text question the candidate needs to answer
  (why this company, tools comfort, availability, a behavioral prompt, etc.)
- "skip" - anything else: unrelated fields, dropdowns, checkboxes,
  anything you're not confident about

Only ever return "skip" if uncertain - a wrong guess on a mapped field fills
the wrong data into a stranger's application, which is worse than leaving a
field for the human to handle themselves."""


# Keyword -> experience_years() key, checked in order (first match wins) so
# a more specific domain ("product management") is checked before falling
# back to "total" - confirmed the real fact this project's user gave
# directly: 15 years total tech experience, 7+ specifically in product
# management, and a form asking "5+ years of Product Management experience"
# needs the 7, not the 15, or a genuinely false "No" could result for a
# domain-specific threshold this candidate doesn't clear on the total alone.
_EXPERIENCE_DOMAIN_KEYWORDS = [
    ("product_management", ["product management", "product manager", "as a pm", "product management experience"]),
]

_YEARS_THRESHOLD_RE = re.compile(r"(\d+)\s*\+?\s*years?", re.IGNORECASE)


def _resolve_experience_threshold(question_text: str) -> str:
    """Deterministically answers a "do you have at least N years of X
    experience" gate question from the static experience_years() profile
    fact, instead of drafting a fresh answer (and flagging it for review)
    every single time for a fact that never actually changes per listing.
    Returns "Yes"/"No" when the question text names a numeric year
    threshold and a matching (or "total") experience fact is on file, ""
    otherwise - callers must fall through to normal drafting on "", since a
    question this can't confidently parse is exactly the kind of ambiguity
    this function isn't meant to guess through."""
    years = experience_years()
    if not years:
        return ""
    match = _YEARS_THRESHOLD_RE.search(question_text)
    if not match:
        return ""
    text_lower = question_text.lower()
    if "year" not in text_lower or "experience" not in text_lower:
        return ""
    threshold = int(match.group(1))
    domain = "total"
    for key, keywords in _EXPERIENCE_DOMAIN_KEYWORDS:
        if any(kw in text_lower for kw in keywords):
            domain = key
            break
    actual = years.get(domain, years.get("total"))
    if actual is None:
        return ""
    return "Yes" if actual >= threshold else "No"


def _try_topic_answer(page, raw_entry: dict, locator, topic) -> tuple:
    """If the field-mapping call recognized this question as matching a
    known profile topic, tries every saved phrasing for that topic (in
    order) against this specific employer's form until one actually fills
    and verifies - "Man" not matching a "Male"/"Female" dropdown is exactly
    why a topic can have more than one saved phrasing. Returns (True, value)
    on the first phrasing that works, (False, None) if the field has no
    topic, the topic has no saved answer, or none of the saved phrasings
    match anything this form actually offers - never guesses among them."""
    if not topic:
        return False, None
    for candidate_value in profile_answers_for(topic):
        if fields.fill_answer(page, raw_entry, locator, candidate_value):
            return True, candidate_value
    return False, None


# Kept alive here, not just in the caller's local variables, so the visible
# browser window survives a Streamlit rerun (which discards local Python
# state every time the script re-executes top to bottom) without the
# Playwright driver/browser process being garbage-collected out from under
# the user mid-review.
_LIVE_SESSIONS = {}


class FillResult:
    def __init__(self, status, reason="", fields_auto_mapped=None, fields_flagged=None, reveal_clicked=False):
        self.status = status  # "opened" | "dead" | "error"
        self.reason = reason
        self.fields_auto_mapped = fields_auto_mapped or []
        self.fields_flagged = fields_flagged or []
        self.reveal_clicked = reveal_clicked


class _DiscoveryResult:
    def __init__(self, status, reason="", reveal_clicked=False, playwright=None, browser=None, page=None, raw_fields=None, mapping=None):
        self.status = status  # "ok" | "dead" | "error" | "no_fields" | "mapping_failed"
        self.reason = reason
        self.reveal_clicked = reveal_clicked
        self.playwright = playwright
        self.browser = browser
        self.page = page
        self.raw_fields = raw_fields or []
        self.mapping = mapping or []


def _discover_and_map(url, api_key, deepseek_api_key, session_key=None):
    """Shared first half of both open_and_fill and scan_questions: liveness
    check, open a visible browser, get the right vendor adapter for this
    URL, click the 'Apply' reveal control if one is safely identifiable,
    scan the resulting fields using that vendor's own scanning logic, and
    map them via the same LLM call. Split out so scanning a listing's
    questions (no filling, no browser left open) and actually filling it
    don't duplicate this logic, and so a fix to one (e.g. the reveal-click
    hardening) automatically applies to both."""
    try:
        page_data = fetch_job_page(url)
    except Exception as e:
        return _DiscoveryResult(status="error", reason=f"Couldn't reach the listing: {e}")

    liveness = check_liveness(page_data["text"], page_data["final_url"])
    if liveness["status"] == "expired":
        return _DiscoveryResult(status="dead", reason=liveness["reason"])

    adapter = get_adapter(url)

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width": 1600, "height": 1000})
    pw_page = context.new_page()
    pw_page.goto(url, wait_until="domcontentloaded")
    # Many career pages (Cribl's included) client-render their real content,
    # including the Apply button, after the initial DOM load fires - a fixed
    # settle wait here, not just at goto(), so the scan below sees the
    # hydrated page instead of the pre-JS shell.
    pw_page.wait_for_timeout(2000)

    session_key = session_key or url
    _LIVE_SESSIONS[session_key] = {
        "playwright": playwright,
        "browser": browser,
        "context": context,
        "page": pw_page,
    }

    reveal_clicked = False
    reveal_button = adapter.find_reveal_button(pw_page)
    if reveal_button:
        try:
            reveal_button.click()
            pw_page.wait_for_load_state("domcontentloaded")
            pw_page.wait_for_timeout(1500)
            reveal_clicked = True
        except Exception:
            # Most likely something else (a cookie-consent overlay, a modal)
            # is blocking it - stay safe and just proceed to scan whatever
            # the page already has, same as if no reveal button existed.
            pass

    raw_fields = pw_page.evaluate(adapter.SCAN_FIELDS_JS, adapter.SKIPPED_INPUT_TYPES)

    if not raw_fields:
        reason = "No fillable fields detected on this page"
        reason += " (clicked 'Apply' to reveal the form, but still found none)" if reveal_clicked else ""
        reason += " - likely a custom or JS-heavy form."
        return _DiscoveryResult(
            status="no_fields", reason=reason, reveal_clicked=reveal_clicked,
            playwright=playwright, browser=browser, page=pw_page,
        )

    # A field's full options list can be huge (a real country/university
    # <select> can carry 1000+ entries) and the mapping step only needs
    # enough of it to recognize the field's TYPE, not every choice - sending
    # the whole thing would flood the prompt for zero benefit. The complete
    # list stays in raw_fields for the actual fill step, which needs it.
    _MAX_OPTIONS_IN_PROMPT = 15
    prompt_fields = []
    for f in raw_fields:
        options = f.get("options", [])
        if len(options) > _MAX_OPTIONS_IN_PROMPT:
            f = dict(f)
            f["options"] = options[:_MAX_OPTIONS_IN_PROMPT]
            f["options_truncated_count"] = len(options) - _MAX_OPTIONS_IN_PROMPT
        prompt_fields.append(f)
    mapping_prompt = "FORM FIELDS (JSON):\n" + json.dumps(prompt_fields, indent=2)
    topics = known_topics()
    mapping_system_prompt = FIELD_MAPPING_SYSTEM_PROMPT_TEMPLATE.format(
        known_topics=topics if topics else "(none saved yet)"
    )
    try:
        mapping_text, _provider = call_with_fallback(
            system_prompt=mapping_system_prompt,
            user_prompt=mapping_prompt,
            anthropic_api_key=api_key,
            anthropic_model=FIELD_MAPPING_MODEL,
            max_tokens=2000,
            deepseek_api_key=deepseek_api_key,
        )
        mapping = fields._extract_json(mapping_text).get("fields", [])
    except Exception as e:
        return _DiscoveryResult(
            status="mapping_failed", reason=f"Field mapping failed ({e}).", reveal_clicked=reveal_clicked,
            playwright=playwright, browser=browser, page=pw_page, raw_fields=raw_fields,
        )

    # The mapping call can omit a field entirely (a truncated or incomplete
    # JSON response) - without this check, that field just vanishes from
    # every downstream list: not filled, not flagged, no record it was ever
    # on the page at all. Every raw_fields index gets an explicit "skip"
    # entry here if the LLM didn't return one, so it always shows up in the
    # fill loop's flagged output instead of silently disappearing.
    mapped_indices = {entry.get("index") for entry in mapping}
    for f in raw_fields:
        if f["index"] not in mapped_indices:
            mapping.append({"index": f["index"], "category": "skip"})

    return _DiscoveryResult(
        status="ok", reveal_clicked=reveal_clicked,
        playwright=playwright, browser=browser, page=pw_page,
        raw_fields=raw_fields, mapping=mapping,
    )


def scan_questions(url, api_key, deepseek_api_key="", session_key=None):
    """Ingests a listing's actual custom and demographic questions WITHOUT
    filling anything and without leaving a browser open - a lightweight
    preview step so answers can be crafted deliberately (reviewed, or handed
    to the user for real facts) before any fill attempt, instead of
    reverse-engineering field text from a live page under time pressure each
    time. Returns {"status", "reason", "questions": [{"question_text",
    "field_label", "category"}]} - category is "custom_question" or
    "demographic_question", useful for telling apart a fresh essay-style
    question from one that should only ever be answered from a saved,
    pre-approved fact (see the "demographic_question" handling in
    open_and_fill).
    """
    discovery = _discover_and_map(url, api_key, deepseek_api_key, session_key=f"scan-{session_key or url}")

    questions = []
    if discovery.status == "ok":
        for entry in discovery.mapping:
            category = entry.get("category")
            if category not in ("custom_question", "demographic_question"):
                continue
            index = entry.get("index")
            field_label = next(
                (f.get("label_text") or f.get("name") or f"field #{index}" for f in discovery.raw_fields if f["index"] == index),
                f"field #{index}",
            )
            questions.append({
                "question_text": entry.get("question_text") or field_label,
                "field_label": field_label,
                "category": category,
            })

    # Scanning is preview-only - always close the browser it opened, unlike
    # open_and_fill which deliberately leaves it open for review.
    if discovery.page is not None:
        try:
            discovery.browser.close()
            discovery.playwright.stop()
        except Exception:
            pass
        _LIVE_SESSIONS.pop(f"scan-{session_key or url}", None)

    return {"status": discovery.status, "reason": discovery.reason, "questions": questions}


def open_and_fill(
    url,
    resume_text,
    company,
    role_title,
    contact_info,
    links,
    resume_pdf_path,
    cover_letter_pdf_path,
    api_key,
    deepseek_api_key="",
    session_key=None,
):
    """Pre-flight liveness check, then opens a visible browser on `url`, maps
    its fields via an LLM call, fills in what it confidently can, drafts and
    flags answers to genuinely new custom questions, and stops. The browser
    is left open and untouched at that final state - nothing in this
    function, or anything it calls, submits the form. See module docstring.
    """
    discovery = _discover_and_map(url, api_key, deepseek_api_key, session_key=session_key)

    if discovery.status in ("dead", "error"):
        return FillResult(status=discovery.status, reason=discovery.reason)
    if discovery.status == "no_fields":
        return FillResult(status="opened", reason=discovery.reason + " Left open for manual review.", reveal_clicked=discovery.reveal_clicked)
    if discovery.status == "mapping_failed":
        return FillResult(
            status="opened",
            reason=discovery.reason + " Every field left for manual review.",
            fields_flagged=[f.get("label_text") or f.get("name") or f"field #{f['index']}" for f in discovery.raw_fields],
            reveal_clicked=discovery.reveal_clicked,
        )

    pw_page = discovery.page
    raw_fields = discovery.raw_fields
    mapping = discovery.mapping
    reveal_clicked = discovery.reveal_clicked

    auto_mapped = []
    flagged = []
    # Every field this loop believes it successfully filled, kept alongside
    # exactly what was used to fill it - not just the label - so the
    # verify-and-retry pass below can re-check the real DOM state and, if
    # it doesn't match, redo the fill with the same inputs rather than just
    # trusting the report. This is the direct fix for a repeated failure
    # mode this session: a field marked as successfully filled that turned
    # out, on inspection, to still be genuinely blank.
    attempted = []

    for entry in mapping:
        index = entry.get("index")
        category = entry.get("category", "skip")
        locator = pw_page.locator(f'[data-maester-index="{index}"]')
        raw_entry = next((f for f in raw_fields if f["index"] == index), {})
        field_label = raw_entry.get("label_text") or raw_entry.get("name") or f"field #{index}"

        def _record(ok: bool, value=None, note: str = "") -> None:
            if ok:
                auto_mapped.append(field_label)
                attempted.append({"label": field_label, "index": index, "raw_entry": raw_entry, "value": value})
            else:
                flagged.append(f"{field_label} ({note})" if note else field_label)

        try:
            if category == "first_name" and contact_info.get("name"):
                first, _, _ = contact_info["name"].partition(" ")
                _record(fields.fill_answer(pw_page, raw_entry, locator, first), first, "no matching option offered")
            elif category == "last_name" and contact_info.get("name"):
                _, _, rest = contact_info["name"].partition(" ")
                if rest:
                    _record(fields.fill_answer(pw_page, raw_entry, locator, rest), rest, "no matching option offered")
                else:
                    flagged.append(field_label)  # single-word name, no real "last name" to give
            elif category == "name" and contact_info.get("name"):
                _record(fields.fill_answer(pw_page, raw_entry, locator, contact_info["name"]), contact_info["name"], "no matching option offered")
            elif category == "email" and contact_info.get("email"):
                _record(fields.fill_answer(pw_page, raw_entry, locator, contact_info["email"]), contact_info["email"], "no matching option offered")
            elif category == "phone" and contact_info.get("phone"):
                _record(fields.fill_answer(pw_page, raw_entry, locator, contact_info["phone"]), contact_info["phone"], "no matching option offered")
            elif category == "country" and contact_info.get("country"):
                _record(fields.fill_answer(pw_page, raw_entry, locator, contact_info["country"]), contact_info["country"], "no matching option offered")
            elif category == "city" and contact_info.get("city"):
                _record(fields.fill_answer(pw_page, raw_entry, locator, contact_info["city"]), contact_info["city"], "no matching option offered")
            elif category == "state" and contact_info.get("state"):
                _record(fields.fill_answer(pw_page, raw_entry, locator, contact_info["state"]), contact_info["state"], "no matching option offered")
            elif category == "linkedin_url" and links.get("linkedin_url"):
                _record(fields.fill_answer(pw_page, raw_entry, locator, links["linkedin_url"]), links["linkedin_url"], "no matching option offered")
            elif category == "portfolio_url" and links.get("portfolio_url"):
                _record(fields.fill_answer(pw_page, raw_entry, locator, links["portfolio_url"]), links["portfolio_url"], "no matching option offered")
            elif category == "github_url" and links.get("github_url"):
                _record(fields.fill_answer(pw_page, raw_entry, locator, links["github_url"]), links["github_url"], "no matching option offered")
            elif category == "middle_name":
                # No real middle name to give. "N/A" is a standard,
                # non-fabricated convention for a REQUIRED field - filling
                # it isn't inventing a fact, it's stating the actual fact
                # ("none"). An optional field is left genuinely blank
                # instead, same as before this category existed.
                if raw_entry.get("required"):
                    _record(fields.fill_answer(pw_page, raw_entry, locator, "N/A"), "N/A", "no matching option offered")
                else:
                    flagged.append(f"{field_label} (no middle name — optional, left blank)")
            elif category == "resume_upload" and resume_pdf_path:
                locator.set_input_files(resume_pdf_path)
                auto_mapped.append(field_label)
                attempted.append({"label": field_label, "index": index, "raw_entry": raw_entry, "value": resume_pdf_path, "file": True})
            elif category == "cover_letter_upload" and cover_letter_pdf_path:
                locator.set_input_files(cover_letter_pdf_path)
                auto_mapped.append(field_label)
                attempted.append({"label": field_label, "index": index, "raw_entry": raw_entry, "value": cover_letter_pdf_path, "file": True})
            elif category == "demographic_question":
                # Bank-lookup only - NEVER falls through to a fresh LLM
                # draft. A resume has no basis to state a person's gender
                # identity, ethnicity, disability, or veteran status, so
                # unlike custom_question, an unmatched demographic question
                # just stays flagged, full stop - guessing here would mean
                # fabricating someone's identity, not just missing a fact.
                question_text = entry.get("question_text") or field_label
                topic = entry.get("topic")
                ok, used_value = _try_topic_answer(pw_page, raw_entry, locator, topic)
                if ok:
                    _record(True, used_value)
                    continue
                bank_entry = find_answer(question_text)
                if bank_entry and bank_entry.get("approved"):
                    # A bank hit on the QUESTION doesn't guarantee the saved
                    # ANSWER text matches this employer's exact option wording
                    # (confirmed directly: "Man" vs. this form's real "Male")
                    # - check the result, don't assume success.
                    _record(
                        fields.fill_answer(pw_page, raw_entry, locator, bank_entry["answer"]),
                        bank_entry["answer"],
                        f"saved answer {bank_entry['answer']!r} wasn't offered as an option on this form",
                    )
                elif topic:
                    flagged.append(f"{field_label} (recognized as {topic!r} but no saved phrasing matched this form's options)")
                else:
                    flagged.append(f"{field_label} (no saved answer on file)")
            elif category == "consent_checkbox":
                # Confirmed directly on a live Reddit form: not every
                # "checkbox"-looking consent field is a real HTML checkbox -
                # one was actually a react-select-style single-option
                # combobox (its only option, verified directly: "I agree").
                # Try a real checkbox first, fall back to the same
                # click-and-select path everything else uses.
                try:
                    locator.check()
                    auto_mapped.append(field_label)
                    attempted.append({"label": field_label, "index": index, "raw_entry": raw_entry, "value": None, "checkbox": True})
                except Exception:
                    _record(fields.fill_answer(pw_page, raw_entry, locator, "I agree"), "I agree", "no matching consent option offered")
            elif category == "custom_question":
                question_text = entry.get("question_text") or field_label
                topic = entry.get("topic")
                ok, used_value = _try_topic_answer(pw_page, raw_entry, locator, topic)
                if ok:
                    _record(True, used_value)
                    continue
                bank_entry = find_answer(question_text)
                if bank_entry and bank_entry.get("approved"):
                    _record(
                        fields.fill_answer(pw_page, raw_entry, locator, bank_entry["answer"]),
                        bank_entry["answer"],
                        f"saved answer {bank_entry['answer']!r} wasn't offered as an option on this form",
                    )
                    continue
                experience_answer = _resolve_experience_threshold(question_text)
                if experience_answer:
                    ok = fields.fill_answer(pw_page, raw_entry, locator, experience_answer)
                    if ok:
                        _record(True, experience_answer)
                        continue
                    # Fall through to drafting rather than flagging outright -
                    # the fact is confidently known, only this form's exact
                    # option wording didn't match "Yes"/"No" literally.
                draft = fields._draft_custom_answer(
                    question_text, resume_text, company, role_title, api_key, deepseek_api_key,
                    options=raw_entry.get("options"), limit=raw_entry.get("limit"),
                )
                filled_ok = fields.fill_answer(pw_page, raw_entry, locator, draft)
                if filled_ok:
                    if not raw_entry.get("options"):
                        pw_page.evaluate(fields._FLAG_BANNER_JS, index)
                    flagged.append(f"{field_label} (unreviewed AI draft)")
                else:
                    flagged.append(f"{field_label} (drafted answer wasn't a valid option on this form)")
            else:
                flagged.append(field_label)
        except Exception as e:
            flagged.append(f"{field_label} (fill failed: {e})")

    auto_mapped, extra_flagged = fields.verify_and_retry(pw_page, attempted)
    flagged.extend(extra_flagged)

    reason = "Clicked 'Apply' to reveal the application form before filling it in." if reveal_clicked else ""
    return FillResult(
        status="opened",
        reason=reason,
        fields_auto_mapped=auto_mapped,
        fields_flagged=flagged,
        reveal_clicked=reveal_clicked,
    )
