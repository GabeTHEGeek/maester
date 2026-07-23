"""
dedup.py
Tracks every listing that's already been quick-scored, across searches. A
listing that shows up again under a different query (or via a different
source) gets its cached score reused instead of burning another API call.

This is deliberately separate from tracker.py (which only logs Deep Dive
results): scan history covers every listing that ever entered a quick scan,
regardless of whether you dove deeper on it.
"""

import csv
import os
from datetime import datetime

SCAN_HISTORY_PATH = os.path.join(os.path.dirname(__file__), "scan_history.csv")

FIELDS = [
    "url",
    "title",
    "company",
    "score",
    "grade",
    "reason",
    "source",
    "board",
    "location",
    "salary",
    "legitimacy_tier",
    "legitimacy_note",
    "comp_reliability",
    "last_scanned",
]


def ensure_scan_history():
    if not os.path.exists(SCAN_HISTORY_PATH):
        with open(SCAN_HISTORY_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
        return

    with open(SCAN_HISTORY_PATH, newline="") as f:
        reader = csv.reader(f)
        existing_header = next(reader, [])

    if existing_header != FIELDS:
        archive_path = SCAN_HISTORY_PATH.replace(".csv", "_old.csv")
        os.replace(SCAN_HISTORY_PATH, archive_path)
        with open(SCAN_HISTORY_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()


def load_seen_urls() -> dict:
    """Returns {url: {row dict}} for every previously scanned listing."""
    ensure_scan_history()
    with open(SCAN_HISTORY_PATH, newline="") as f:
        rows = list(csv.DictReader(f))
    return {row["url"]: row for row in rows if row.get("url")}


def record_scans(quick_scores: list) -> None:
    """Appends every newly scanned QuickScore to the history in one write."""
    ensure_scan_history()
    with open(SCAN_HISTORY_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        now = datetime.now().isoformat(timespec="seconds")
        for r in quick_scores:
            writer.writerow(
                {
                    "url": r.url,
                    "title": r.title,
                    "company": r.company,
                    "score": r.score,
                    "grade": r.grade,
                    "reason": r.reason,
                    "source": r.source,
                    "board": r.board,
                    "location": r.location,
                    "salary": r.salary,
                    "legitimacy_tier": r.legitimacy_tier,
                    "legitimacy_note": r.legitimacy_note,
                    "comp_reliability": r.comp_reliability,
                    "last_scanned": now,
                }
            )
