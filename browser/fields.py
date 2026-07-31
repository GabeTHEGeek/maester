"""
fields.py
The generic fill/verify engine: once a field's tag and options are known
(assigned by a vendor's scanning logic - see browser/vendors/), everything
in this file works the same regardless of which ATS platform produced that
tag. This is the deliberate split from browser/vendors/: vendors own
DISCOVERING and LABELING fields on their own specific markup; this file
owns FILLING and VERIFYING them once discovered, since a react-select
combobox, a native <select>, or a native radio/checkbox group behaves the
same way no matter which vendor's page it showed up on.

HARD RULE, carried over from when this all lived in one file together:
nothing here clicks anything resembling a submit control. `.click()`,
`.check()`, and `select_option()` calls below only ever act on a field the
caller already decided to fill or a specific option already matched against
the intended value - never a button matching submit-like text. That
boundary is enforced in browser/vendors/base.py's find_reveal_button and
browser/autofill.py's orchestration, not here, but it's worth restating:
this module has no code path that could submit anything even if it wanted
to, since it never searches for or clicks buttons at all.
"""

import json
import re

from engines.llm_fallback import call_with_fallback

FIELD_MAPPING_MODEL = "claude-sonnet-4-5-20250929"

_FLAG_BANNER_JS = """
(index) => {
  const el = document.querySelector(`[data-maester-index="${index}"]`);
  if (!el) return;
  const banner = document.createElement('div');
  banner.textContent = '\\u26a0 Unreviewed AI draft \\u2014 check before submitting';
  banner.setAttribute('data-maester-flag', 'true');
  banner.style.cssText = 'color:#8a1f11;background:#fff0ef;border:1px solid #8a1f11;' +
    'padding:4px 8px;font:12px -apple-system,sans-serif;margin:4px 0;border-radius:4px;';
  el.insertAdjacentElement('afterend', banner);
}
"""


def _extract_json(text: str) -> dict:
    text = re.sub(r"```(json)?", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in field-mapping response: {text[:300]!r}")
    return json.loads(match.group(0))


def _draft_custom_answer(question_text, resume_text, company, role_title, api_key, deepseek_api_key, options=None, limit=None):
    """Same no-invention rule as engines/tailor.py: draws only on what's
    actually in the resume, never fabricates an experience or credential to
    answer a question the resume doesn't actually support.

    `options` is passed for radiogroup/checkboxgroup/yesnogroup questions -
    when present, the draft is constrained to exactly one of those option
    labels rather than a free paragraph. This matters because
    _check_group_option matches the draft against the option list by
    substring: a paragraph answer happens to work when it starts with an
    unambiguous word like "No," but that's luck, not a guarantee - asking
    for the exact option label directly removes the guesswork entirely.

    `limit` is the field's real character maxlength, when the browser has
    one. A draft longer than this would get silently truncated by .fill()
    - the same "looks filled, isn't really" failure shape as everything
    else fixed this session - so it's both asked for in the prompt AND
    enforced as a hard backstop below, consistent with this project's
    standing rule that a prompt instruction is a request, not a guarantee
    (see CLAUDE.md)."""
    if options:
        option_labels = [o["label"] for o in options]
        prompt = (
            f"Answer this job application question, grounded ONLY in the resume "
            f"below - never invent experience, employers, or metrics not already "
            f"present in it.\n\n"
            f"COMPANY: {company}\nROLE: {role_title}\nQUESTION: {question_text}\n\n"
            f"RESUME:\n{resume_text}\n\n"
            f"This question must be answered with EXACTLY one of these options, "
            f"verbatim, nothing else added: {option_labels}\n"
            f"Respond with ONLY that exact option text, no preamble, no punctuation "
            f"added, no explanation."
        )
        max_tokens = 60
    else:
        limit_instruction = f" HARD LIMIT: {limit} characters maximum, no exceptions." if limit else ""
        prompt = (
            f"Answer this job application question, grounded ONLY in the resume "
            f"below - never invent experience, employers, or metrics not already "
            f"present in it. If the resume doesn't truly support a strong answer, "
            f"write an honest, concise one anyway rather than fabricating specifics."
            f"{limit_instruction}\n\n"
            f"COMPANY: {company}\nROLE: {role_title}\nQUESTION: {question_text}\n\n"
            f"RESUME:\n{resume_text}\n\n"
            f"Respond with ONLY the answer text, 2-4 sentences, no preamble, no "
            f"JSON, no markdown fences."
        )
        max_tokens = 400

    text, _provider = call_with_fallback(
        system_prompt="",
        user_prompt=prompt,
        anthropic_api_key=api_key,
        anthropic_model=FIELD_MAPPING_MODEL,
        max_tokens=max_tokens,
        deepseek_api_key=deepseek_api_key,
    )
    text = text.strip()
    if limit and len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _fill_field(page, locator, value: str) -> bool:
    """Fills a value into a field, then checks whether a react-select-style
    option listbox appeared (elements with role="option") and clicks the one
    matching `value` if so. Confirmed directly this matters: a plain
    `.fill()` on a live Greenhouse "Country" combobox set the visible text
    but never actually registered a selection - these widgets only commit a
    value when a real option is clicked, typed text alone doesn't do it.

    Returns True if the fill can be trusted, False if it can't - the caller
    must check this and flag rather than auto-map on False. Three cases:
    - No option menu ever appears at all -> True (an ordinary text field;
      the plain .fill() above is the correct, complete answer).
    - A menu appears and one option matches `value` -> True, after clicking
      the real option.
    - A menu appears but NOTHING matches `value` -> False. The stored
      answer's exact wording doesn't match what this employer's form
      actually offers - leaving typed, unregistered text in the box and
      calling it success is worse than flagging it.

    Two things confirmed directly on a live Reddit application form, both
    needed for the True cases above to actually work rather than silently
    doing nothing or grabbing the wrong element entirely:
    - `.click()` before `.fill()`: react-select doesn't reliably render its
      own option list from `.fill()` alone - clicking first is what
      actually opens the menu.
    - Excluding intl-tel-input's own option elements (id starts with
      "iti-"): that phone-number country-code picker keeps its full country
      list in the DOM with `role="option"` at all times, on forms that
      happen to also have a phone field with this widget, regardless of
      which unrelated field is being filled. An unscoped option search on
      such a form silently matches the wrong widget's option.
    """
    locator.click()
    locator.fill(value)

    options = page.locator('[role="option"]:not([id^="iti-"])')
    try:
        options.first.wait_for(state="visible", timeout=1200)
    except Exception:
        return True  # no menu ever appeared - ordinary text field, .fill() stands as-is

    matching = options.filter(has_text=value)
    try:
        matching.first.wait_for(state="visible", timeout=800)
        matching.first.click()
        return True
    except Exception:
        return False  # a menu opened, but nothing in it matched - don't trust the raw typed text


def _find_matching_option(options: list, value: str):
    """Shared matcher for both native <select> options and radio/checkbox
    group options: prefers an exact (case-insensitive) match; falls back to
    a substring match only if that yields exactly one candidate. Returns
    None - never guesses - if nothing matches or more than one option
    plausibly does, same principle as everywhere else in this module: an
    uncertain match is worse than an honest flag."""
    normalized_value = value.strip().lower()

    exact = [o for o in options if o["label"].strip().lower() == normalized_value]
    candidates = exact or [
        o for o in options
        if normalized_value in o["label"].strip().lower() or o["label"].strip().lower() in normalized_value
    ]

    return candidates[0] if len(candidates) == 1 else None


def _check_group_option(page, raw_field_entry: dict, value: str) -> bool:
    """For a radiogroup/checkboxgroup entry (native radio/checkbox inputs -
    a completely different pattern from the react-select comboboxes),
    finds the specific option whose label matches `value` and checks it.
    For a "yesnogroup" (a custom Yes/No button-toggle widget - two real
    <button> elements alongside a checkbox that can't be meaningfully
    checked directly), clicks the matched button instead - the correct
    interaction for what a real user would actually click, not a state to
    set programmatically. Either way, the same guarantee holds: never
    guesses among ambiguous or absent matches."""
    option = _find_matching_option(raw_field_entry.get("options", []), value)
    if option is None:
        return False
    try:
        target = page.locator(f'[data-maester-index="{option["index"]}"]')
        if raw_field_entry.get("tag") == "yesnogroup":
            target.click()
        else:
            target.check()
        return True
    except Exception:
        return False


def _select_native_option(locator, raw_field_entry: dict, value: str) -> bool:
    """For a genuine native <select> element (country/university-style
    selects with hundreds of real <option> elements are common enough
    elsewhere to need their own path). Uses Playwright's select_option()
    directly by label - the correct, native API for this element, unlike
    the click-and-type approach the other widgets need. Matches the same
    way as a group: exact label match preferred, substring only if
    unambiguous; never guesses among multiple plausible options."""
    option = _find_matching_option(raw_field_entry.get("options", []), value)
    if option is None:
        return False
    try:
        locator.select_option(label=option["label"])
        return True
    except Exception:
        return False


def fill_answer(page, raw_field_entry: dict, locator, value: str) -> bool:
    """Single entry point the fill loop uses for any text-like answer,
    whether the underlying field turns out to be an ordinary input, a
    react-select combobox, a native <select>, or a native radio/checkbox
    group - callers don't need to know which, since the vendor's scanning
    logic already tells us via tag/options."""
    if raw_field_entry.get("tag") == "select":
        return _select_native_option(locator, raw_field_entry, value)
    if raw_field_entry.get("options"):
        return _check_group_option(page, raw_field_entry, value)
    return _fill_field(page, locator, value)


_MAX_FILL_RETRIES = 2  # bounded: a field that's genuinely unfillable (option
# removed, page changed) must not spin forever - after this many retries it
# gets demoted to flagged instead of trusted.


def verify_filled(page, attempt: dict) -> bool:
    """Re-reads the field's actual current DOM state and confirms it really
    matches what this module believes it filled - never trust a prior
    success report without checking, the same lesson repeated more than
    once this session (a field reported as filled turned out, on direct
    inspection, to still show its empty placeholder)."""
    index = attempt["index"]
    value = attempt["value"]
    raw_entry = attempt["raw_entry"]
    locator = page.locator(f'[data-maester-index="{index}"]')

    try:
        if attempt.get("file"):
            return locator.evaluate("e => e.files.length > 0")
        if attempt.get("checkbox"):
            return locator.is_checked()
        if raw_entry.get("tag") == "select":
            option = _find_matching_option(raw_entry.get("options", []), value)
            if option is None:
                return False
            selected = locator.evaluate("e => e.options[e.selectedIndex] ? e.options[e.selectedIndex].text : ''")
            return selected.strip().lower() == option["label"].strip().lower()
        if raw_entry.get("tag") == "yesnogroup":
            option = _find_matching_option(raw_entry.get("options", []), value)
            if option is None:
                return False
            # The matched option is a <button>, not a real checkbox - it has
            # no is_checked() of its own. The sibling hidden checkbox looked
            # like the right signal at first, but it's a SINGLE shared
            # boolean for the whole Yes/No pair - clicking "No" can leave it
            # at checked=False, which is indistinguishable from "never
            # answered" (confirmed directly: this false-negative happened on
            # a real listing). The button's own CSS state after being
            # clicked is reliable instead - Ashby marks the selected option
            # with a class containing "active" (hash suffix varies per
            # build, but that substring is stable).
            option_locator = page.locator(f'[data-maester-index="{option["index"]}"]')
            class_name = option_locator.get_attribute("class") or ""
            return "active" in class_name.lower()
        if raw_entry.get("options"):
            option = _find_matching_option(raw_entry.get("options", []), value)
            if option is None:
                return False
            return page.locator(f'[data-maester-index="{option["index"]}"]').is_checked()
        # Ordinary text field or react-select combobox: either the value is
        # genuinely sitting in the box (plain input), or the box cleared
        # because a real option got clicked (react-select's actual
        # "committed" signal) - an empty box with the menu still open or
        # never opened is neither.
        current = locator.input_value()
        if current.strip():
            return value.strip().lower() in current.strip().lower() or current.strip().lower() in value.strip().lower()
        return locator.get_attribute("aria-expanded") == "false"
    except Exception:
        return False


def _retry_fill(page, attempt: dict) -> None:
    """Re-attempts a fill that failed verification, using the exact same
    inputs recorded the first time - a fresh locator lookup in case
    anything in the DOM shifted, not a cached reference."""
    index = attempt["index"]
    value = attempt["value"]
    raw_entry = attempt["raw_entry"]
    locator = page.locator(f'[data-maester-index="{index}"]')
    try:
        if attempt.get("file"):
            locator.set_input_files(value)
        elif attempt.get("checkbox"):
            locator.check()
        else:
            fill_answer(page, raw_entry, locator, value)
    except Exception:
        pass  # verification on the next round will catch and report this


def verify_and_retry(page, attempted: list) -> tuple:
    """Takes a snapshot of every field this run believes it filled, checks
    each one's real state, and retries any mismatch up to _MAX_FILL_RETRIES
    times before giving up on it. Returns (verified_labels, flagged_notes) -
    anything that never verifies gets demoted out of the "filled" list
    entirely rather than staying reported as a success that isn't real."""
    pending = list(attempted)
    for _ in range(_MAX_FILL_RETRIES + 1):
        failing = [a for a in pending if not verify_filled(page, a)]
        if not failing:
            break
        for a in failing:
            _retry_fill(page, a)

    verified_labels = []
    flagged_notes = []
    for a in attempted:
        if verify_filled(page, a):
            verified_labels.append(a["label"])
        else:
            flagged_notes.append(f"{a['label']} (fill did not verify after {_MAX_FILL_RETRIES + 1} attempts)")
    return verified_labels, flagged_notes
