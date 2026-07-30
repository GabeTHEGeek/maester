"""
autofill.py
Opens a real, visible browser on a job application page and fills in what
Maester already knows: contact info from the resume, the tailored resume and
cover letter PDFs, and answers to custom questions (reused from the answer
bank when one matches, freshly drafted and flagged when none does). Then it
stops.

HARD RULE, the single non-negotiable constraint of this entire module: this
code never clicks anything that submits an application. That is enforced
structurally, not by asking a model nicely and hoping it holds — the same
lesson this project has already learned the hard way for em dashes, banned
phrases, and JSON truncation (see CLAUDE.md), applied here to something
irreversible instead of cosmetic.

Real-world testing (a live Cribl listing, 2026-07-30) showed this needs one
narrow exception: some career pages render no application fields at all until
a user clicks an "Apply" control first — a reveal action, not a submission.
Refusing to ever click anything meant the tool couldn't see the real form on
those sites at all. So there are now exactly two click-eligible categories,
kept structurally distinct:

  1. REVEAL clicks (_find_apply_reveal_button): opens/scrolls to the actual
     application form. Decided entirely in code against a small closed
     allowlist of exact button/link text ("Apply", "Apply Now", "Apply for
     this job", etc.) — never left to the field-mapping LLM's judgment,
     since this is the one place the click boundary is being extended at
     all. Attempted once, unconditionally, before the field scan runs (an
     earlier version only tried this when the initial scan found too few
     fields, but a cookie-consent banner's own checkboxes inflated that count
     on a real listing and silently skipped the reveal click it needed —
     simpler and more robust to just always look for the one safe, exact-
     match control rather than infer whether the real form is "probably"
     already present). Excludes any element with type="submit" outright, and
     is independently re-checked against _SUBMIT_DENYLIST_SUBSTRINGS even
     though the allowlist and denylist don't overlap by construction — belt
     and suspenders on the one rule that actually matters.
  2. SUBMIT clicks: still categorically absent. There is no allowlist, no
     category, no code path anywhere in this file that clicks a submit
     button, a button with type="submit", or anything matching
     _SUBMIT_DENYLIST_SUBSTRINGS.

A third, narrower click also exists inside _fill_field: some custom dropdown
widgets (react-select and similar - confirmed directly on a live Greenhouse
"Country" field) only register a value when a visible `role="option"` element
is clicked, typed text alone doesn't commit a selection. This is part of
*filling* a field the caller already decided to fill, not a new capability
boundary - it only ever clicks an option matching the exact value already
being filled, never a button, link, or anything resembling submission.
"""

import json
import re

from playwright.sync_api import sync_playwright

from data.answer_bank import find_answer
from engines.llm_fallback import call_with_fallback
from utils.fetch_job import check_liveness, fetch_job_page

FIELD_MAPPING_MODEL = "claude-sonnet-4-5-20250929"

_SKIPPED_INPUT_TYPES = ["hidden", "submit", "button", "reset", "image"]

# Closed, exact-match (post-normalization) allowlist — deliberately small.
# Only text that matches one of these exactly is ever clicked; nothing here
# is a substring/fuzzy match, since a loose match is exactly how a wrong
# button gets clicked on a page this code has never seen before.
_APPLY_REVEAL_PHRASES = {
    "apply",
    "apply now",
    "apply for this job",
    "apply to this job",
    "apply for this role",
    "apply to this role",
    "apply for this position",
    "apply to this position",
    "start application",
    "start your application",
    "begin application",
    "continue to application",
}

# If a candidate's text contains ANY of these, it is never clicked — full
# stop — even if it also happens to match the allowlist above (it shouldn't,
# by construction, but this is checked independently rather than trusted to
# never come up).
_SUBMIT_DENYLIST_SUBSTRINGS = ["submit", "send", "confirm", "finalize", "complete"]

# Real-world testing (the same live Cribl listing) turned up a second, sharper
# problem than wrong-word matching: a plain-text allowlist match ("Apply") hit
# a OneTrust cookie-consent widget's own "Apply" button (id="filter-apply-
# handler", inside a "ot-fltr-btns" container) — completely unrelated to the
# job application, just reusing the same generic label. A wrong click here
# doesn't submit anything, but it's still acting on the wrong element, so any
# candidate nested inside a known cookie-consent/consent-management widget is
# excluded outright, regardless of its own text.
_NON_APPLICATION_ANCESTOR_MARKERS = ["onetrust", "ot-", "cookie", "consent", "gdpr"]


def _normalize_button_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower()).rstrip("!.")


def _looks_like_non_application_widget(el) -> bool:
    """Checks the candidate and its ancestor chain for markers of an
    unrelated widget (cookie-consent tooling, so far) that happens to reuse
    an allowlisted label like 'Apply' for something that has nothing to do
    with a job application."""
    try:
        haystack = el.evaluate(
            """e => {
                let s = '';
                let node = e;
                for (let i = 0; i < 6 && node; i++) {
                    s += ' ' + (node.id || '') + ' ' + (node.className || '');
                    node = node.parentElement;
                }
                return s.toLowerCase();
            }"""
        )
    except Exception:
        return False
    return any(marker in haystack for marker in _NON_APPLICATION_ANCESTOR_MARKERS)


def _find_apply_reveal_button(page):
    """Deterministic, code-only search for a single, unambiguous 'reveal the
    application form' control. Never decided by the field-mapping LLM — this
    is the one place the click boundary is intentionally widened beyond pure
    field-filling, so the decision has to be as auditable and conservative as
    possible. Returns None (do nothing) unless exactly one candidate matches
    the allowlist exactly, isn't a type="submit" element, doesn't also hit
    the submit denylist, and isn't nested inside a known unrelated widget
    (see _looks_like_non_application_widget). Ambiguity (zero or multiple
    matches) means staying safe and doing nothing, not guessing."""
    candidates = page.locator('button, a, [role="button"]').all()
    matches = []
    for el in candidates:
        try:
            if (el.get_attribute("type") or "").lower() == "submit":
                continue
            text = _normalize_button_text(el.inner_text())
            if text not in _APPLY_REVEAL_PHRASES:
                continue
            if any(bad in text for bad in _SUBMIT_DENYLIST_SUBSTRINGS):
                continue  # unreachable given the allowlist; kept as a hard backstop
            if _looks_like_non_application_widget(el):
                continue
            matches.append(el)
        except Exception:
            continue
    if len(matches) == 1:
        return matches[0]
    return None

_SCAN_FIELDS_JS = """
(skipped) => {
  const fields = [];
  const els = document.querySelectorAll('input, textarea, select');
  let i = 0;
  els.forEach(el => {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (skipped.includes(type)) return;
    // Custom combobox widgets (react-select and similar) often keep a
    // second, aria-hidden="true" shadow input purely for HTML5 validation
    // state - not a real, user-facing field, and not something that should
    // ever be filled or even shown to the field-mapping step as if it were
    // one. Confirmed directly on a live Greenhouse form (Tekion): a
    // tabindex="-1" aria-hidden input sat right next to the real "Country"
    // combobox with no label of its own.
    if (el.getAttribute('aria-hidden') === 'true') return;
    el.setAttribute('data-maester-index', String(i));
    let labelText = '';
    if (el.id) {
      const lbl = document.querySelector(`label[for="${el.id}"]`);
      if (lbl) labelText = lbl.innerText.trim();
    }
    if (!labelText) {
      const parentLabel = el.closest('label');
      if (parentLabel) labelText = parentLabel.innerText.trim();
    }
    fields.push({
      index: i,
      tag: el.tagName.toLowerCase(),
      type: type,
      name: el.getAttribute('name') || '',
      id: el.id || '',
      placeholder: el.getAttribute('placeholder') || '',
      aria_label: el.getAttribute('aria-label') || '',
      label_text: labelText,
    });
    i += 1;
  });
  return fields;
}
"""

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

FIELD_MAPPING_SYSTEM_PROMPT = """You map a job application form's raw fields to a
known set of categories, using each field's tag, type, name, placeholder, and
label text. Respond ONLY with valid JSON, no markdown fences, no prose:
{"fields": [{"index": <int>, "category": "<category>", "question_text": "<only for custom_question, the actual question being asked, verbatim from the label>"}]}

Valid categories:
- "first_name", "last_name" - use these, NOT "name", whenever first and last
  name have SEPARATE fields (the overwhelmingly common case: distinct
  "First Name*" / "Last Name*" boxes). Getting this wrong means the full
  name gets typed into both boxes, which is wrong data, not just imprecise -
  treat first/last name detection carefully, never default to "name" when
  two separate name fields are present.
- "name" - ONLY for a single field meant to hold the candidate's whole name
  at once (rare - most forms split first/last).
- "email", "phone", "country" - standard contact fields ("country" means
  country of residence, e.g. for an address section - not a work-
  authorization or visa question, those are "custom_question")
- "linkedin_url", "portfolio_url", "github_url" - profile link fields
- "resume_upload" - a file input for a resume/CV
- "cover_letter_upload" - a file input for a cover letter
- "custom_question" - a free-text question the candidate needs to answer
  (why this company, tools comfort, availability, a behavioral prompt, etc.)
- "skip" - anything else: unrelated fields, dropdowns, checkboxes, consent/
  EEO/self-identification fields, anything you're not confident about

Only ever return "skip" if uncertain - a wrong guess on a mapped field fills
the wrong data into a stranger's application, which is worse than leaving a
field for the human to handle themselves."""


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


def _extract_json(text: str) -> dict:
    text = re.sub(r"```(json)?", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in field-mapping response: {text[:300]!r}")
    return json.loads(match.group(0))


def _draft_custom_answer(question_text, resume_text, company, role_title, api_key, deepseek_api_key):
    """Same no-invention rule as engines/tailor.py: draws only on what's
    actually in the resume, never fabricates an experience or credential to
    answer a question the resume doesn't actually support."""
    prompt = (
        f"Answer this job application question, grounded ONLY in the resume "
        f"below - never invent experience, employers, or metrics not already "
        f"present in it. If the resume doesn't truly support a strong answer, "
        f"write an honest, concise one anyway rather than fabricating specifics.\n\n"
        f"COMPANY: {company}\nROLE: {role_title}\nQUESTION: {question_text}\n\n"
        f"RESUME:\n{resume_text}\n\n"
        f"Respond with ONLY the answer text, 2-4 sentences, no preamble, no "
        f"JSON, no markdown fences."
    )
    text, _provider = call_with_fallback(
        system_prompt="",
        user_prompt=prompt,
        anthropic_api_key=api_key,
        anthropic_model=FIELD_MAPPING_MODEL,
        max_tokens=400,
        deepseek_api_key=deepseek_api_key,
    )
    return text.strip()


def _fill_field(page, locator, value: str) -> None:
    """Fills a value into a field, then checks whether a react-select-style
    option listbox appeared (elements with role="option") and clicks the one
    matching `value` if so. Confirmed directly this matters: a plain
    `.fill()` on a live Greenhouse "Country" combobox set the visible text
    but never actually registered a selection - these widgets only commit a
    value when a real option is clicked, typed text alone doesn't do it. A
    no-op for ordinary text inputs, since no options ever appear for those,
    so this is safe to use as the default fill path everywhere, not just for
    fields already known to be comboboxes."""
    locator.fill(value)
    try:
        option = page.locator('[role="option"]').filter(has_text=value).first
        option.wait_for(state="visible", timeout=1500)
        option.click()
    except Exception:
        pass  # plain text field, or no matching option - the .fill() above already stands


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
    try:
        page_data = fetch_job_page(url)
    except Exception as e:
        return FillResult(status="error", reason=f"Couldn't reach the listing: {e}")

    liveness = check_liveness(page_data["text"], page_data["final_url"])
    if liveness["status"] == "expired":
        return FillResult(status="dead", reason=liveness["reason"])

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
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
    reveal_button = _find_apply_reveal_button(pw_page)
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

    raw_fields = pw_page.evaluate(_SCAN_FIELDS_JS, _SKIPPED_INPUT_TYPES)

    if not raw_fields:
        reason = "No fillable fields detected on this page"
        reason += " (clicked 'Apply' to reveal the form, but still found none)" if reveal_clicked else ""
        reason += " - likely a custom or JS-heavy form. Left open for manual review."
        return FillResult(status="opened", reason=reason, reveal_clicked=reveal_clicked)

    mapping_prompt = "FORM FIELDS (JSON):\n" + json.dumps(raw_fields, indent=2)
    try:
        mapping_text, _provider = call_with_fallback(
            system_prompt=FIELD_MAPPING_SYSTEM_PROMPT,
            user_prompt=mapping_prompt,
            anthropic_api_key=api_key,
            anthropic_model=FIELD_MAPPING_MODEL,
            max_tokens=2000,
            deepseek_api_key=deepseek_api_key,
        )
        mapping = _extract_json(mapping_text).get("fields", [])
    except Exception as e:
        # Mapping failure: partial fill with flags, not a bail-out (PRD
        # decision #3) - every field just gets flagged since none were mapped.
        return FillResult(
            status="opened",
            reason=f"Field mapping failed ({e}). Every field left for manual review.",
            fields_flagged=[f.get("label_text") or f.get("name") or f"field #{f['index']}" for f in raw_fields],
            reveal_clicked=reveal_clicked,
        )

    auto_mapped = []
    flagged = []

    for entry in mapping:
        index = entry.get("index")
        category = entry.get("category", "skip")
        locator = pw_page.locator(f'[data-maester-index="{index}"]')
        field_label = next(
            (f.get("label_text") or f.get("name") or f"field #{index}" for f in raw_fields if f["index"] == index),
            f"field #{index}",
        )

        try:
            if category == "first_name" and contact_info.get("name"):
                first, _, _ = contact_info["name"].partition(" ")
                _fill_field(pw_page, locator, first)
                auto_mapped.append(field_label)
            elif category == "last_name" and contact_info.get("name"):
                _, _, rest = contact_info["name"].partition(" ")
                if rest:
                    _fill_field(pw_page, locator, rest)
                    auto_mapped.append(field_label)
                else:
                    flagged.append(field_label)  # single-word name, no real "last name" to give
            elif category == "name" and contact_info.get("name"):
                _fill_field(pw_page, locator, contact_info["name"])
                auto_mapped.append(field_label)
            elif category == "email" and contact_info.get("email"):
                _fill_field(pw_page, locator, contact_info["email"])
                auto_mapped.append(field_label)
            elif category == "phone" and contact_info.get("phone"):
                _fill_field(pw_page, locator, contact_info["phone"])
                auto_mapped.append(field_label)
            elif category == "country" and contact_info.get("country"):
                _fill_field(pw_page, locator, contact_info["country"])
                auto_mapped.append(field_label)
            elif category == "linkedin_url" and links.get("linkedin_url"):
                _fill_field(pw_page, locator, links["linkedin_url"])
                auto_mapped.append(field_label)
            elif category == "portfolio_url" and links.get("portfolio_url"):
                _fill_field(pw_page, locator, links["portfolio_url"])
                auto_mapped.append(field_label)
            elif category == "github_url" and links.get("github_url"):
                _fill_field(pw_page, locator, links["github_url"])
                auto_mapped.append(field_label)
            elif category == "resume_upload" and resume_pdf_path:
                locator.set_input_files(resume_pdf_path)
                auto_mapped.append(field_label)
            elif category == "cover_letter_upload" and cover_letter_pdf_path:
                locator.set_input_files(cover_letter_pdf_path)
                auto_mapped.append(field_label)
            elif category == "custom_question":
                question_text = entry.get("question_text") or field_label
                bank_entry = find_answer(question_text)
                if bank_entry and bank_entry.get("approved"):
                    _fill_field(pw_page, locator, bank_entry["answer"])
                    auto_mapped.append(field_label)
                else:
                    draft = _draft_custom_answer(
                        question_text, resume_text, company, role_title, api_key, deepseek_api_key
                    )
                    _fill_field(pw_page, locator, draft)
                    pw_page.evaluate(_FLAG_BANNER_JS, index)
                    flagged.append(f"{field_label} (unreviewed AI draft)")
            else:
                flagged.append(field_label)
        except Exception as e:
            flagged.append(f"{field_label} (fill failed: {e})")

    reason = "Clicked 'Apply' to reveal the application form before filling it in." if reveal_clicked else ""
    return FillResult(
        status="opened",
        reason=reason,
        fields_auto_mapped=auto_mapped,
        fields_flagged=flagged,
        reveal_clicked=reveal_clicked,
    )
