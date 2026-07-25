"""
freshness.py
Rates how "fresh" a posting is, scaled by inferred seniority — a 60-day-old
Senior/Staff posting is normal (those searches run longer), the same age on
a Junior/Associate posting is a real staleness signal. Informational only,
never folded into the fit score, same design choice as Posting Legitimacy
and Compensation Reliability.

Base breakpoints (days since posted), Mid-tier: 1, 7, 14, 30, 60.
The first two (1, 7) are fixed for every seniority tier — being an early
applicant matters the same amount regardless of level. Only the back half
(14/30/60) scales by a per-tier multiplier.
"""

from datetime import datetime, timezone

from extract import _parse_published

_SENIORITY_KEYWORDS = {
    "executive": ["principal", "director", "vp", "vice president", "head of", "chief", "group product manager"],
    "senior": ["senior", "sr.", "sr ", "staff", "lead"],
    "junior": ["junior", "associate", "entry", "intern", "coordinator"],
}

_TIER_MULTIPLIER = {
    "junior": 0.7,
    "mid": 1.0,
    "senior": 1.5,
    "executive": 2.0,
}


def infer_seniority_tier(title: str) -> str:
    """Best-effort seniority tier from title keywords. Defaults to 'mid' when
    there's no clear signal either way, rather than guessing — same honesty
    principle as everything else in Maester. Checked in executive -> senior
    -> junior order so 'Senior Director' correctly lands as executive, not
    senior, since director/VP-level titles imply broader scope."""
    if not title:
        return "mid"
    t = title.lower()
    for keyword in _SENIORITY_KEYWORDS["executive"]:
        if keyword in t:
            return "executive"
    for keyword in _SENIORITY_KEYWORDS["senior"]:
        if keyword in t:
            return "senior"
    for keyword in _SENIORITY_KEYWORDS["junior"]:
        if keyword in t:
            return "junior"
    return "mid"


def compute_freshness(raw_published: str, title: str) -> dict:
    """Returns {"emoji": str, "label": str, "tier": str, "days": int|None,
    "detail": str}. Empty emoji/label/detail if the date can't be parsed —
    never guesses a freshness rating without a real date."""
    parsed = _parse_published(raw_published)
    if parsed is None:
        return {"emoji": "", "label": "", "tier": "", "days": None, "detail": ""}

    days = (datetime.now(timezone.utc) - parsed).days
    if days < 0:
        days = 0

    tier = infer_seniority_tier(title)
    mult = _TIER_MULTIPLIER[tier]

    b14 = round(14 * mult)
    b30 = round(30 * mult)
    b60 = round(60 * mult)

    if days <= 1:
        emoji, label = "🔥🔥", "Hot"
    elif days <= 7:
        emoji, label = "🔥", "Good"
    elif days <= b14:
        emoji, label = "🔵", "Normal"
    elif days <= b30:
        emoji, label = "🕒", "Aging"
    elif days <= b60:
        emoji, label = "🟡", "Possibly Stale"
    else:
        emoji, label = "🥶", "Stale"

    tier_label = tier.capitalize() if tier != "mid" else "Mid"
    detail = f"{emoji} {label} — {tier_label}-level"

    return {"emoji": emoji, "label": label, "tier": tier, "days": days, "detail": detail}
