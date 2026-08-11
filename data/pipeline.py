"""
pipeline.py
Manually-maintained application tracker — deliberately separate from
tracker.py (which logs every Deep Dive automatically, whether or not you
ever applied) and dedup.py (every quick-scan, ever). This only holds jobs
the user explicitly chose to track, same "different lifecycle event, don't
conflate them" precedent as fill_log.py already established for the
auto-fill flow.

Status is manually set and changed by the user (Search & Score/Deep Dive
can only "start" tracking a job with a default status) - this module has
no opinion about what a "Saved" job should become next.
"""

import csv
import os
from datetime import datetime

PIPELINE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "applications.csv")

FIELDS = [
    "url",
    "company",
    "role_title",
    "snapshot_score",
    "status",
    "date_added",
    "status_updated_at",
    "date_applied",
    "notes",
]

# Ordered so the Tracking tab's funnel chart reads left-to-right as an actual
# progression, not just alphabetical. Rejected/Withdrawn are terminal states
# off the main line, not "further along" than Offer.
STATUSES = ["Saved", "Applied", "Interviewing", "Offer", "Rejected", "Withdrawn"]
DEFAULT_STATUS = "Saved"


def ensure_pipeline():
    if not os.path.exists(PIPELINE_PATH):
        with open(PIPELINE_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
        return

    # Same schema-drift safety net as tracker.py/dedup.py/fill_log.py: never
    # append new-schema rows to an old-schema file.
    with open(PIPELINE_PATH, newline="") as f:
        reader = csv.DictReader(f)
        existing_header = reader.fieldnames or []
        existing_rows = list(reader)

    if existing_header == FIELDS:
        return

    # Purely additive drift (every old column still exists in the new
    # schema, e.g. adding date_applied) gets backfilled in place instead of
    # archived — real tracked applications live in this file and a blind
    # archive would silently reset the user's whole pipeline back to empty.
    # Checked as a set, not a prefix: a new field can land in the middle of
    # FIELDS (as date_applied did, ahead of notes) without that counting as
    # a breaking change — save_all always writes by field name, not position.
    if set(existing_header) <= set(FIELDS):
        for row in existing_rows:
            for field in FIELDS:
                row.setdefault(field, "")
            # Best-effort backfill: status_updated_at is the closest proxy
            # for "when this job reached its current status" on rows that
            # predate date_applied.
            if not row.get("date_applied") and row.get("status") in ("Applied", "Interviewing", "Offer", "Rejected", "Withdrawn"):
                row["date_applied"] = row.get("status_updated_at") or ""
        save_all(existing_rows)
        return

    archive_path = PIPELINE_PATH.replace(".csv", "_old.csv")
    os.replace(PIPELINE_PATH, archive_path)
    with open(PIPELINE_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()


def load_all() -> list:
    ensure_pipeline()
    with open(PIPELINE_PATH, newline="") as f:
        return list(csv.DictReader(f))


def save_all(rows: list) -> None:
    """Overwrites the whole file — used by the Tracking tab's editable
    table, same pattern as company_registry.save_registry: the user edits
    a full st.data_editor grid (status dropdown included) and saves it back
    in one shot, rather than this module tracking per-cell diffs."""
    with open(PIPELINE_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})


def add_or_update(url: str, company: str, role_title: str, snapshot_score: str, status: str = DEFAULT_STATUS) -> None:
    """Adds a new tracked job, or refreshes an already-tracked one's
    snapshot (company/role/score can drift if a listing gets re-scored)
    WITHOUT resetting its status or date_added - re-clicking "Track this
    job" a second time should never silently wipe out real progress
    (e.g. an "Interviewing" status) back to the default."""
    rows = load_all()
    now = datetime.now().isoformat(timespec="seconds")
    for row in rows:
        if row.get("url") == url:
            row["company"] = company
            row["role_title"] = role_title
            row["snapshot_score"] = snapshot_score
            save_all(rows)
            return
    rows.append(
        {
            "url": url,
            "company": company,
            "role_title": role_title,
            "snapshot_score": snapshot_score,
            "status": status,
            "date_added": now,
            "status_updated_at": now,
            "date_applied": now if status == "Applied" else "",
            "notes": "",
        }
    )
    save_all(rows)


def is_tracked(url: str, rows: list = None) -> bool:
    rows = rows if rows is not None else load_all()
    return any(row.get("url") == url for row in rows)
