"""
email_notify.py
Sends a summary email after a Deep Dive run, using the user's own SMTP
credentials (e.g. a Gmail App Password). Nothing is ever sent unless the
user explicitly enables auto-send or clicks "send now" — this module never
sends on its own initiative.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_summary_email(
    smtp_email: str,
    smtp_password: str,
    recipient: str,
    subject: str,
    body: str,
    smtp_server: str = "smtp.gmail.com",
    smtp_port: int = 587,
) -> None:
    """Sends a plain-text email via SMTP with STARTTLS. Raises on failure so
    the caller can surface a clear error instead of silently failing."""
    msg = MIMEMultipart()
    msg["From"] = smtp_email
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
        server.starttls()
        server.login(smtp_email, smtp_password)
        server.sendmail(smtp_email, recipient, msg.as_string())


def build_deep_dive_summary(result) -> str:
    """Builds a plain-text email body summarizing a Deep Dive PanelResult."""
    lines = [
        f"{result.role_title} at {result.company}",
        f"Fit score: {result.fit_score}/100 ({result.tier})",
        f"Recommendation: {result.recommendation}",
        "",
        f"Why: {result.tier_reason}",
        "",
        "Top gaps:",
    ]
    lines += [f"- {gap}" for gap in result.top_gaps] or ["- none noted"]
    lines += ["", "Resume fixes:"]
    lines += [f"- {fix}" for fix in result.resume_fixes] or ["- none noted"]
    lines += [
        "",
        f"Posting legitimacy: {result.legitimacy_tier or 'Unknown'}",
    ]
    if result.legitimacy_notes:
        lines.append(result.legitimacy_notes)
    lines.append(f"Comp reliability: {result.comp_reliability or 'Unknown'}")
    if result.comp_notes:
        lines.append(result.comp_notes)
    if result.location or result.salary:
        lines.append("")
        if result.location:
            lines.append(f"Location: {result.location}")
        if result.salary:
            lines.append(f"Salary: {result.salary}")
    if result.job_url:
        lines += ["", f"Listing: {result.job_url}"]
    return "\n".join(lines)
