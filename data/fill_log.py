"""
fill_log.py
Lightweight CSV-backed record of every auto-fill attempt (browser/autofill.py),
so a batch of prepared applications doesn't lose track of what's actually been
submitted versus just filled and left waiting for review. Deliberately
separate from tracker.py (Deep Dive results) and dedup.py (scan history) —
this logs a different lifecycle event, the fill itself, not the scoring.
"""

import csv
import os
from datetime import datetime

FILL_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fill_log.csv")

FIELDS = [
    "timestamp",
    "company",
    "role_title",
    "url",
    "fields_auto_mapped",
    "fields_flagged",
    "status",
]


def ensure_fill_log():
    if not os.path.exists(FILL_LOG_PATH):
        with open(FILL_LOG_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
        return

    # Same schema-drift safety net as tracker.py/dedup.py: never append
    # new-schema rows to an old-schema file, since that silently shifts
    # values into the wrong columns.
    with open(FILL_LOG_PATH, newline="") as f:
        reader = csv.reader(f)
        existing_header = next(reader, [])

    if existing_header != FIELDS:
        archive_path = FILL_LOG_PATH.replace(".csv", "_old.csv")
        os.replace(FILL_LOG_PATH, archive_path)
        with open(FILL_LOG_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()


def log_fill_attempt(
    company: str,
    role_title: str,
    url: str,
    fields_auto_mapped: list,
    fields_flagged: list,
    status: str = "filled_awaiting_review",
) -> None:
    """status is always the tool's own record of what IT did (filled and
    stopped), never whether the application was actually submitted — this
    tool has no way of knowing that, since it never clicks submit itself."""
    ensure_fill_log()
    with open(FILL_LOG_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writerow(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "company": company,
                "role_title": role_title,
                "url": url,
                "fields_auto_mapped": " | ".join(fields_auto_mapped),
                "fields_flagged": " | ".join(fields_flagged),
                "status": status,
            }
        )


def load_all() -> list:
    ensure_fill_log()
    with open(FILL_LOG_PATH, newline="") as f:
        return list(csv.DictReader(f))
