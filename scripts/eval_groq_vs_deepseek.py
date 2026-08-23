"""
eval_groq_vs_deepseek.py
Cross-provider agreement + repeat-run consistency check for engines/rubric.py:
scores the same real listings through DeepSeek and Groq, 3 repeat runs each,
via the real call_with_fallback path (Anthropic naturally fails first on a
billing error, same as production when Anthropic is out of credits) - the
DeepSeek runs pass no Groq key so they can't spill over into Groq, and the
Groq runs pass no DeepSeek key so they can't spill over into DeepSeek. Each
provider is isolated to its own tier of the real fallback chain, not a
separate ad-hoc call path.

Unlike the Gemini comparison (scripts/eval_provider_comparison.py, capped at
1 run/listing because of Gemini's 20-requests/day free-tier ceiling), Groq's
14,400/day cap comfortably supports the same 3x-repeat design already used
for DeepSeek-only consistency testing (scripts/eval_consistency.py).

Usage:
    python3 scripts/eval_groq_vs_deepseek.py --n 10 --runs 3
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from engines.rubric import _score_one
from role_profiles import get_profile
from scripts.eval_consistency import pick_sample


def _run_n_times(resume, job, api_key, profile, deepseek_key, groq_key, runs):
    scores, grades, errors = [], [], []
    for _ in range(runs):
        try:
            qs = _score_one(resume, job, api_key, profile, deepseek_api_key=deepseek_key, groq_api_key=groq_key)
            scores.append(qs.score)
            grades.append(qs.grade)
        except Exception as e:
            errors.append(str(e))
    return scores, grades, errors


def run_comparison(n: int, runs: int, role_profile_id: str) -> list[dict]:
    with open("sample_data/resume.md") as f:
        resume = f.read()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    groq_key = os.environ.get("GROQ_API_KEY", "")
    profile = get_profile(role_profile_id)

    picks = pick_sample(role_profile_id, n)
    results = []
    for pick in picks:
        row, job = pick["row"], pick["job"]
        cached_score = float(row["score"])

        # DeepSeek only: no Groq key passed, so a DeepSeek failure can't
        # silently fall through to Groq and contaminate this provider's data.
        ds_scores, ds_grades, ds_errors = _run_n_times(resume, job, api_key, profile, deepseek_key, "", runs)
        # Groq only: no DeepSeek key passed, same isolation in reverse.
        gq_scores, gq_grades, gq_errors = _run_n_times(resume, job, api_key, profile, "", groq_key, runs)

        ds_avg = round(sum(ds_scores) / len(ds_scores), 2) if ds_scores else None
        gq_avg = round(sum(gq_scores) / len(gq_scores), 2) if gq_scores else None

        results.append({
            "company": job.get("company") or row["board"],
            "title": job.get("title"),
            "url": row["url"],
            "cached_score": cached_score,
            "cached_grade": row["grade"],
            "deepseek_scores": ds_scores, "deepseek_grades": ds_grades, "deepseek_errors": ds_errors,
            "deepseek_avg": ds_avg,
            "deepseek_spread": round(max(ds_scores) - min(ds_scores), 2) if ds_scores else None,
            "deepseek_flip": len(set(ds_grades)) > 1,
            "groq_scores": gq_scores, "groq_grades": gq_grades, "groq_errors": gq_errors,
            "groq_avg": gq_avg,
            "groq_spread": round(max(gq_scores) - min(gq_scores), 2) if gq_scores else None,
            "groq_flip": len(set(gq_grades)) > 1,
            "cross_delta": round(ds_avg - gq_avg, 2) if (ds_avg is not None and gq_avg is not None) else None,
        })
    return results


def print_report(results: list[dict]) -> None:
    for r in results:
        print(f"\n=== {r['company']} — {r['title']} ===")
        print(f"cached (Haiku):  {r['cached_score']} ({r['cached_grade']})")
        print(f"DeepSeek runs:   {list(zip(r['deepseek_scores'], r['deepseek_grades']))}  avg={r['deepseek_avg']}  spread={r['deepseek_spread']}  flip={r['deepseek_flip']}")
        if r["deepseek_errors"]:
            print(f"  DeepSeek errors: {r['deepseek_errors']}")
        print(f"Groq runs:       {list(zip(r['groq_scores'], r['groq_grades']))}  avg={r['groq_avg']}  spread={r['groq_spread']}  flip={r['groq_flip']}")
        if r["groq_errors"]:
            print(f"  Groq errors: {r['groq_errors']}")
        print(f"cross-provider delta (DeepSeek - Groq): {r['cross_delta']}")

    print("\n=== SUMMARY ===")
    ds_flips = sum(1 for r in results if r["deepseek_flip"])
    gq_flips = sum(1 for r in results if r["groq_flip"])
    big_deltas = sum(1 for r in results if r["cross_delta"] is not None and abs(r["cross_delta"]) >= 0.8)
    for r in results:
        flag = ""
        if r["deepseek_flip"]:
            flag += " <== DEEPSEEK FLIP"
        if r["groq_flip"]:
            flag += " <== GROQ FLIP"
        if r["cross_delta"] is not None and abs(r["cross_delta"]) >= 0.8:
            flag += " <== PROVIDERS DISAGREE"
        print(f"{r['company']:15s} cached={r['cached_score']:>4} deepseek={r['deepseek_avg']!s:>5} groq={r['groq_avg']!s:>5} delta={r['cross_delta']!s:>5}{flag}")

    n = len(results)
    runs = len(results[0]["deepseek_scores"]) if results and results[0]["deepseek_scores"] else 0
    print(f"\n{ds_flips}/{n} DeepSeek grade flips across {runs} runs; {gq_flips}/{n} Groq grade flips; "
          f"{big_deltas}/{n} cross-provider deltas >=0.8.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10, help="Number of listings to sample (default 10)")
    parser.add_argument("--runs", type=int, default=3, help="Repeat runs per provider per listing (default 3)")
    parser.add_argument("--role-profile", default="product_manager", help="Role profile id (default product_manager)")
    args = parser.parse_args()

    results = run_comparison(args.n, args.runs, args.role_profile)
    print_report(results)
