# PRD: Auto-Fill Job Applications

**Status:** Draft — not yet built

**Assumption stated up front:** this PRD scopes the custom Playwright + Claude
API build, not the Claude for Chrome extension. That fork was raised in the
original draft and is now resolved — see Decisions Log.

## Problem

Applying to a role after Maester has already scored it and generated a
tailored resume and cover letter still means manually re-entering the same
contact information, uploading the same files, and re-answering the same
handful of custom questions, across every single application. This is pure
repetition, not judgment — exactly the kind of task worth automating without
touching the one step that actually matters.

## Goals

- Eliminate repetitive manual data entry across job applications
- Reuse materials Maester has already generated (tailored resume, cover
  letter) and answers the user has already written and approved
- Leave the user in full control of the one irreversible action in the flow

## Non-goals (explicit, not just implied)

- This tool will never click submit, or any other control that sends,
  finalizes, or transmits an application to an employer, under any
  circumstance. Not as a default that can be changed later, not as a
  "trusted mode" toggle. This is the single hardest constraint in the
  entire feature and every other design choice is subordinate to it. The
  one narrow exception (see Decisions log #4): a single, code-verified
  "Apply"-style click that only reveals/opens the application form is in
  scope, kept structurally distinct from anything that could submit one.
- Not building a general-purpose web agent. Scope is limited to job
  application forms specifically.
- Not attempting to bypass CAPTCHA or bot-detection of any kind. If a site
  blocks automated filling, the feature stops and hands off to the user
  cleanly — it does not try to work around the block.

## User story

The user has already run a listing through Deep Dive and Tailor & Export.
From that same screen, they click "Apply." A visible browser window opens
the real application page, checks it's still live, fills in their contact
info, uploads the tailored resume and cover letter, and answers custom
questions — either reusing something they've already written and approved,
or drafting something new for review. The browser then sits open, fully
filled, waiting for them. They review it and click submit themselves.

## Functional requirements

1. Entry point: a button in the Tailor & Export tab, enabled only once a
   tailored resume and cover letter exist for the current listing.
2. Pre-flight liveness check: reuse `check_liveness()` before opening a
   browser at all; if the posting looks dead, tell the user and stop
   before doing any work.
3. Visible, not headless, browser: the user can watch the fill happen in
   real time, not just receive a finished result.
4. Field detection and mapping: an LLM call (via the existing
   `llm_fallback` module, same fallback behavior as the rest of Maester)
   reads the page's actual field structure and maps fields to known data
   (name, email, phone, LinkedIn, resume upload, cover letter, custom
   question text areas).
5. Standard field fill: contact info and file uploads, using the
   already-generated tailored PDFs.
6. Answer bank for custom questions: a small, structured file of
   previously-written, user-approved answers (tools comfort, why-this-
   company, pattern-recognition, etc. — real material already produced
   this session), checked first before generating anything new. A
   genuinely new question triggers a fresh draft, clearly marked as
   unreviewed.
7. Hard stop before submit: once every field is filled, the browser window
   remains open and untouched at the final state. No further action is
   taken by the tool.
8. Fill log: each auto-fill attempt gets a lightweight record (listing,
   timestamp, which fields were auto-mapped vs. flagged for manual
   attention) so a batch of applications doesn't lose track of what's
   actually been submitted versus just prepared.

## Technical approach

- New module, e.g. `browser/autofill.py`, following the existing package
  structure (`sources/`, `engines/`, `data/`, `utils/`)
- Playwright for browser control
- Field-mapping LLM call reuses `llm_fallback.call_with_fallback`, same
  provider fallback and reliability behavior already proven elsewhere in
  the app, not a separate, untested path
- New dependency: `playwright`, plus its browser binaries

## Success metrics

- Time from "tailored materials ready" to "form fully filled, ready for
  human review" drops meaningfully versus manual entry
- Zero submissions occur without a human directly clicking submit — this
  is a hard pass/fail requirement, not a target to approach

## Risks

- Field-mapping reliability varies by site. Some company career pages
  will have unusual or heavily custom forms the mapping step handles
  poorly. Partial-fill-and-flag is safer than an all-or-nothing failure.
- Site structure changes over time — the same class of fragility that
  already affects `fetch_job.py`'s scraping. No different in kind, just a
  new surface for it.
- Terms of service: most ATS platforms' ToS restrict automated form
  interaction. Auto-filling (versus auto-submitting) is a meaningfully
  different risk profile, but not a zero one — worth being aware of, not
  papering over.
- Generic UI labels get reused for unrelated things on the same page.
  Confirmed directly in testing: an exact-text match on "Apply" hit a
  OneTrust cookie-consent widget's own "Apply" button (its cookie-
  preferences form, unrelated to the job application) before the ancestor-
  context check (see Decisions log #4) was added to exclude it. Any future
  allowlist expansion needs the same defense-in-depth, not just a wider
  word list.

## Decisions log

1. **Playwright + Claude API vs. Claude for Chrome — resolved: Playwright +
   Claude API.** The deciding factor is the hard-stop-before-submit
   constraint. With Playwright, "never click submit" is a code-level fact:
   the tool simply never contains a code path that clicks a submit-like
   element. With Claude for Chrome, that guarantee would instead rely on
   instructing a more autonomous computer-use agent not to submit — and
   this project has already learned, repeatedly (banned phrases, em
   dashes, JSON truncation), that prompt-only rules fail in real use and
   need a code-level backstop. An irreversible, high-stakes action is the
   wrong place to rely on that pattern for the first time. Trade-off
   accepted: Playwright's DOM-based field mapping will need more of our
   own robustness work on unusual/custom forms than a vision-based Chrome
   agent might need out of the box — mitigated by the partial-fill-and-
   flag approach already in Risks.
2. **Where drafted answers to brand-new custom questions get flagged —
   resolved: inline in the browser, not a separate summary.** A separate
   summary is one more place to check that can drift out of sync with
   what's actually in the form — the same class of risk this project has
   already hit once with parallel state (the tenure bug, where the model
   conflated two sources of truth). A visible marker attached directly to
   the actual field (e.g. a colored border or inline banner next to the
   textarea) keeps the flag physically attached to what it's flagging,
   rather than living in a list that has to be cross-referenced.
3. **What happens when field-mapping fails outright — resolved: partial
   fill with flags, not a clean bail-out.** Consistent with the Risks
   section's own conclusion ("partial-fill-and-flag is safer than an
   all-or-nothing failure"). A full bail-out throws away whatever the
   mapper did get right; flagging the unmapped fields and filling the rest
   gives the user strictly more than nothing.
4. **"Apply" vs. "submit" — resolved: an Apply-style reveal click is in
   scope, kept structurally separate from submit.** Real-world testing
   (2026-07-30) on a live Cribl listing showed some career pages render no
   application fields at all until a user clicks "Apply" first — a reveal
   action, not a submission. The original "never click apply" wording was
   too broad; the actual risk is only ever clicking something that sends
   the application. Implemented as two independent code paths: (a) a
   REVEAL click, decided entirely in code against a small closed allowlist
   of exact button/link text ("Apply", "Apply Now", "Apply for this job",
   etc.), never left to the field-mapping LLM's judgment, excluding any
   `type="submit"` element and anything also matching a submit-word
   denylist; (b) SUBMIT clicks, still categorically absent from the code —
   no allowlist, no category, nothing. Verified on two real listings:
   Cribl (no safe reveal candidate found — the page's only "Apply"-labeled
   element turned out to be a OneTrust cookie-consent widget's own button,
   correctly excluded once an ancestor-context check was added — tool
   correctly did nothing rather than click it) and
   `job-boards.greenhouse.io/tekion/...` (reveal click fired correctly,
   contact fields auto-filled, every sensitive/custom question — comp
   expectations, work authorization, conflict-of-interest, reCAPTCHA —
   correctly flagged rather than trusted).
5. **Answer bank match threshold — resolved: require at least two keyword
   hits, not one.** Real-world testing with sample bank entries in place
   surfaced a genuine bug, not just a hypothetical: a Tekion question about
   contractor/agency history ("...name of the agency/company") matched the
   "why_this_company" bank entry purely because "company" was one of its
   keywords, and got silently auto-filled with a completely unrelated
   canned answer — no flag, no indication anything was off. That's the
   exact failure this tool exists to prevent. `data/answer_bank.py`'s
   `find_answer` now requires `_MIN_KEYWORD_HITS = 2` before trusting a
   match; a single coincidental word overlap now correctly falls through to
   a fresh, flagged draft instead. Verified against the real failing case
   (now returns no match) and against two genuine multi-keyword matches
   (still resolve correctly).
6. **First/last name split — resolved: distinct `first_name`/`last_name`
   categories, not one generic `name`.** Real-world testing on the Tekion
   form (which has separate "First Name*" / "Last Name*" boxes, the common
   case) surfaced another silent-wrong-fill bug: the field-mapping prompt
   only had a single "name" category, so the model mapped both boxes to it,
   and the code filled the full "First Last" name string into both —
   auto-mapped, unflagged, wrong. Fixed by adding explicit `first_name` /
   `last_name` categories to the prompt (with an instruction to never
   default to "name" when two separate boxes exist), and splitting
   `contact_info["name"]` on the first space at fill time. Verified
   directly by reading back the filled values: first and last name each
   land in their correct respective fields, not the full name in both.
7. **Custom dropdown widgets — resolved: click the matching visible option
   after filling, don't trust `.fill()` alone.** Real-world testing found
   Tekion's "Country" field is a react-select-style combobox: `.fill()` sets
   the visible text, but the widget only actually registers a selection when
   a real `role="option"` element is clicked. Added `_fill_field()` as the
   default fill path everywhere (not just for fields already known to be
   comboboxes) — it fills, then clicks a matching visible option if one
   appears, and is a safe no-op on ordinary text inputs since no options
   ever render for those. Verified directly: after filling and the
   follow-up click, `aria-expanded` on the combobox goes to `"false"`
   (the listbox closes, meaning a real option was clicked and the
   selection committed), not just left with typed text sitting unregistered
   in the box. Same investigation also found a related scan bug: a hidden
   `aria-hidden="true"` shadow validation input (part of the same widget,
   not a real user-facing field) was showing up in the field scan with no
   label, confusing the mapping step - `_SCAN_FIELDS_JS` now excludes any
   `aria-hidden="true"` element outright.
8. **Answer-crafting workflow — resolved: ingest a listing's questions
   first, then craft answers, then fill.** Manually reverse-engineering
   exact keyword phrases from a raw HTML/field dump for every listing was
   slow and exactly how the keyword-collision bugs (#5) happened in the
   first place. Added `browser.autofill.scan_questions(url, api_key,
   deepseek_api_key)`: runs the same liveness-check → reveal-click → field-
   scan → LLM-mapping pipeline as `open_and_fill`, but only returns the
   `custom_question`-categorized questions' verbatim text — no filling, no
   browser left open. The discovery logic itself was factored out into a
   shared `_discover_and_map()` used by both functions, so a fix to one
   (e.g. the reveal-click hardening) automatically applies to the other
   instead of needing to be duplicated. Verified on a live Reddit listing:
   returned exactly the 4 real open-ended questions, correctly excluding
   "Country"/"Location" (now their own categories) and the privacy-consent
   checkbox (correctly left to `skip`).
9. **Answer bank matching — resolved: exact question-text match first,
   keyword overlap only as a fallback.** The keyword-only approach (fixed
   in #5, but only patched, not redesigned) is inherently collision-prone
   for company-specific compliance questions, which is exactly where the
   real bug occurred. `find_answer()` now tries an exact, normalized match
   on a new `question_text` field first (deterministic, zero collision
   risk — the intended pairing with `scan_questions()`'s verbatim output),
   and only falls back to the keyword-overlap tier (still gated at
   `_MIN_KEYWORD_HITS = 2`) for genuinely reusable general questions ("why
   this company") that get worded differently across employers and will
   never land an exact match. Verified both tiers resolve correctly and
   independently.
10. **Demographic/EEO self-identification and consent checkboxes — resolved:
    a dedicated `demographic_question` category, bank-lookup only, never
    drafted; consent checkboxes explicitly opt-in per-field.** Initially
    these correctly landed in `skip` with no fill attempt at all (the
    default, safest behavior). The user was then asked directly, per
    question, and explicitly chose two things: (a) provide real answers
    once as permanent, reusable facts (stored in `sample_data/answer_bank.json`,
    gitignored, same as the resume) rather than re-answering on every
    application, and (b) auto-check the general privacy-policy consent
    checkbox specifically, after being told exactly what it means. Added
    `demographic_question` as its own category, structurally distinct from
    `custom_question`: it ONLY ever fills from an exact bank match and
    NEVER falls through to `_draft_custom_answer` - a resume has no basis
    to state someone's gender identity, ethnicity, disability, or veteran
    status, so unlike a general custom question, guessing here would mean
    fabricating identity facts, not just missing one. Added
    `consent_checkbox` as a separate category (real `.check()` first,
    falling back to the same click-and-select path as everything else if
    the "checkbox" turns out to be a combobox instead - confirmed directly
    that Reddit's general consent field is exactly that). Both categories
    remain opt-in per field the user explicitly approves, not a default.
11. **Combobox fill reliability — resolved: click before fill, and exclude
    intl-tel-input's own options from the search.** Testing the
    demographic-answer reuse on Reddit surfaced two compounding bugs in
    `_fill_field` (the fix from #7 was necessary but not sufficient): (a)
    `.fill()` alone doesn't reliably make react-select render its own
    option list - it needs a real `.click()` first to open the menu, the
    same interaction a human would do; (b) on any form that also has a
    phone field using the `intl-tel-input` library (confirmed on Reddit's
    form), that library keeps its own full country list in the DOM with
    `role="option"` at all times, regardless of which field is actually
    being filled - an unscoped option search silently grabbed an entry from
    the wrong widget entirely. Fixed by clicking before filling, and
    excluding any option element whose id starts with `"iti-"`. Verified
    directly, not just assumed: after the fix, both the Country field and
    the consent combobox show `aria-expanded="false"` (menu closed) AND
    their visible input clears back to empty - the correct react-select
    behavior when a real selection commits, replacing the raw typed text
    rather than leaving it sitting unregistered in the box.
12. **Silent no-op fills — resolved: `_fill_field` now returns a real
    success/failure signal, and callers must check it.** The #11 fix wasn't
    the whole story. The user caught it directly from a screenshot: all six
    demographic dropdowns still showed their "Select..." placeholder despite
    being reported as successfully auto-mapped. Root cause: the stored
    answer's exact wording didn't match what this specific employer's form
    actually offered (e.g. saved "Man" against a real option list of
    "Male"/"Female"/"Non-binary"/etc. - "Man" matched nothing). `_fill_field`
    had no way to signal that failure - it filled raw text, found no
    matching option, and returned nothing, so every call site kept
    unconditionally reporting success. Fixed on two levels: (a) `_fill_field`
    now returns `True` only when either no option menu ever appears (an
    ordinary text field, where the plain `.fill()` is genuinely the right
    answer) or a real matching option gets clicked; it returns `False` when
    a menu opens but nothing in it matches, and every call site in the fill
    loop now branches on that return value into auto-mapped vs. flagged
    instead of assuming success; (b) the six stored demographic answers were
    corrected to the form's actual exact option text (confirmed by opening
    each dropdown directly and reading its real options - "Man" -> "Male",
    "Heterosexual/Straight" -> "Heterosexual", "I am not a protected
    veteran" -> "No military service", the closest option this specific
    form actually offers for non-veteran status). Re-verified independently
    per field afterward (not just trusting the aggregate result this time):
    all six now show `aria-expanded="false"` and a cleared input for the
    correct value - the real committed-selection signature. The broader
    lesson, worth stating plainly: a stored answer bank entry is only as
    good as its exact match against a given employer's specific option
    wording, and every employer phrases these differently - this will keep
    happening on new listings and needs the same fix-and-verify treatment
    each time, not a one-time patch.
13. **Native radio/checkbox groups — resolved: consolidate into one logical
    field with an options list, fill by checking the matched option.**
    Tested on a live Ashby listing (Rula), a completely different form
    architecture from Greenhouse's react-select comboboxes seen elsewhere:
    Pronouns, gender identity, veteran status, and work-authorization/
    driver's-license questions are all native `<input type="radio">` /
    `<input type="checkbox">` groups wrapped in a `<fieldset>`, with the
    real question text in a `<label>` that's a direct child of the
    fieldset - not attached to any single option. Treating each option as
    its own field (the original behavior) hid the actual question from the
    mapping step entirely and produced dozens of duplicate, unlabeled
    entries. `_SCAN_FIELDS_JS` now detects fieldset-wrapped radio/checkbox
    inputs and consolidates them into one `radiogroup`/`checkboxgroup`
    entry with an `options` list; a new `_check_group_option` finds the
    one option whose label matches the intended answer (exact match
    preferred, substring only if unambiguous) and checks it - never
    guessing among multiple plausible matches, same principle as
    everywhere else. `demographic_question` and `custom_question` both
    route through this transparently via a shared `_fill_answer` entry
    point. Also fixed a related discovery: `_draft_custom_answer` now
    accepts the field's `options` list and, when present, is told to
    answer with exactly one option label verbatim rather than a paragraph -
    the original paragraph-answer approach happened to substring-match
    correctly in testing (a draft starting with "No,..." matched the "No"
    option), but that was luck, not a guarantee, so this closes the gap
    properly instead of relying on it.
14. **Reveal-button false ambiguity — resolved: prefer a real `<button>`
    over a wrapping `<a>`/`[role="button"]` with identical inherited
    text.** Also found on the same Rula listing: the real "Apply for this
    Job" button was wrapped in a plain container element that also matched
    the reveal-click selector and inherited the same text, producing a
    spurious two-way "ambiguous" result (the existing zero-or-multiple-
    matches safety rule correctly refused to click either, but that left
    the tool unable to reveal the form at all). Fixed narrowly: when
    matches share identical normalized text and exactly one of them is a
    real `<button>` tag, prefer that one - re-verified the full regression
    suite afterward (genuine single button, submit-only page, two
    genuinely distinct buttons with different text, and a new case for two
    genuinely distinct buttons sharing the same text) to confirm this
    doesn't weaken the ambiguity safety net in the cases where ambiguity is
    real, only in this specific nested-wrapper false positive.
15. **Native `<select>` support — added proactively, informed by an external
    reference (career-ops's `apply.md`), not yet hit on a real listing.**
    All four real listings tested so far (Cribl, Tekion, Reddit, Rula)
    happened to use either a text-input-backed combobox or a native radio/
    checkbox group - never a genuine `<select>`. That reference doc flags
    huge native selects (country/university dropdowns with 1000+ options)
    as a common real-world pattern elsewhere, with a specific warning: don't
    snapshot the full option list into a prompt, and use `select_option()`
    directly rather than click-and-type. Implemented both: `_SCAN_FIELDS_JS`
    captures a `<select>`'s options directly; a new `_select_native_option`
    uses Playwright's `select_option(label=...)`, matched through the same
    shared `_find_matching_option` exact/substring logic (refactored out of
    `_check_group_option` so both paths stay in sync) - never guessing among
    multiple plausible options. Verified synthetically (no real listing has
    surfaced one yet): a 1500-option select correctly resolves a real match
    and safely returns `False` (not a guess) on a bogus value.
16. **Field-mapping prompt bloat — resolved: cap options shown to the LLM,
    keep the full list for the actual fill.** Testing the native-select
    fix directly surfaced the exact anti-pattern career-ops's docs warned
    against: a 1500-option field's ENTIRE option list was being embedded in
    the field-mapping prompt, for zero benefit - the mapping step only
    needs enough to recognize "this is a country-type field," not every
    choice. Fixed by capping any field's `options` list to 15 entries
    (plus an `options_truncated_count`) in the copy sent to the LLM, while
    `raw_fields` - the untruncated version the actual fill step reads from
    - keeps everything. Verified directly: the truncated prompt was ~1.2KB
    instead of the tens of KB the full list would have cost, and the fill
    step still correctly matched and selected the right option using the
    complete untruncated list.
17. **Character-limit awareness — added alongside the above, informed by
    the same reference doc's field-contract idea.** `_SCAN_FIELDS_JS` now
    captures a text field's real `maxlength` when the browser enforces one.
    `_draft_custom_answer` is told the limit and asked to stay within it,
    with a hard backstop truncation if it doesn't - preventing a plausible
    "looks filled, actually cut off mid-sentence" failure (a plain `.fill()`
    silently truncates to `maxlength`, the same failure shape as several
    bugs already fixed this session) before it's ever been directly
    observed on a real listing.
18. **Fields silently vanishing from every output — resolved: backfill any
    index the mapping call didn't return.** User-reported symptom:
    "fields get skipped/flagged that should be fillable." Root cause,
    confirmed directly: the field-mapping LLM call can omit a field's index
    from its JSON response entirely (a partial/truncated response, or just
    an oversight), and nothing downstream ever checked for that - an
    omitted field wasn't filled, wasn't flagged, didn't appear anywhere,
    as if it had never existed on the page. `_discover_and_map` now
    compares every `raw_fields` index against what the mapping call
    actually returned and backfills a `"skip"` entry for anything missing,
    so a gap in the LLM's response becomes a visible flagged field instead
    of a silent disappearance. Verified synthetically: a mapping response
    that omits two of three indices now correctly ends up covering all
    three.
19. **Non-deterministic name-field categorization — resolved: explicit,
    fixed rules instead of per-field judgment.** Also part of the same
    user report: identical back-to-back runs against the same Rula listing
    categorized its "First and Last Name (Legal Name)" field differently
    each time - sometimes `name` (correctly auto-filled), sometimes
    `custom_question` (triggering a nonsensical AI-drafted "answer" to what
    is just a name field). The prompt now states this as a fixed rule, not
    a per-field judgment call: every field asking for a combined first+last
    name is always `name`, however many such fields a form has (Preferred
    Name and Legal Name both count); anything name-adjacent but not a real
    name field (Middle Name, Nickname) is always `skip`, never drafted.
    Re-ran the same listing twice after the fix: both runs now correctly
    and identically auto-map both name fields and flag Middle Name.
20. **Post-fill verification pass — added per explicit user request, closing
    the loop on every "reported filled, actually wasn't" bug this session.**
    User's framing: after filling the form, take a snapshot, compare
    against what was reported, fix anything wrong, and repeat until
    correct. Important scope boundary, stated explicitly rather than left
    implicit: this verifies that fields the tool *attempted* to fill
    actually took - it does not force answers into fields correctly left
    blank (an unmatched demographic question, reCAPTCHA, an unapproved
    consent checkbox). "Every field filled" would mean guessing at things
    this tool has refused to guess at all session; that boundary doesn't
    move. Implemented as `_verify_and_retry`: every successful fill is now
    recorded with the exact value and mechanism used (not just its label),
    then re-checked against the field's real DOM state (input value,
    checked state, or selected option, matching how each widget type
    actually confirms a real commit) up to `_MAX_FILL_RETRIES = 2` times,
    retrying with the same inputs on a mismatch. Anything still unverified
    after that is demoted out of the auto-filled list entirely into
    flagged, rather than staying reported as a success that isn't real.
    Verified two ways: a field started genuinely empty (the real bug
    pattern from earlier this session) is caught and actually fixed by the
    retry, confirmed by reading its real value afterward; a genuinely
    unfillable field (no matching option exists at all) is correctly
    demoted to flagged after exactly 3 bounded attempts, not stuck
    retrying indefinitely.
21. **A third distinct widget pattern on the same Ashby form: a custom
    Yes/No button-toggle — resolved with its own tag and fill/verify
    logic.** Discovered while wiring in real user-supplied answers for
    Rula's work-authorization and experience-screening questions: neither
    react-select nor native radio/checkbox, but two real `<button>`
    elements ("Yes"/"No") alongside a `tabindex="-1"` checkbox that only
    stores boolean state and isn't itself a meaningful interactive target.
    Added a `yesnogroup` tag - detected via the checkbox-with-sibling-
    buttons shape, not any hashed class name - with its own fill path
    (click the matched button, reusing `_check_group_option`'s exact/
    substring matching) and its own verification signal. That verification
    needed a real fix mid-testing: the shared boolean checkbox looked like
    the obvious signal, but clicking "No" can leave it at `checked=False`,
    which is indistinguishable from "never answered" - confirmed directly
    as a live false-negative ("fill did not verify after 3 attempts" on a
    field that actually had been filled correctly). Fixed by checking the
    clicked button's own CSS state instead (Ashby marks the selected option
    with a class containing "active" - the hash suffix varies per build,
    but that substring is stable). Re-verified directly for both Yes and
    No afterward.
22. **Label discovery for two more field shapes on the same form —
    resolved: a broader, still-targeted ancestor search.** The same
    real-answer wiring surfaced two more previously-unlabeled field types:
    the Yes/No toggle's real question text lives in a
    `.ashby-application-form-question-title` element scoped to an ancestor
    that varies by field type (a `.ashby-application-form-field-entry` div
    for some fields, a bare `[data-field-entry-id]` div or a `<fieldset>`
    for others - confirmed by inspecting several fields directly rather
    than assuming one wrapper class covers all of them). `_SCAN_FIELDS_JS`
    now searches `.closest('.ashby-application-form-field-entry,
    [data-field-entry-id], fieldset')` as a single broadened fallback,
    fixing "Current State of Residency" and "Race identity" (previously
    invisible to the mapping step entirely) alongside the Yes/No toggles.
23. **"Pronouns" mis-categorized as `skip` — resolved with an explicit
    prompt example.** A real saved answer ("He/him/his") for Rula's
    Pronouns field didn't get applied - not a matching bug, a
    categorization bug: the field-mapping call put it in `skip`, never
    reaching the bank-lookup step at all. The `demographic_question`
    category description named gender identity, veteran status, etc. by
    example but not pronouns specifically; added it explicitly. Re-verified:
    Pronouns now correctly auto-fills from the saved answer.
24. **Two of seven user-supplied answers didn't match this listing's actual
    current question text at all — surfaced, not silently forced.** Before
    wiring anything in, a check against the live page's real wording found
    one answer aimed at a stricter threshold than given ("4+ years" vs. the
    real "at least 5 years" of PM experience) and one aimed at a question
    that doesn't exist on this form at all (A/B testing vs. the real
    question, about complex workflow redesign). Asked the user directly
    for each rather than assuming equivalence or forcing the given answer
    onto a different question; got an explicit "yes, I have 5+ years" for
    the first, and "draft an honest answer from the resume, still flagged"
    for the second. Final result after all fixes in this batch: 14 of 22
    fields auto-filled and verified (up from 7 at the start of this round),
    8 correctly flagged (2 real Rula-specific questions correctly drafted
    from the resume, not from a mismatched answer).
25. **"Current State of Residency" mis-categorized as `city` — resolved
    with a dedicated `state` category.** Adding a real, verified answer
    ("Maryland") for this field didn't work: it stayed flagged instead of
    auto-filling. Root cause, confirmed directly: the field-mapping prompt
    only had "country" and "city" as location categories, so the model
    put a state-of-residency field under "city" - the fill loop then tried
    to fill the candidate's actual city ("Baltimore") into a field
    expecting a US state name, which correctly failed verification (no
    state option matches a city name) and got flagged, but never even
    reached the answer bank in the first place, since "city" routes
    through `contact_info` directly, not `find_answer`. Added "state" as
    its own category and its own `contact_info["state"]` handling,
    parallel to the existing country/city ones - more generalizable than a
    one-off per-question answer-bank entry, since any employer's own
    "state of residence" field can now use it. Re-verified independently
    after the fix: the field now shows a real committed selection (the
    input directly contains "Maryland," a valid alternate confirmation
    signal alongside the aria-expanded-false / cleared-input pattern seen
    on other comboboxes). Final count after this fix: 15 of 22 fields
    auto-filled and verified.
26. **A mid-session tooling incident, worth recording plainly: repeated
    test runs left stale Chromium processes that caused a later run to
    hang.** User-reported: "it froze." Diagnosis confirmed two things
    directly rather than guessing: an earlier run's browser had errored
    out mid-fill ("Target page, context or browser has been closed") and
    left its Chromium process running; a subsequent retry then hung
    waiting on a resource the stale process still held, with no live
    Python interpreter process behind the stuck shell. Resolved by killing
    all `chrome-mac-arm64/Google Chrome for Testing` processes for a clean
    slate, then re-running successfully. Not a bug in `browser/autofill.py`
    itself, but a real operational gap worth naming: this module has no
    cleanup path for a browser that errors out mid-run (by design, the
    happy path deliberately leaves the browser open for review - but nothing
    currently closes one that failed instead of finishing). A future
    improvement, not implemented here: detect a mid-run Playwright
    connection error specifically and close that browser's own resources
    before returning an error result, rather than leaving it to accumulate.

27. **Architecture change, user-directed: split scanning by job board, and
    replace exact-text answer matching with a structured profile + semantic
    topic matching.** Prompted directly by two observations: the exact-text
    answer bank meant the same real question, worded differently across
    employers ("Are you currently authorized to work in the U.S.?" vs. "Are
    you currently eligible to work in the United States of America?"),
    needed a separate saved entry each time instead of recognizing they're
    the same question; and the vendor-specific scanning logic (Ashby's
    class names, its Yes/No widget) was mixed into the same file as the
    generic, vendor-agnostic fill/verify engine, which would only get
    messier as more platforms' quirks accumulated.

    Three changes, built together:
    - **File split**: `browser/vendors/` now owns per-platform SCANNING
      (finding and labeling fields on that vendor's specific markup) -
      `vendors/base.py` holds the generic, already-tested behavior every
      vendor starts from (used directly by Greenhouse, Lever, Gem, and any
      unrecognized custom careers page); `vendors/ashby.py` layers Ashby's
      specific detection (the Yes/No button-toggle, its stable class-name
      label fallback) on top. Vendor detection reuses
      `utils.extract.parse_company_and_source_from_url` rather than
      re-deriving URL patterns, so the two stay in sync. `browser/fields.py`
      now holds the generic FILL/VERIFY engine (react-select handling,
      native `<select>`, group matching, the whole verify-and-retry system)
      - this part doesn't need to know which vendor produced a field's tag,
      only what the tag means, so it stays vendor-agnostic. `autofill.py`
      is now orchestration only. Re-verified after the split: identical
      15/22 result on Rula, confirming the refactor changed nothing
      behaviorally.
    - **`data/profile.py` + `sample_data/profile.json`** (gitignored, real
      personal facts - same protection as the resume): a flat table of
      STATIC facts (work authorization, demographics, logistics) keyed by a
      stable topic string, replacing the old per-question exact-text bank
      entries for anything that's really just a fact about the candidate,
      not a company-specific narrative. Each topic's value is a LIST of
      acceptable phrasings, not a single string - confirmed directly this
      matters: "Man" and "Male" mean the same fact but don't substring-match
      each other, and different employers' dropdowns use one or the other.
      Deliberately NOT migrated: questions whose real answer depends on the
      specific wording, not a static fact (e.g. "do you have at least 5
      years of X experience" - the threshold in the question matters, not
      just a stored yes/no) - those stay on the existing resume-grounded
      drafting path, which already reasons about them correctly.
    - **Semantic topic matching**: the field-mapping prompt now receives the
      list of topics the profile already has answers for, and is asked to
      recognize when a `demographic_question`/`custom_question` field is
      REALLY asking about one of them, however differently worded, tagging
      it with that exact topic string (or omitting it entirely if unsure -
      never inventing a new topic, never guessing). `_try_topic_answer`
      tries every saved phrasing for a matched topic against the specific
      form before falling back to the old exact-text bank, then to fresh
      drafting.

    Verified conclusively, not just assumed: ran the full Rula fill with
    `sample_data/answer_bank.json` emptied to `[]` entirely. Every fact-based
    field (pronouns, gender identity, race identity, veteran status, work
    authorization, visa sponsorship) still auto-filled and verified
    correctly - proof the profile/topic system, not the old bank, is doing
    the work now. The one field that changed behavior did so correctly and
    as designed: the "5 years experience" question (never migrated to the
    profile, since it's a threshold judgment, not a fact) now falls through
    to fresh resume-grounded drafting instead of a stale bank entry, and
    still produces the right answer.
28. **Wiring the Ashby resume-autofill upload — attempted, then reverted
    after a real regression, not a hypothetical one.** After confirming
    field #0 was Ashby's own "upload your resume to prefill this form"
    convenience input (identified via its stable
    `ashby-application-form-autofill-input-root` container class), the user
    approved reusing the same resume PDF for it. Wiring it in immediately
    broke the run: two consecutive attempts both ended in the browser
    context terminating mid-fill ("Target page, context or browser has been
    closed"), the same failure shape as the tooling incident in #26 - but
    this time the user directly diagnosed the actual cause by watching it
    happen live: uploading to that field triggers Ashby's own asynchronous
    resume-parsing, which then tries to auto-populate name/email/phone/etc.
    *at the same time* this module's own fill loop is independently trying
    to fill those same fields through its own, already-verified process - a
    genuine race condition between two systems writing to the same DOM
    concurrently, not random flakiness or a leftover process. Reverted the
    label wiring entirely; the field goes back to being flagged and
    untouched, exactly as before. Re-verified: the same test that crashed
    twice with the field wired in ran clean immediately after reverting -
    same stable 14/22 result, no errors. The real, required "Resume" field
    elsewhere on the form already fills correctly without this risk, so
    nothing was actually lost by not automating this one.
29. **Years-of-experience gate questions and "Middle Name" moved from
    per-listing drafting/skip to static profile facts - a real user
    correction, not a hypothetical improvement.** Feedback on a live Rula
    run, verbatim: "Why are you drafting answers that you should already
    know. I have over 15 years in tech, 7+ in product... you shouldn't need
    an approval." "Do you have at least N years of X experience" questions
    were originally excluded from data/profile.py on purpose (see that
    file's docstring, pre-edit) - reasoned as depending on the number in
    the question, not a static fact. In practice this meant redrafting and
    reflagging the same true "Yes" on every single listing. Fixed by adding
    a static `experience_years` fact ({"total": 15, "product_management":
    7}) and a small deterministic resolver,
    `browser.autofill._resolve_experience_threshold`, that parses the
    threshold number out of the question text, picks the right domain
    (checking for "product management" before falling back to "total" -
    the two numbers differ, so a domain-specific gate question needs the
    domain-specific fact, not the total), and answers Yes/No without ever
    calling the drafting LLM or flagging it as unreviewed. Falls through to
    the existing drafting path unchanged if the question doesn't parse as a
    numeric threshold, or if the resolved answer isn't offered as a real
    option on this particular form.
    Separately, the same feedback covered "Middle Name": "I have no Middle
    name, should be blank or N/A if required." This field was previously
    lumped into the generic "skip" category (deliberately, since a made-up
    middle name would be fabricating a fact) - the fix isn't drafting one,
    it's recognizing "N/A" is the honest, standard answer for a REQUIRED
    field when no middle name exists. Added a dedicated "middle_name"
    category, a `required` flag now captured directly in both vendor
    adapters' field-scanning JS (`el.required || aria-required`), and
    logic that fills "N/A" only when the field is actually required,
    otherwise leaves it genuinely blank (flagged, not fabricated) exactly
    as before.
30. **"Have you ever been an employee/contractor at [Company]?" and
    location fields (state/city/country) moved from drafted-and-flagged
    or silently skipped to fact-checked-in-code.** Direct user feedback:
    "Why are you asking me that when you have my resume?" for the Rula
    prior-employment questions, and "Current State of Residency is MD...
    something you should know. You have the reference files and profile
    data" for a location field that was silently skipped.
    Two separate root causes, two separate fixes:
    - `_resolve_prior_employer_relationship` (browser/autofill.py):
      "have you ever been an employee/contractor at X" / "...credentialed
      with X" questions are, for a first-time applicant, directly
      verifiable against the resume - if the employer's name never
      appears in it, "No" is the actual, checkable fact, not a guess.
      Deliberately still falls through to normal drafting (flagged, as
      before) in the one case this can't answer safely: the company DOES
      appear in the resume, where the real nature of that relationship
      needs actual judgment, not a flat rule.
    - `_resolve_location` (browser/autofill.py): the "state"/"city"/
      "country" categories only ever checked resume-parsed contact_info,
      with no fallback to the profile's own saved city/state/country facts
      - so a form whose combobox didn't get auto-split from the resume's
      contact block by parse_contact_info fell all the way through to
      silently flagged, even though the real answer was already sitting in
      sample_data/profile.json. Now checks contact_info first, profile
      second, same "known fact, don't ask twice" precedent as every other
      profile-backed category.
    Re-verified live on Rula: both prior-relationship questions and
    "Current State of Residency" moved from flagged to auto-mapped: no
    resume/profile-derivable question is left unresolved anymore.
    Deliberately NOT extended to genuinely creative/subjective
    custom_questions ("What snack fuels your best ideas?", "describe a
    time you redesigned a workflow") - those still get drafted and flagged
    for review, since there's no fact in the resume to check them against.

## Open questions

None remaining as of this draft. All thirty forks raised across drafting
and real-world testing are resolved above. Item #26 names one real,
deliberately-deferred follow-up (stale-browser cleanup on a mid-run error)
rather than a fork that's actually closed.
