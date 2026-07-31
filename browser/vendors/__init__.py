"""
vendors/
Job-board-specific scanning logic, split out because each ATS platform
renders its forms with a genuinely different DOM structure - not just
different CSS, different *widget architectures* entirely. Confirmed
directly this session: Ashby's forms use native fieldset-wrapped radio/
checkbox groups AND a custom Yes/No button-toggle widget found nowhere
else, with real question text tied to Ashby's own stable class names
(`ashby-application-form-question-title` and friends) - none of which
means anything on a Greenhouse or Lever form.

The split: a vendor module owns SCANNING (how to find a field and its real
question text on that vendor's markup). The generic fill/verify engine in
browser/fields.py owns FILLING and VERIFYING once a field's tag/options are
known - that part doesn't need to know which vendor produced the tag, only
what the tag means (a native <select>, a radiogroup, a yesnogroup, etc.).
Reuses utils.extract.parse_company_and_source_from_url's existing URL
patterns for detection rather than re-deriving them, so the two stay in
sync (the same lesson career-ops's own detectVendor() reuse note names).
"""

from browser.vendors import ashby, base

_VENDOR_MODULES = {
    "ashby": ashby,
}


def get_adapter(url: str):
    """Returns the vendor-specific scanning adapter for `url`, falling back
    to the generic base adapter for any platform without its own known
    quirks yet (Greenhouse, Lever, Gem, or an unrecognized custom careers
    page) - the generic adapter is not a placeholder, it's the real,
    already-tested behavior every vendor started from."""
    from utils.extract import parse_company_and_source_from_url

    _slug, source = parse_company_and_source_from_url(url)
    module = _VENDOR_MODULES.get(source, base)
    return module.Adapter()
