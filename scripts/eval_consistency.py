"""
eval_consistency.py
Repeat-run consistency check for engines/rubric.py: pulls N already-scored
listings from scan_history.csv, re-fetches each one's real current listing
text, re-scores it 3x in a row against the real resume, and reports score
spread, letter-grade flips, and drift from the originally cached score.

This exists because real testing surfaced it as needed, not speculatively:
the same listing scoring 72/64/72 across identical runs (see CLAUDE.md) was
found by hand once. This script is that same check, made repeatable, so it
doesn't have to be rediscovered by hand again after the next rubric prompt
edit. It is deliberately scoped to just this — repeat-run spread against one
provider — not the fuller golden-dataset/cross-provider-agreement harness
CLAUDE.md's roadmap describes; that's a separate, larger effort.

Usage:
    python3 scripts/eval_consistency.py --n 10 --role-profile product_manager
    python3 scripts/eval_consistency.py --n 10 --runs 5

A listing is skipped (not counted as a failure) if it can no longer be
fetched — closed/removed since it was originally scanned, or (for very large
boards) outside the per-board result cap the fetch shares with the app's own
"score a listing by URL" path. Skipped listings are backfilled from the same
score band so the sample size still reaches --n.
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

import sources.ashby as ashby
import sources.bamboohr as bamboohr
import sources.gem as gem
import sources.greenhouse as greenhouse
import sources.lever as lever
from engines.rubric import _score_one
from role_profiles import get_profile
from utils.extract import parse_company_and_source_from_url

_SEARCH_FUNCS = {
    "greenhouse": lambda token: greenhouse.search_greenhouse("", boards=[token], limit=500),
    "ashby": lambda token: ashby.search_ashby("", boards=[token], limit=500),
    "lever": lambda token: lever.search_lever("", boards=[token], limit=500),
    "gem": lambda token: gem.search_gem("", boards=[token], limit=500),
    "bamboohr": lambda token: bamboohr.search_bamboohr("", boards=[token], limit=500),
}


def _fetch_listing(url: str, source: str, board: str) -> dict | None:
    """Same accurate per-platform fetch app.py's '_fetch_listing_by_url' and
    Deep Dive's manual-URL path use, including embedded-board resolution
    (see sources/greenhouse.py and sources/ashby.py) - so this script tests
    the rubric against the exact same listing text a real user would see,
    not a stale cached description."""
    token, parsed_source = parse_company_and_source_from_url(url)
    token = token or board
    parsed_source = parsed_source or source
    search_fn = _SEARCH_FUNCS.get(parsed_source)
    if search_fn and token:
        try:
            jobs, _meta = search_fn(token)
            target = url.rstrip("/")
            for job in jobs:
                if (job.get("url") or "").rstrip("/") == target:
                    return job
        except Exception:
            pass
    if parsed_source == "greenhouse":
        job = greenhouse.resolve_embedded_job(url)
        if job:
            return job
    if parsed_source == "ashby":
        job = ashby.resolve_embedded_job(url)
        if job:
            return job
    return None


def _load_candidates(role_profile_id: str) -> list[dict]:
    """Every cached scan for this role profile, sorted by score - lets the
    sample get spread across the full range rather than clustering wherever
    the most recent search happened to land."""
    with open("scan_history.csv") as f:
        rows = list(csv.DictReader(f))
    rows = [r for r in rows if r.get("role_profile") == role_profile_id and r.get("source") in _SEARCH_FUNCS]
    rows.sort(key=lambda r: float(r["score"]))
    return rows


def pick_sample(role_profile_id: str, n: int) -> list[dict]:
    """Spreads picks evenly across the cached score range, then verifies each
    is still live before committing to it - a closed listing gets swapped for
    the next one in the same band instead of shrinking the sample."""
    candidates = _load_candidates(role_profile_id)
    if not candidates:
        return []
    band_count = min(n, len(candidates))
    picks: list[dict] = []
    used_boards: set[str] = set()

    for i in range(band_count):
        target_idx = int(i * (len(candidates) - 1) / max(band_count - 1, 1))
        # search outward from the target index for the nearest still-live,
        # not-yet-used listing, so one dead posting doesn't just vanish from
        # the sample - it gets replaced by its closest neighbor on the curve.
        offsets = [0] + [d for step in range(1, len(candidates)) for d in (step, -step)]
        for offset in offsets:
            idx = target_idx + offset
            if not (0 <= idx < len(candidates)):
                continue
            row = candidates[idx]
            if row["board"].lower() in used_boards:
                continue
            job = _fetch_listing(row["url"], row["source"], row["board"])
            if job:
                picks.append({"row": row, "job": job})
                used_boards.add(row["board"].lower())
                break
    return picks


def run_eval(n: int, runs: int, role_profile_id: str) -> list[dict]:
    with open("sample_data/resume.md") as f:
        resume = f.read()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    profile = get_profile(role_profile_id)

    picks = pick_sample(role_profile_id, n)
    results = []
    for pick in picks:
        row, job = pick["row"], pick["job"]
        cached_score = float(row["score"])
        run_scores = []
        run_grades = []
        run_reasons = []
        for _ in range(runs):
            try:
                qs = _score_one(resume, job, api_key, profile, deepseek_key)
                run_scores.append(qs.score)
                run_grades.append(qs.grade)
                run_reasons.append(qs.reason)
            except Exception as e:
                run_reasons.append(f"ERROR: {e}")

        avg_new = round(sum(run_scores) / len(run_scores), 2) if run_scores else None
        spread = round(max(run_scores) - min(run_scores), 2) if run_scores else None
        results.append({
            "company": job.get("company") or row["board"],
            "title": job.get("title"),
            "url": row["url"],
            "cached_score": cached_score,
            "cached_grade": row["grade"],
            "run_scores": run_scores,
            "run_grades": run_grades,
            "run_reasons": run_reasons,
            "avg_new": avg_new,
            "spread": spread,
            "grade_flip": len(set(run_grades)) > 1,
            "delta_from_cache": round(avg_new - cached_score, 2) if avg_new is not None else None,
        })
    return results


def print_report(results: list[dict]) -> None:
    for r in results:
        print(f"\n=== {r['company']} — {r['title']} ===")
        print(f"cached: {r['cached_score']} ({r['cached_grade']})")
        for i, (score, grade, reason) in enumerate(zip(r["run_scores"], r["run_grades"], r["run_reasons"])):
            print(f"  run {i + 1}: {score} ({grade}) — {reason}")
        print(f"  spread={r['spread']}  grade_flip={r['grade_flip']}  avg_new={r['avg_new']}  delta={r['delta_from_cache']}")

    print("\n=== SUMMARY ===")
    flips = sum(1 for r in results if r["grade_flip"])
    big_deltas = sum(1 for r in results if r["delta_from_cache"] is not None and abs(r["delta_from_cache"]) >= 0.8)
    for r in results:
        flag = " <== GRADE FLIP" if r["grade_flip"] else ""
        flag += " <== LARGE DELTA FROM CACHE" if r["delta_from_cache"] is not None and abs(r["delta_from_cache"]) >= 0.8 else ""
        print(f"{r['company']:15s} cached={r['cached_score']:>4} avg_new={r['avg_new']!s:>5} "
              f"delta={r['delta_from_cache']!s:>5} spread={r['spread']!s:>4}{flag}")
    print(f"\n{flips}/{len(results)} flipped letter grade across {len(results[0]['run_scores']) if results else 0} runs; "
          f"{big_deltas}/{len(results)} drifted >=0.8 from the originally cached score.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10, help="Number of listings to sample (default 10)")
    parser.add_argument("--runs", type=int, default=3, help="Repeat scoring runs per listing (default 3)")
    parser.add_argument("--role-profile", default="product_manager", help="Role profile id (default product_manager)")
    args = parser.parse_args()

    results = run_eval(args.n, args.runs, args.role_profile)
    print_report(results)
