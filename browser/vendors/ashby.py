"""
vendors/ashby.py
Ashby-specific scanning, layered on top of vendors.base's generic behavior.
Two things confirmed directly on live Ashby listings (Rula) that don't exist
anywhere else in this codebase's testing:

1. A custom "Yes/No" button-toggle widget: two real <button> elements
   ("Yes"/"No") alongside a tabindex="-1" checkbox that only stores boolean
   state and isn't itself a meaningful interactive target. Neither a
   react-select combobox nor a native radio/checkbox group - a third,
   distinct pattern, detected here as tag "yesnogroup" (the generic fill/
   verify engine in browser/fields.py already knows what to do with that
   tag once assigned; only the DETECTION is Ashby-specific).
2. Ashby's own stable, non-hashed class names
   (`ashby-application-form-question-title`, and a scoping container that
   varies between `.ashby-application-form-field-entry`,
   `[data-field-entry-id]`, and a bare `<fieldset>` depending on field
   type) reliably tie a field to its real question text even when the
   label's `for` attribute doesn't resolve to the field's own id - confirmed
   on a type-ahead combobox with no id at all.

The JS below duplicates vendors.base's generic detection rather than trying
to compose two separate JS snippets at runtime - simpler and more reliable
than string-splicing JavaScript, at the cost of needing to port a future fix
to the generic base logic here too if it turns out to matter for Ashby as
well.
"""

from browser.vendors.base import Adapter as BaseAdapter

_ASHBY_SCAN_FIELDS_JS = """
(skipped) => {
  const fields = [];
  const els = document.querySelectorAll('input, textarea, select');
  const seenGroupFieldsets = new Set();
  let i = 0;
  els.forEach(el => {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (skipped.includes(type)) return;
    if (el.getAttribute('aria-hidden') === 'true') return;

    // Ashby's own custom "Yes/No" button-toggle widget.
    if (type === 'checkbox' && el.getAttribute('tabindex') === '-1' && !el.closest('fieldset, [role="group"], [role="radiogroup"]')) {
      const container = el.parentElement;
      const toggleButtons = container ? Array.from(container.querySelectorAll(':scope > button')) : [];
      if (toggleButtons.length >= 2) {
        const entry = el.closest('.ashby-application-form-field-entry, [data-field-entry-id], fieldset');
        const titleEl = entry ? entry.querySelector('.ashby-application-form-question-title') : null;
        const groupLabel = titleEl ? titleEl.innerText.trim() : '';

        const options = [];
        toggleButtons.forEach(btn => {
          btn.setAttribute('data-maester-index', String(i));
          options.push({index: i, label: btn.innerText.trim()});
          i += 1;
        });

        fields.push({
          index: options[0].index,
          tag: 'yesnogroup',
          type: 'button',
          name: el.getAttribute('name') || '',
          id: '',
          placeholder: '',
          aria_label: '',
          label_text: groupLabel,
          options: options,
        });
        return;
      }
    }

    if (type === 'radio' || type === 'checkbox') {
      const fieldset = el.closest('fieldset, [role="group"], [role="radiogroup"]');
      if (fieldset) {
        if (seenGroupFieldsets.has(fieldset)) return;
        seenGroupFieldsets.add(fieldset);

        let groupLabel = '';
        const directLabel = fieldset.querySelector(':scope > label');
        if (directLabel) groupLabel = directLabel.innerText.trim();
        if (!groupLabel) {
          const titleEl = fieldset.querySelector('.ashby-application-form-question-title');
          if (titleEl) groupLabel = titleEl.innerText.trim();
        }
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
    }

    el.setAttribute('data-maester-index', String(i));
    let labelText = '';
    if (el.id) {
      const lbl = document.querySelector(`label[for="${el.id}"]`);
      if (lbl) labelText = lbl.innerText.trim();
    }
    // Ashby-specific fallback: the label's `for` doesn't always resolve to
    // this element's own id (confirmed on a type-ahead combobox input with
    // no id at all, inside a <fieldset> whose <label for="..."> points at a
    // different, unrendered id) - Ashby's stable, non-hashed class names
    // reliably tie a field to its real question text regardless.
    if (!labelText) {
      const entry = el.closest('.ashby-application-form-field-entry, [data-field-entry-id], fieldset');
      const titleEl = entry ? entry.querySelector('.ashby-application-form-question-title') : null;
      if (titleEl) labelText = titleEl.innerText.trim();
    }
    if (!labelText) {
      const parentLabel = el.closest('label');
      if (parentLabel) labelText = parentLabel.innerText.trim();
    }
    // Ashby's own "resume autofill" convenience upload (confirmed directly
    // on a live Rula listing): a second, unlabeled file input near the top
    // of the form. DELIBERATELY LEFT UNLABELED/UNFILLED - uploading to it
    // triggers Ashby's own async resume-parsing, which then tries to
    // auto-populate name/email/phone/etc. WHILE this module's own fill loop
    // is simultaneously trying to fill those same fields through its own,
    // verified process. Confirmed directly this causes real instability
    // (the browser context terminating mid-run, not just a wrong value) -
    // a first attempt at wiring this field in was reverted for exactly this
    // reason. The real, required "Resume" field elsewhere on the form
    // already gets filled correctly without this risk.
    const field = {
      index: i,
      tag: el.tagName.toLowerCase(),
      type: type,
      name: el.getAttribute('name') || '',
      id: el.id || '',
      placeholder: el.getAttribute('placeholder') || '',
      aria_label: el.getAttribute('aria-label') || '',
      label_text: labelText,
      required: el.required || el.getAttribute('aria-required') === 'true',
    };
    if (el.tagName.toLowerCase() === 'select') {
      field.options = Array.from(el.options).map(o => ({value: o.value, label: o.text.trim()}));
    }
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


class Adapter(BaseAdapter):
    SCAN_FIELDS_JS = _ASHBY_SCAN_FIELDS_JS
