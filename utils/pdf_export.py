"""
pdf_export.py
Converts the tailored resume/cover letter Markdown into simple, single-column
PDFs designed to parse cleanly through ATS systems — no tables, no multi-column
layouts, no images, standard fonts only. Fancy HTML-to-PDF resume templates
often look great to a human and parse terribly to an ATS; this deliberately
avoids that trap. (The Core Competencies tags are the one deliberate exception
to "no tables" — a light background box per skill, which ATS parsers handle
fine since the text itself is still linear, selectable text.)
"""

import re
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

_VALEDICTIONS = (
    "sincerely", "best regards", "kind regards", "warm regards", "regards",
    "warmly", "respectfully", "best", "many thanks", "thank you", "thanks",
)


def _looks_like_signoff(paragraph: str, candidate_name: str) -> bool:
    """True if `paragraph` is the model's own closing line despite being told
    not to write one (the sign-off is handled entirely in code below) - the
    bare name-only case (e.g. just "Gabriel Pendleton") AND the valediction-
    plus-name case (e.g. "Sincerely, Gabriel Pendleton" or "Sincerely," /
    "Gabriel Pendleton" as two separate short paragraphs). Real evidence:
    the exact-name-only check this replaced missed "Sincerely, Gabriel
    Pendleton" entirely, since that string is never equal to the bare name,
    so a generated cover letter ended up with the model's own "Sincerely,
    <name>" left in as a body paragraph AND the code's own "Best regards,
    <name>" signoff appended after it - the name (and a valediction) shown
    twice, back to back."""
    if not candidate_name:
        return False
    normalized = re.sub(r"[,.]", "", paragraph.strip().lower()).strip()
    name_normalized = re.sub(r"[,.]", "", candidate_name.strip().lower()).strip()
    if normalized == name_normalized:
        return True
    for word in _VALEDICTIONS:
        if normalized == word:
            return True
        if normalized.startswith(word) and normalized[len(word):].strip() == name_normalized:
            return True
    return False


_STYLES = getSampleStyleSheet()
_LINK_COLOR = "#1a5276"
_PILL_BG = colors.HexColor("#DCEEFB")
_PILL_TEXT = "#1a3a5c"

_NAME_STYLE = ParagraphStyle(
    "NameStyle", parent=_STYLES["Title"], fontSize=18, spaceAfter=2, alignment=1
)
_CONTACT_STYLE = ParagraphStyle(
    "ContactStyle", parent=_STYLES["Normal"], fontSize=9, alignment=1, spaceAfter=2,
    textColor="#444444",
)
_LINKS_STYLE = ParagraphStyle(
    "LinksStyle", parent=_STYLES["Normal"], fontSize=9, alignment=1, spaceAfter=12,
)
_TAGLINE_STYLE = ParagraphStyle(
    "TaglineStyle", parent=_STYLES["Normal"], fontSize=10.5, alignment=1, spaceAfter=2,
    textColor="#444444",
)
_LETTER_DATE_STYLE = ParagraphStyle(
    "LetterDateStyle", parent=_STYLES["Normal"], fontSize=9.5, textColor="#555555",
    spaceAfter=16,
)
_SIGNOFF_STYLE = ParagraphStyle(
    "SignoffStyle", parent=_STYLES["Normal"], fontSize=11, spaceAfter=2,
)
_SIGNOFF_NAME_STYLE = ParagraphStyle(
    "SignoffNameStyle", parent=_STYLES["Normal"], fontSize=11, fontName="Helvetica-Bold",
)
_SECTION_STYLE = ParagraphStyle(
    "SectionStyle", parent=_STYLES["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4,
    textColor="#1a1a1a", borderWidth=0,
)
_SUBSECTION_STYLE = ParagraphStyle(
    "SubsectionStyle", parent=_STYLES["Normal"], fontSize=11, spaceBefore=6, spaceAfter=6,
    fontName="Helvetica-Bold",
)
_DATE_STYLE = ParagraphStyle(
    "DateStyle", parent=_STYLES["Normal"], fontSize=9, textColor="#555555", spaceAfter=4,
    fontName="Helvetica-Oblique",
)
_DATE_RIGHT_STYLE = ParagraphStyle(
    "DateRightStyle", parent=_STYLES["Normal"], fontSize=10, textColor="#555555",
    fontName="Helvetica-Oblique", alignment=2,  # 2 = right-aligned
)
_BULLET_STYLE = ParagraphStyle(
    "BulletStyle", parent=_STYLES["Normal"], fontSize=11, leftIndent=16, bulletIndent=4,
    spaceAfter=3, leading=15,
)
_BODY_STYLE = ParagraphStyle(
    "BodyStyle", parent=_STYLES["Normal"], fontSize=11, spaceAfter=4, leading=15,
)
_LETTER_BODY_STYLE = ParagraphStyle(
    "LetterBodyStyle", parent=_STYLES["Normal"], fontSize=11, spaceAfter=12, leading=16,
)
_COMPETENCY_STYLE = ParagraphStyle(
    "CompetencyStyle", parent=_STYLES["Normal"], fontSize=8, textColor=_PILL_TEXT,
    alignment=1, leading=10,
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _inline_markdown_to_reportlab(text: str) -> str:
    """Convert **bold** and *italic* to reportlab's mini-markup, and escape
    any stray ampersands/angle brackets so Paragraph doesn't choke on them."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", text)
    return text


def _linkify_emails(text: str) -> str:
    """Wraps any email address found in plain text with a clickable mailto link."""
    def repl(m):
        email = m.group(0)
        return f'<a href="mailto:{email}"><font color="{_LINK_COLOR}"><u>{email}</u></font></a>'
    return _EMAIL_RE.sub(repl, text)


def _hyperlink(url: str, display_text: str = None) -> str:
    """Builds reportlab markup for a clickable, underlined, colored link."""
    if not url:
        return ""
    display_text = display_text or url
    href = url if url.startswith(("http://", "https://", "mailto:")) else f"https://{url}"
    return f'<a href="{href}"><font color="{_LINK_COLOR}"><u>{display_text}</u></font></a>'


def _build_links_line(linkedin_url: str = "", portfolio_url: str = "", github_url: str = "") -> str:
    """Builds a single centered line of hyperlinked labels for whichever
    links were actually provided — never invents one that's missing."""
    parts = []
    if linkedin_url:
        parts.append(_hyperlink(linkedin_url, "LinkedIn"))
    if portfolio_url:
        parts.append(_hyperlink(portfolio_url, "Portfolio"))
    if github_url:
        parts.append(_hyperlink(github_url, "GitHub"))
    return "&nbsp;&nbsp;|&nbsp;&nbsp;".join(parts)


def _build_competencies_flowables(competencies: list, content_width_inches: float = 7.0) -> list:
    """Renders a 'CORE COMPETENCIES' section as light-blue tag/pill boxes,
    packed left-to-right and wrapped onto new rows as needed. Square corners,
    not rounded — reportlab's Table doesn't support rounded cell corners
    without custom canvas drawing, and square pills are still a clear visual
    match for the tag-cloud look with far less complexity."""
    if not competencies:
        return []

    flowables = [Paragraph("CORE COMPETENCIES", _SECTION_STYLE)]

    max_width = content_width_inches * inch
    char_width = 4.6  # rough estimate for 8pt Helvetica
    h_padding = 16
    gap = 6

    rows, current_row, current_width = [], [], 0
    for comp in competencies:
        pill_width = len(comp) * char_width + h_padding
        if current_row and current_width + gap + pill_width > max_width:
            rows.append(current_row)
            current_row, current_width = [], 0
        current_row.append(comp)
        current_width += (gap if current_row[:-1] else 0) + pill_width
    if current_row:
        rows.append(current_row)

    for row in rows:
        cell_data, col_widths, style_commands = [], [], [
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        col = 0
        for i, comp in enumerate(row):
            cell_data.append(Paragraph(comp, _COMPETENCY_STYLE))
            col_widths.append(len(comp) * char_width + h_padding)
            style_commands.append(("BACKGROUND", (col, 0), (col, 0), _PILL_BG))
            col += 1
            if i < len(row) - 1:
                cell_data.append("")
                col_widths.append(gap)
                col += 1
        t = Table([cell_data], colWidths=col_widths, hAlign="LEFT")
        t.setStyle(TableStyle(style_commands))
        flowables.append(t)
        flowables.append(Spacer(1, 4))
    flowables.append(Spacer(1, 4))
    return flowables


_US_LOCATION_HINTS = [
    "usa", "us", "united states", "u.s.", "remote - us", "remote (us",
    "america", "canada",  # Canada commonly pairs with Letter too
]


def _detect_page_size(location: str):
    """US/Canada listings get Letter (the norm there); everything else gets
    A4 (the norm nearly everywhere else). Defaults to Letter if location is
    empty/unrecognized, since most of this candidate's searches target US
    remote roles."""
    if not location:
        return LETTER
    loc_lower = location.lower()
    if any(hint in loc_lower for hint in _US_LOCATION_HINTS):
        return LETTER
    # Recognizable non-US signals -> A4
    intl_hints = ["europe", "uk", "united kingdom", "germany", "france", "spain",
                  "worldwide", "emea", "asia", "australia", "brazil", "latam"]
    if any(hint in loc_lower for hint in intl_hints):
        return A4
    return LETTER


def _build_role_date_row(role_text: str, date_text: str, content_width_inches: float) -> Table:
    """Renders a role/company line and its date range on the same row, date
    pushed to the far right — the standard resume layout, rather than the
    date sitting on its own left-aligned line underneath."""
    role_para = Paragraph(_inline_markdown_to_reportlab(role_text), _SUBSECTION_STYLE)
    date_para = Paragraph(_inline_markdown_to_reportlab(date_text), _DATE_RIGHT_STYLE)
    total_width = content_width_inches * inch
    date_width = 2.0 * inch
    role_width = total_width - date_width
    t = Table([[role_para, date_para]], colWidths=[role_width, date_width])
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]))
    return t


def _is_date_line(text: str) -> bool:
    t = text.strip()
    return t.startswith("*") and t.endswith("*") and not t.startswith("**")


# The tailoring prompt requires "- " bullets, but that's a request, not a
# guarantee (see CLAUDE.md) - a source resume pasted as plain extracted PDF
# text often already uses one of these characters as its own bullet marker,
# and a model asked to "keep the same structure" has been observed carrying
# it through unchanged instead of normalizing it. Recognized here as a
# backstop so those still render as real bulleted list items instead of
# silently falling through to a plain left-aligned paragraph with the raw
# bullet character stuck in the text.
_BULLET_PREFIXES = ("- ", "* ", "• ", "● ", "◦ ", "– ")


def _strip_bullet_prefix(stripped: str) -> str:
    for prefix in _BULLET_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return stripped


def render_resume_pdf(
    markdown_text: str,
    output_path: str,
    location: str = "",
    candidate_tagline: str = "",
    linkedin_url: str = "",
    portfolio_url: str = "",
    github_url: str = "",
    core_competencies: list = None,
) -> str:
    """Parses the resume Markdown line-by-line into flowables and writes a PDF.

    Header handling uses an explicit state machine rather than a boolean flag:
    the previous version tried to detect the contact line via 'not seen_name',
    but seen_name was already True by the time that line was reached (it's
    set on the name line itself), so the contact line never actually matched
    and fell through to plain left-aligned body text. This tracks distinct
    stages instead, so the line immediately following the name — whatever it
    contains — is always treated as the contact line and centered correctly.
    """
    page_size = _detect_page_size(location)
    doc = SimpleDocTemplate(
        output_path,
        pagesize=page_size,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    content_width_inches = (page_size[0] / inch) - 1.5  # page width minus L+R margins

    story = []
    lines = markdown_text.splitlines()

    # The tailoring prompt requires "# Name" as line 1, but that's a request,
    # not a guarantee - confirmed directly: a source resume pasted as plain
    # extracted text (no Markdown at all) produced tailored output that also
    # skipped the "# " prefix on its own name line. Without this, the header
    # state machine below never leaves "awaiting_name", so the contact line
    # right after ALSO falls through to plain left-aligned body text - one
    # missing "# " silently breaks both lines, not just the name. The first
    # non-blank line of a resume is always the candidate's name, so normalize
    # it here rather than trusting the model got the prefix right.
    for idx, raw_line in enumerate(lines):
        if raw_line.strip():
            if not raw_line.strip().startswith("# "):
                lines[idx] = f"# {raw_line.strip()}"
            break

    header_stage = "awaiting_name"  # -> "awaiting_contact" -> "done"
    summary_seen = False
    competencies_injected = False

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            if header_stage != "awaiting_contact":
                story.append(Spacer(1, 4))
            i += 1
            continue

        if header_stage == "awaiting_name" and stripped.startswith("# "):
            story.append(Paragraph(_inline_markdown_to_reportlab(stripped[2:].strip()), _NAME_STYLE))
            header_stage = "awaiting_contact"
            i += 1
            continue

        if header_stage == "awaiting_contact":
            contact_text = _linkify_emails(_inline_markdown_to_reportlab(stripped))
            story.append(Paragraph(contact_text, _CONTACT_STYLE))
            links_line = _build_links_line(linkedin_url, portfolio_url, github_url)
            if links_line:
                story.append(Paragraph(links_line, _LINKS_STYLE))
            else:
                story.append(Spacer(1, 10))
            header_stage = "done"
            i += 1
            continue

        if stripped.startswith("## "):
            header_text = stripped[3:].strip()
            if summary_seen and not competencies_injected and header_text.lower() != "summary":
                story.extend(_build_competencies_flowables(core_competencies or [], content_width_inches))
                competencies_injected = True
            if header_text.lower() == "summary":
                summary_seen = True
                if candidate_tagline:
                    story.append(Paragraph(_inline_markdown_to_reportlab(candidate_tagline), _TAGLINE_STYLE))
            story.append(Paragraph(header_text.upper(), _SECTION_STYLE))
            i += 1
        elif stripped.startswith("### "):
            role_text = stripped[4:].strip()
            # Look ahead: if the next non-blank line is a *date* line, render
            # both on one row with the date pushed to the far right, the
            # standard resume layout, instead of two stacked left-aligned lines.
            next_idx = i + 1
            while next_idx < len(lines) and not lines[next_idx].strip():
                next_idx += 1
            if next_idx < len(lines) and _is_date_line(lines[next_idx]):
                date_text = lines[next_idx].strip()
                story.append(_build_role_date_row(role_text, date_text, content_width_inches))
                i = next_idx + 1
            else:
                story.append(Paragraph(_inline_markdown_to_reportlab(role_text), _SUBSECTION_STYLE))
                i += 1
        elif _is_date_line(stripped):
            # A date line with no preceding ### role (shouldn't normally
            # happen given the lookahead above, but handle it gracefully).
            story.append(Paragraph(_inline_markdown_to_reportlab(stripped), _DATE_STYLE))
            i += 1
        elif stripped.startswith(_BULLET_PREFIXES):
            bullet_text = _inline_markdown_to_reportlab(_strip_bullet_prefix(stripped))
            story.append(Paragraph(bullet_text, _BULLET_STYLE, bulletText="\u2022"))
            i += 1
        else:
            story.append(Paragraph(_inline_markdown_to_reportlab(stripped), _BODY_STYLE))
            i += 1

    # Fallback: Summary existed but was the last section in the document, so
    # the "next header" trigger never fired — append competencies at the end
    # instead of silently dropping them.
    if summary_seen and not competencies_injected and core_competencies:
        story.extend(_build_competencies_flowables(core_competencies, content_width_inches))

    doc.build(story)
    return output_path


def render_cover_letter_pdf(
    cover_letter_text: str,
    output_path: str,
    location: str = "",
    candidate_name: str = "",
    linkedin_url: str = "",
    portfolio_url: str = "",
    github_url: str = "",
) -> str:
    """Renders the cover letter with a letterhead (name, hyperlinked links,
    centered) above a dated body and a proper sign-off block, rather than
    bare paragraphs — matches the resume's header treatment so both
    documents look like a matched set. Deliberately no tagline here — that's
    a resume-only element."""
    doc = SimpleDocTemplate(
        output_path,
        pagesize=_detect_page_size(location),
        topMargin=0.8 * inch,
        bottomMargin=1 * inch,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
    )
    story = []

    if candidate_name:
        story.append(Paragraph(_inline_markdown_to_reportlab(candidate_name), _NAME_STYLE))
    links_line = _build_links_line(linkedin_url, portfolio_url, github_url)
    if links_line:
        story.append(Paragraph(links_line, _LINKS_STYLE))
    if candidate_name or links_line:
        story.append(Spacer(1, 10))

    story.append(Paragraph(datetime.now().strftime("%B %d, %Y"), _LETTER_DATE_STYLE))

    paragraphs = [p.strip() for p in cover_letter_text.split("\n\n") if p.strip()]

    # If the model included its own closing line(s) despite being told not to
    # (the sign-off is handled entirely in code below), drop them here rather
    # than showing a valediction and the name twice. Loops (capped) since a
    # closing can be one combined paragraph ("Sincerely, <name>") or two
    # separate short ones ("Sincerely," then "<name>").
    strip_attempts = 0
    while paragraphs and strip_attempts < 3 and _looks_like_signoff(paragraphs[-1], candidate_name):
        paragraphs = paragraphs[:-1]
        strip_attempts += 1

    for p in paragraphs:
        story.append(Paragraph(_inline_markdown_to_reportlab(p.replace("\n", " ")), _LETTER_BODY_STYLE))

    if candidate_name:
        story.append(Spacer(1, 14))
        story.append(Paragraph("Best regards,", _SIGNOFF_STYLE))
        story.append(Paragraph(_inline_markdown_to_reportlab(candidate_name), _SIGNOFF_NAME_STYLE))

    doc.build(story)
    return output_path
