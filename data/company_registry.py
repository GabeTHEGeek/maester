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

REGISTRY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "companies.csv")

FIELDS = ["company", "token", "platform", "status", "last_checked", "notes"]

# Seed data. "verified" rows were confirmed via an actual job URL fetched
# during use. Everything else is "unverified" — my best guess, which could
# be wrong — or "unknown," where I have no real basis for a guess at all.
# Auto-discovery corrects these as you search.
_SEED_ROWS = [
    {"company": "Anthropic", "token": "anthropic", "platform": "greenhouse", "status": "verified", "notes": "Confirmed via job URL. Also confirmed present in a real, current Greenhouse company directory (8,333 companies), reinforcing this guess."},
    {"company": "Airtable", "token": "airtable", "platform": "greenhouse", "status": "verified", "notes": "Confirmed via job URL. Also confirmed present in a real, current Greenhouse company directory (8,333 companies), reinforcing this guess."},
    {"company": "Mercury", "token": "mercury", "platform": "greenhouse", "status": "verified", "notes": "Confirmed via job URL. Also confirmed present in a real, current Greenhouse company directory (8,333 companies), reinforcing this guess."},
    {"company": "OpenAI", "token": "openai", "platform": "ashby", "status": "unverified", "notes": "Confirmed present in a real, current Ashby company directory (3,161 companies, github.com/Feashliaa/job-board-aggregator) — high confidence, pending verification by an actual Maester search"},
    {"company": "Databricks", "token": "databricks", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed (confirmed NOT on Ashby via a 3,161-company Ashby directory check). Also confirmed present in a real, current Greenhouse company directory (8,333 companies), reinforcing this guess."},
    {"company": "Notion", "token": "notion", "platform": "ashby", "status": "unverified", "notes": "Confirmed present in a real, current Ashby company directory (3,161 companies, github.com/Feashliaa/job-board-aggregator) — high confidence, pending verification by an actual Maester search"},
    {"company": "Ramp", "token": "ramp", "platform": "ashby", "status": "unverified", "notes": "Confirmed present in a real, current Ashby company directory (3,161 companies, github.com/Feashliaa/job-board-aggregator) — high confidence, pending verification by an actual Maester search"},
    {"company": "Scale AI", "token": "scaleai", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed (confirmed NOT on Ashby via a 3,161-company Ashby directory check). Also confirmed present in a real, current Greenhouse company directory (8,333 companies), reinforcing this guess."},
    {"company": "Perplexity", "token": "perplexity", "platform": "ashby", "status": "verified", "notes": "Confirmed by user"},
    {"company": "Webflow", "token": "webflow", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed (confirmed NOT on Ashby via a 3,161-company Ashby directory check). Also confirmed present in a real, current Greenhouse company directory (8,333 companies), reinforcing this guess."},
    {"company": "Vercel", "token": "vercel", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed (confirmed NOT on Ashby via a 3,161-company Ashby directory check). Also confirmed present in a real, current Greenhouse company directory (8,333 companies), reinforcing this guess."},
    {"company": "Linear", "token": "linear", "platform": "ashby", "status": "unverified", "notes": "Confirmed present in a real, current Ashby company directory (3,161 companies, github.com/Feashliaa/job-board-aggregator) — high confidence, pending verification by an actual Maester search"},
    {"company": "Retool", "token": "retool", "platform": "gem", "status": "verified", "notes": "Confirmed by user, and confirmed live: jobs.gem.com/retool is a real, public Retool Careers page."},
    {"company": "Replit", "token": "replit", "platform": "ashby", "status": "unverified", "notes": "Confirmed present in a real, current Ashby company directory (3,161 companies, github.com/Feashliaa/job-board-aggregator) — high confidence, pending verification by an actual Maester search"},
    {"company": "Watershed", "token": "watershed", "platform": "ashby", "status": "unverified", "notes": "Confirmed present in a real, current Ashby company directory (3,161 companies, github.com/Feashliaa/job-board-aggregator) — high confidence, pending verification by an actual Maester search"},
    {"company": "Runway", "token": "runway", "platform": "ashby", "status": "unverified", "notes": "Confirmed present in a real, current Ashby company directory (3,161 companies, github.com/Feashliaa/job-board-aggregator) — high confidence, pending verification by an actual Maester search"},
    {"company": "Figma", "token": "figma", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed (confirmed NOT on Ashby via a 3,161-company Ashby directory check). Also confirmed present in a real, current Greenhouse company directory (8,333 companies), reinforcing this guess."},
    {"company": "Cursor", "token": "cursor", "platform": "ashby", "status": "unverified", "notes": "Confirmed present in a real, current Ashby company directory (3,161 companies, github.com/Feashliaa/job-board-aggregator) — high confidence, pending verification by an actual Maester search"},
    {"company": "Brex", "token": "brex", "platform": "greenhouse", "status": "unverified", "notes": "Guess, unconfirmed (confirmed NOT on Ashby via a 3,161-company Ashby directory check). Also confirmed present in a real, current Greenhouse company directory (8,333 companies), reinforcing this guess."},
    {"company": "Reddit", "token": "reddit", "platform": "greenhouse", "status": "verified", "notes": "Confirmed by user"},
    {"company": "Shopify", "token": "shopify", "platform": "lever", "status": "unverified", "notes": "Ruled out on both Ashby and Greenhouse directories, then found in a real Lever company directory — resolves the earlier unknown, pending verification by an actual Maester search"},
    {"company": "Plaid", "token": "plaid", "platform": "ashby", "status": "unverified", "notes": "Confirmed present in a real, current Ashby company directory (3,161 companies, github.com/Feashliaa/job-board-aggregator) — high confidence, pending verification by an actual Maester search"},
    {"company": "Supabase", "token": "supabase", "platform": "ashby", "status": "unverified", "notes": "Confirmed present in a real, current Ashby company directory (3,161 companies, github.com/Feashliaa/job-board-aggregator) — high confidence, pending verification by an actual Maester search"},
    {"company": "PostHog", "token": "posthog", "platform": "ashby", "status": "unverified", "notes": "Confirmed present in a real, current Ashby company directory (3,161 companies, github.com/Feashliaa/job-board-aggregator) — high confidence, pending verification by an actual Maester search"},
    {"company": "Cohere", "token": "cohere", "platform": "ashby", "status": "unverified", "notes": "Confirmed present in a real, current Ashby company directory (3,161 companies, github.com/Feashliaa/job-board-aggregator) — high confidence, pending verification by an actual Maester search"},
    {"company": "Twitch", "token": "twitch", "platform": "lever", "status": "unverified", "notes": "Confirmed present in a real, current Lever company directory (4,368 companies) — pending verification by an actual Maester search"},
    {"company": "Weights & Biases", "token": "wandb", "platform": "lever", "status": "unverified", "notes": "Confirmed present in a real, current Lever company directory (4,368 companies) — pending verification by an actual Maester search"},
    {"company": "Anyscale", "token": "anyscale", "platform": "lever", "status": "unverified", "notes": "Confirmed present in a real, current Lever company directory (4,368 companies) — pending verification by an actual Maester search"},
    {"company": "Abridge", "token": "abridge", "platform": "lever", "status": "unverified", "notes": "Confirmed present in a real, current Lever company directory (4,368 companies) — pending verification by an actual Maester search"},
    {"company": "Toptal", "token": "toptal", "platform": "lever", "status": "unverified", "notes": "Confirmed present in a real, current Lever company directory (4,368 companies) — pending verification by an actual Maester search"},
    {"company": "Upwork", "token": "upwork", "platform": "lever", "status": "unverified", "notes": "Confirmed present in a real, current Lever company directory (4,368 companies) — pending verification by an actual Maester search"},
    {"company": "Atlassian", "token": "atlassian", "platform": "lever", "status": "unverified", "notes": "Confirmed present in a real, current Lever company directory (4,368 companies) — pending verification by an actual Maester search"},
    {"company": "Wiz", "token": "wiz", "platform": "lever", "status": "unverified", "notes": "Confirmed present in a real, current Lever company directory (4,368 companies) — pending verification by an actual Maester search"},
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


def mark_failed_all(rows: list, token: str, platforms_tried: list) -> list:
    """A token that was tried on every supported platform this search and
    found on none of them — explicitly marked 'failed' rather than left as
    an accumulating pile of 'not found on X' notes, so it's visibly distinct
    from a company that just hasn't been checked yet. Doesn't overwrite a
    platform already verified elsewhere (shouldn't happen in practice, since
    verified tokens are skipped before reaching this fallback, but matches
    the same safety rule record_discovery follows)."""
    now = datetime.now().isoformat(timespec="seconds")
    for r in rows:
        if r.get("token") == token and r.get("status") != "verified":
            r["status"] = "failed"
            r["notes"] = f"Not found on any of: {', '.join(sorted(platforms_tried))}"
            r["last_checked"] = now
    return rows
