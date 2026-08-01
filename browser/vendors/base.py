"""
vendors/base.py
The generic adapter: field scanning and reveal-button detection that isn't
tied to any one ATS platform's markup. Every vendor-specific adapter starts
from this (see ashby.py) rather than duplicating it, and any platform this
project hasn't hit vendor-specific quirks on yet (Greenhouse, Lever, Gem, a
custom careers page like Cribl's) uses this directly, unmodified - this is
real, already-tested behavior, not a stub waiting to be filled in.
"""

import re

_SKIPPED_INPUT_TYPES = ["hidden", "submit", "button", "reset", "image"]

# Closed, exact-match (post-normalization) allowlist for the reveal click —
# deliberately small. Only text that matches one of these exactly is ever
# clicked; nothing here is a substring/fuzzy match, since a loose match is
# exactly how a wrong button gets clicked on a page this code has never
# seen before.
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

# Confirmed directly on a live Cribl listing: a plain-text allowlist match
# ("Apply") hit a OneTrust cookie-consent widget's own "Apply" button,
# completely unrelated to the job application, just reusing the same
# generic label. Any candidate nested inside a known cookie-consent widget
# is excluded outright, regardless of its own text.
_NON_APPLICATION_ANCESTOR_MARKERS = ["onetrust", "ot-", "cookie", "consent", "gdpr"]


def _normalize_button_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower()).rstrip("!.")


def _looks_like_non_application_widget(el) -> bool:
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


_BASE_SCAN_FIELDS_JS = """
(skipped) => {
  const fields = [];
  const els = document.querySelectorAll('input, textarea, select');
  const seenGroupFieldsets = new Set();
  let i = 0;
  els.forEach(el => {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (skipped.includes(type)) return;
    // Custom combobox widgets (react-select and similar) often keep a
    // second, aria-hidden="true" shadow input purely for HTML5 validation
    // state - not a real, user-facing field. Confirmed directly on a live
    // Greenhouse form (Tekion): a tabindex="-1" aria-hidden input sat right
    // next to the real "Country" combobox with no label of its own.
    if (el.getAttribute('aria-hidden') === 'true') return;

    // Native radio/checkbox GROUPS: each option is its own <input>, with
    // the group's real question text in a <label> that's a direct child of
    // the wrapping container, not attached to any single option. Treating
    // each option as its own unlabeled field would hide the actual question
    // from the mapping step entirely. Consolidate into ONE entry per group,
    // with an "options" list the fill step picks a specific option from.
    //
    // The wrapping container is a real <fieldset> on every site tested so
    // far, but that's not the only way a group gets built - many component
    // libraries use a plain <div role="group"> (or role="radiogroup")
    // instead of semantic HTML. Confirmed directly via Playwright's own
    // aria_snapshot() on a live Ashby form: <fieldset> already exposes an
    // IMPLICIT "group" role (that's why it worked without this), but a
    // future site using an explicit role instead of real <fieldset> would
    // have been invisible to a fieldset-only check - checking for either
    // generalizes without costing anything on sites that do use <fieldset>.
    if (type === 'radio' || type === 'checkbox') {
      const fieldset = el.closest('fieldset, [role="group"], [role="radiogroup"]');
      if (fieldset) {
        if (seenGroupFieldsets.has(fieldset)) return;
        seenGroupFieldsets.add(fieldset);

        let groupLabel = '';
        const directLabel = fieldset.querySelector(':scope > label');
        if (directLabel) groupLabel = directLabel.innerText.trim();
        if (!groupLabel) {
          const ariaLabel = fieldset.getAttribute('aria-label');
          if (ariaLabel) groupLabel = ariaLabel.trim();
        }
        if (!groupLabel) {
          const labelledBy = fieldset.getAttribute('aria-labelledby');
          if (labelledBy) {
            const labelEl = document.getElementById(labelledBy.split(' ')[0]);
            if (labelEl) groupLabel = labelEl.innerText.trim();
          }
        }

        const optionInputs = fieldset.querySelectorAll(`input[type="${type}"]`);
        const options = [];
        optionInputs.forEach(optEl => {
          optEl.setAttribute('data-maester-index', String(i));
          let optLabel = '';
          if (optEl.id) {
            const lbl = document.querySelector(`label[for="${optEl.id}"]`);
            if (lbl) optLabel = lbl.innerText.trim();
          }
          options.push({index: i, label: optLabel});
          i += 1;
        });

        if (options.length > 0) {
          fields.push({
            index: options[0].index,
            tag: type === 'radio' ? 'radiogroup' : 'checkboxgroup',
            type: type,
            name: el.getAttribute('name') || '',
            id: '',
            placeholder: '',
            aria_label: '',
            label_text: groupLabel,
            options: options,
          });
        }
        return;
      }
      // radio/checkbox with no wrapping fieldset - fall through below,
      // treated as an ordinary standalone field (e.g. a lone consent box).
    }

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
    const field = {
      index: i,
      tag: el.tagName.toLowerCase(),
      type: type,
      name: el.getAttribute('name') || '',
      id: el.id || '',
      placeholder: el.getAttribute('placeholder') || '',
      aria_label: el.getAttribute('aria-label') || '',
      label_text: labelText,
    };
    // Native <select>: country/university-style selects with hundreds of
    // real <option> elements are common enough to need their own path,
    // using select_option() rather than the click-and-type approach the
    // other widgets need.
    if (el.tagName.toLowerCase() === 'select') {
      field.options = Array.from(el.options).map(o => ({value: o.value, label: o.text.trim()}));
    }
    // Character limit, when the browser will actually enforce one - lets
    // the drafting step stay inside it instead of producing text a plain
    // .fill() would silently truncate.
    const maxlength = el.getAttribute('maxlength');
    if (maxlength && parseInt(maxlength, 10) > 0) {
      field.limit = parseInt(maxlength, 10);
    }
    fields.push(field);
    i += 1;
  });
  return fields;
}
"""


class Adapter:
    """Base vendor adapter: generic scanning + reveal-button detection.
    Subclasses override SCAN_FIELDS_JS (and, if a vendor ever needs it,
    find_reveal_button) to layer vendor-specific detection on top without
    touching this shared baseline."""

    SCAN_FIELDS_JS = _BASE_SCAN_FIELDS_JS
    SKIPPED_INPUT_TYPES = _SKIPPED_INPUT_TYPES

    def find_reveal_button(self, page):
        """Deterministic, code-only search for a single, unambiguous 'reveal
        the application form' control. Never decided by the field-mapping
        LLM - this is the one place the click boundary is intentionally
        widened beyond pure field-filling, so the decision has to be as
        auditable and conservative as possible. Returns None (do nothing)
        unless exactly one candidate matches the allowlist exactly, isn't a
        type="submit" element, doesn't also hit the submit denylist, and
        isn't nested inside a known unrelated widget. Ambiguity (zero or
        multiple distinct matches) means staying safe and doing nothing.

        Confirmed directly on a live Ashby listing (Rula): a wrapping
        element (a plain container div with no button semantics of its own)
        around the real <button> both matched the selector and both had the
        same inherited inner text, producing a spurious two-way "ambiguous"
        result for what is really one logical clickable target. When that
        exact pattern shows up - matches with identical normalized text
        where tag counts are otherwise ambiguous - prefer an actual
        <button> element over a wrapping <a>/[role="button"] with the same
        text, since a real button is the more specific, more likely genuine
        interactive control."""
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

        if len(matches) > 1:
            same_text = {_normalize_button_text(el.inner_text()) for el in matches}
            buttons_only = [el for el in matches if el.evaluate("e => e.tagName") == "BUTTON"]
            if len(same_text) == 1 and len(buttons_only) == 1:
                matches = buttons_only

        if len(matches) == 1:
            return matches[0]
        return None
