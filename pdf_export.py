"""
pdf_export.py
Converts the tailored resume/cover letter Markdown into simple, single-column
PDFs designed to parse cleanly through ATS systems — no tables, no multi-column
layouts, no images, standard fonts only. Fancy HTML-to-PDF resume templates
often look great to a human and parse terribly to an ATS; this deliberately
avoids that trap.
"""

import re

from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

_STYLES = getSampleStyleSheet()

_NAME_STYLE = ParagraphStyle(
    "NameStyle", parent=_STYLES["Title"], fontSize=18, spaceAfter=2, alignment=1
)
_CONTACT_STYLE = ParagraphStyle(
    "ContactStyle", parent=_STYLES["Normal"], fontSize=9, alignment=1, spaceAfter=12,
    textColor="#444444",
)
_SECTION_STYLE = ParagraphStyle(
    "SectionStyle", parent=_STYLES["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4,
    textColor="#1a1a1a", borderWidth=0,
)
_SUBSECTION_STYLE = ParagraphStyle(
    "SubsectionStyle", parent=_STYLES["Normal"], fontSize=10.5, spaceBefore=6, spaceAfter=1,
    fontName="Helvetica-Bold",
)
_DATE_STYLE = ParagraphStyle(
    "DateStyle", parent=_STYLES["Normal"], fontSize=9, textColor="#555555", spaceAfter=4,
    fontName="Helvetica-Oblique",
)
_BULLET_STYLE = ParagraphStyle(
    "BulletStyle", parent=_STYLES["Normal"], fontSize=9.5, leftIndent=14, spaceAfter=3,
    leading=13,
)
_BODY_STYLE = ParagraphStyle(
    "BodyStyle", parent=_STYLES["Normal"], fontSize=9.5, spaceAfter=4, leading=13,
)
_LETTER_BODY_STYLE = ParagraphStyle(
    "LetterBodyStyle", parent=_STYLES["Normal"], fontSize=10.5, spaceAfter=12, leading=15,
)


def _inline_markdown_to_reportlab(text: str) -> str:
    """Convert **bold** and *italic* to reportlab's mini-markup, and escape
    any stray ampersands/angle brackets so Paragraph doesn't choke on them."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", text)
    return text


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


def render_resume_pdf(markdown_text: str, output_path: str, location: str = "") -> str:
    """Parses the resume Markdown line-by-line into flowables and writes a PDF."""
    doc = SimpleDocTemplate(
        output_path,
        pagesize=_detect_page_size(location),
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    story = []
    lines = markdown_text.splitlines()
    seen_name = False

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            story.append(Spacer(1, 4))
            continue

        if line.startswith("# "):
            story.append(Paragraph(_inline_markdown_to_reportlab(line[2:].strip()), _NAME_STYLE))
            seen_name = True
        elif line.startswith("## "):
            story.append(Paragraph(line[3:].strip().upper(), _SECTION_STYLE))
        elif line.startswith("### "):
            story.append(Paragraph(_inline_markdown_to_reportlab(line[4:].strip()), _SUBSECTION_STYLE))
        elif line.startswith("- "):
            bullet_text = _inline_markdown_to_reportlab(line[2:].strip())
            story.append(Paragraph(f"&bull;&nbsp;&nbsp;{bullet_text}", _BULLET_STYLE))
        elif line.strip().startswith("*") and line.strip().endswith("*") and not line.strip().startswith("**"):
            story.append(Paragraph(_inline_markdown_to_reportlab(line.strip()), _DATE_STYLE))
        elif not seen_name and "|" in line:
            # Contact line right after the name header, e.g. "City | phone | email"
            story.append(Paragraph(_inline_markdown_to_reportlab(line.strip()), _CONTACT_STYLE))
        else:
            story.append(Paragraph(_inline_markdown_to_reportlab(line.strip()), _BODY_STYLE))

    doc.build(story)
    return output_path


def render_cover_letter_pdf(cover_letter_text: str, output_path: str, location: str = "") -> str:
    """Renders the cover letter as simple paragraph flow — one Paragraph per
    blank-line-separated block, no headers/bullets needed."""
    doc = SimpleDocTemplate(
        output_path,
        pagesize=_detect_page_size(location),
        topMargin=1 * inch,
        bottomMargin=1 * inch,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
    )
    story = []
    paragraphs = [p.strip() for p in cover_letter_text.split("\n\n") if p.strip()]
    for p in paragraphs:
        story.append(Paragraph(_inline_markdown_to_reportlab(p.replace("\n", " ")), _LETTER_BODY_STYLE))
    doc.build(story)
    return output_path
