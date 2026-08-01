"""
import_company_lists.py
One-time (but repeatable) bulk import of large, real ATS company directories
into companies.csv. Point it at JSON files that are each just a flat array
of company slugs, e.g. ["cohere", "cursor", ...].

Usage:
    python3 import_company_lists.py --ashby ashby_companies.json \\
        --greenhouse greenhouse_companies.json --lever lever_companies.json \\
        --bamboohr bamboohr_companies.json

Existing registry rows are never overwritten — a company already in
companies.csv (especially anything already "verified") keeps its current
platform/status/notes untouched. New companies get added as "unverified,"
same standard as every other guess in this registry: a directory listing is
not the same as a real Maester search confirming a company actually works.

Companies appearing on more than one uploaded list get platform "unknown"
rather than a guess — that's deliberate. Cross-list overlap for well-known
companies has repeatedly turned out to be directory noise/staleness rather
than genuine dual-hosting (see company_registry.py's seed notes), so "unknown"
lets a real search resolve it instead of trusting either list blindly.
"""

import argparse
import json

from data.company_registry import load_registry, save_registry


def _title_case(token: str) -> str:
    """Best-effort display name from a lowercase slug — editable later via
    the in-app 'Manage companies' table if it guesses wrong."""
    return token.replace("-", " ").replace("_", " ").title()


def import_lists(ashby_path: str = None, greenhouse_path: str = None, lever_path: str = None, bamboohr_path: str = None) -> None:
    platform_sets = {}
    if ashby_path:
        with open(ashby_path) as f:
            platform_sets["ashby"] = set(json.load(f))
    if greenhouse_path:
        with open(greenhouse_path) as f:
            platform_sets["greenhouse"] = set(json.load(f))
    if lever_path:
        with open(lever_path) as f:
            platform_sets["lever"] = set(json.load(f))
    if bamboohr_path:
        with open(bamboohr_path) as f:
            platform_sets["bamboohr"] = set(json.load(f))

    if not platform_sets:
        print("No input files given — nothing to do.")
        return

    # Build token -> [platforms it appeared on]
    token_platforms = {}
    for platform, tokens in platform_sets.items():
        for token in tokens:
            token_platforms.setdefault(token, []).append(platform)

    rows = load_registry()
    existing_tokens = {r["token"] for r in rows}

    added = 0
    skipped_existing = 0
    added_unknown = 0

    for token, platforms in token_platforms.items():
        if token in existing_tokens:
            skipped_existing += 1
            continue

        if len(platforms) == 1:
            platform = platforms[0]
            notes = f"Bulk-imported from a real {platform} company directory — pending verification by an actual Maester search"
        else:
            platform = "unknown"
            notes = (
                f"Bulk-imported — appeared on {len(platforms)} different directories "
                f"({', '.join(sorted(platforms))}), marked unknown rather than guessed "
                f"since cross-list overlap has repeatedly turned out to be noise"
            )
            added_unknown += 1

        rows.append({
            "company": _title_case(token),
            "token": token,
            "platform": platform,
            "status": "unverified",
            "last_checked": "",
            "notes": notes,
        })
        added += 1

    save_registry(rows)

    print(f"Added {added} new companies ({added_unknown} marked 'unknown' due to multi-list overlap).")
    print(f"Skipped {skipped_existing} already in the registry (left untouched).")
    print(f"Registry now has {len(rows)} total companies.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ashby", help="Path to a JSON file: flat array of Ashby company slugs")
    parser.add_argument("--greenhouse", help="Path to a JSON file: flat array of Greenhouse company slugs")
    parser.add_argument("--lever", help="Path to a JSON file: flat array of Lever company slugs")
    parser.add_argument("--bamboohr", help="Path to a JSON file: flat array of BambooHR company subdomains")
    args = parser.parse_args()
    import_lists(ashby_path=args.ashby, greenhouse_path=args.greenhouse, lever_path=args.lever, bamboohr_path=args.bamboohr)
