"""
company_registry.py
A user-editable log of companies to check on Greenhouse/Ashby, with their
board token, which platform they're actually on, and whether that's been
verified or is still a guess. Auto-updates as searches discover (or fail to
find) a company on a given platform, so wrong guesses self-correct over time
instead of silently staying wrong. (This exists because a "verified" guess
about Mercury turned out to be on the wrong platform — better to track
confidence explicitly than pretend every entry is equally reliable.)
"""

import csv
import os
from datetime import datetime

REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "companies.csv")

FIELDS = ["company", "token", "platform", "status", "last_checked", "notes"]

# Seed data. "verified" rows were confirmed via an actual job URL fetched
# during use. Everything else is "unverified" — my best guess, which could
# be wrong — or "unknown," where I have no real basis for a guess at all.
# Auto-discovery corrects these as you search.
_SEED_ROWS = [
    {"company": "Anthropic", "token": "anthropic", "platform": "greenhouse", "status": "verified", "notes": "Confirmed via job URL"},
    {"company": "Airtable", "token": "airtable", "platform": "greenhouse", "status": "verified", "notes": "Confirmed via job URL"},
    {"company": "Mercury", "token": "mercury", "platform": "greenhouse", "status": "verified", "notes": "Confirmed via job URL"},
    {"company": "OpenAI", "token": "openai", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Databricks", "token": "databricks", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Notion", "token": "notion", "platform": "unknown", "status": "unverified", "notes": "Could be Greenhouse or Ashby, unconfirmed"},
    {"company": "Ramp", "token": "ramp", "platform": "unknown", "status": "unverified", "notes": "Could be Greenhouse or Ashby, unconfirmed"},
    {"company": "Scale AI", "token": "scaleai", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Perplexity", "token": "perplexityai", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Webflow", "token": "webflow", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Vercel", "token": "vercel", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Linear", "token": "linear", "platform": "ashby", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Retool", "token": "retool", "platform": "ashby", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Replit", "token": "replit", "platform": "ashby", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Watershed", "token": "watershed", "platform": "ashby", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Runway", "token": "runway", "platform": "ashby", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Figma", "token": "figma", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Cursor", "token": "anysphere", "platform": "unknown", "status": "unverified", "notes": "Company is Anysphere — token may be wrong, verify at their careers page"},
    {"company": "Brex", "token": "brex", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Reddit", "token": "reddit", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Shopify", "token": "shopify", "platform": "unknown", "status": "unverified", "notes": "May use a custom careers site, not Greenhouse/Ashby"},
    {"company": "Plaid", "token": "plaid", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "Supabase", "token": "supabase", "platform": "ashby", "status": "unverified", "notes": "Guess, unconfirmed"},
    {"company": "PostHog", "token": "posthog", "platform": "unknown", "status": "unverified", "notes": "May use a custom careers page"},
    {"company": "Cohere", "token": "cohere", "platform": "unknown", "status": "unverified", "notes": "Guess, unconfirmed"},
]


def ensure_registry():
    if not os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            for row in _SEED_ROWS:
                writer.writerow({k: row.get(k, "") for k in FIELDS})
        return

    with open(REGISTRY_PATH, newline="") as f:
        reader = csv.reader(f)
        existing_header = next(reader, [])
    if existing_header != FIELDS:
        archive_path = REGISTRY_PATH.replace(".csv", "_old.csv")
        os.replace(REGISTRY_PATH, archive_path)
        ensure_registry()


def load_registry() -> list:
    ensure_registry()
    with open(REGISTRY_PATH, newline="") as f:
        return list(csv.DictReader(f))


def save_registry(rows: list) -> None:
    with open(REGISTRY_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})


def tokens_for_platform(rows: list, platform: str) -> list:
    """Tokens explicitly on this platform, plus 'unknown'/blank ones — those
    get tried on every platform until a search discovers where they live."""
    return [
        r["token"] for r in rows
        if r.get("token") and (r.get("platform") == platform or r.get("platform") in ("", "unknown"))
    ]


def record_discovery(rows: list, token: str, platform: str, found: bool) -> list:
    """Updates a company's row after a search attempt: marks it verified on
    the platform that worked, or notes a failure if it wasn't found there
    this pass (without overwriting a platform already verified elsewhere)."""
    now = datetime.now().isoformat(timespec="seconds")
    matched = False
    for r in rows:
        if r.get("token") == token:
            matched = True
            if found:
                r["platform"] = platform
                r["status"] = "verified"
                r["notes"] = "Auto-discovered"
            elif r.get("status") != "verified":
                prior = r.get("notes", "") or ""
                fail_note = f"Not found on {platform}"
                if fail_note not in prior:
                    r["notes"] = (prior + "; " + fail_note).strip("; ")
                r["status"] = r.get("status") or "unverified"
            r["last_checked"] = now
    if not matched and found:
        rows.append({
            "company": token,
            "token": token,
            "platform": platform,
            "status": "verified",
            "last_checked": now,
            "notes": "Auto-discovered",
        })
    return rows


def add_company(rows: list, company: str, token: str = "", platform: str = "unknown") -> list:
    token = (token or "").strip().lower() or company.strip().lower().replace(" ", "")
    if any(r.get("token") == token for r in rows):
        return rows
    rows.append({
        "company": company,
        "token": token,
        "platform": platform,
        "status": "unverified",
        "last_checked": "",
        "notes": "Added manually",
    })
    return rows
