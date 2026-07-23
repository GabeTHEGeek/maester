"""
tracker.py
Lightweight CSV-backed store for past panel evaluations, so the app can show
a running dashboard of every job you've scored.
"""

import csv
import os
from datetime import datetime

TRACKER_PATH = os.path.join(os.path.dirname(__file__), "tracker.csv")

FIELDS = [
    "timestamp",
    "company",
    "role_title",
    "fit_score",
    "tier",
    "recommendation",
    "top_gaps",
    "url",
    "source",
    "location",
    "salary",
    "legitimacy_tier",
    "comp_reliability",
]


def ensure_tracker():
    if not os.path.exists(TRACKER_PATH):
        with open(TRACKER_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
        return

    # If an existing tracker.csv predates a schema change (e.g. we added a
    # column), its header won't match FIELDS. Appending new-schema rows to
    # that file would silently shift values into the wrong columns. Instead,
    # archive the old file and start fresh — losing old rows is better than
    # corrupting them.
    with open(TRACKER_PATH, newline="") as f:
        reader = csv.reader(f)
        existing_header = next(reader, [])

    if existing_header != FIELDS:
        archive_path = TRACKER_PATH.replace(".csv", "_old.csv")
        os.replace(TRACKER_PATH, archive_path)
        with open(TRACKER_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()


def log_result(result) -> None:
    ensure_tracker()
    with open(TRACKER_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writerow(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "company": result.company,
                "role_title": result.role_title,
                "fit_score": result.fit_score,
                "tier": result.tier,
                "recommendation": result.recommendation,
                "top_gaps": " | ".join(result.top_gaps),
                "url": result.job_url,
                "source": f"greenhouse:{result.board}" if result.source == "greenhouse" else result.source,
                "location": result.location,
                "salary": result.salary,
                "legitimacy_tier": result.legitimacy_tier,
                "comp_reliability": result.comp_reliability,
            }
        )


def load_all():
    ensure_tracker()
    with open(TRACKER_PATH, newline="") as f:
        rows = list(csv.DictReader(f))

    # Normalize every row against the current schema: fill missing columns
    # (from an older schema version) with "", and never let a bad fit_score
    # value propagate as something that breaks sorting or JSON rendering.
    normalized = []
    for row in rows:
        clean = {field: (row.get(field) or "") for field in FIELDS}
        if not clean["fit_score"].strip().lstrip("-").isdigit():
            clean["fit_score"] = "0"
        normalized.append(clean)
    return normalized
