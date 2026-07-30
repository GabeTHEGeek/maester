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

Gabriel has already run a listing through Deep Dive and Tailor & Export.
From that same screen, he clicks "Apply." A visible browser window opens
the real application page, checks it's still live, fills in his contact
info, uploads the tailored resume and cover letter, and answers custom
questions — either reusing something he's already written and approved, or
drafting something new for review. The browser then sits open, fully
filled, waiting for him. He reviews it and clicks submit himself.

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
   and the code filled the full "Gabriel Pendleton" string into both —
   auto-mapped, unflagged, wrong. Fixed by adding explicit `first_name` /
   `last_name` categories to the prompt (with an instruction to never
   default to "name" when two separate boxes exist), and splitting
   `contact_info["name"]` on the first space at fill time. Verified
   directly by reading back the filled values: "Gabriel" and "Pendleton"
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

## Open questions

None remaining as of this draft. All seven forks raised across drafting and
real-world testing are resolved above.
