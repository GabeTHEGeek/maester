"""
eval_provider_comparison.py
Cross-provider agreement check for engines/rubric.py: scores the same real
listings through DeepSeek (3 repeat runs each, via the normal
call_with_fallback path - Anthropic naturally falls through to DeepSeek
whenever it's out of credits) and Gemini (1 run each, via call_gemini), and
compares both against the originally cached (Haiku) score.

Gemini is capped at 1 run per listing and a small listing count on purpose:
its free tier has a hard 20-requests/day ceiling, confirmed directly to
already be hitting "503 high demand" errors under light testing load - a
3x-repeat design like the DeepSeek-only consistency script would burn most
of a day's quota on one script run. See scripts/eval_consistency.py for the
same-provider repeat-run version this reuses fetch logic from.

Usage:
    python3 scripts/eval_provider_comparison.py --n 5 --role-profile product_manager
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from engines.llm_fallback import call_gemini, extract_json
from engines.rubric import QUICK_MODEL, _build_system_prompt, _score_one, _score_to_grade
from role_profiles import get_profile
from scripts.eval_consistency import pick_sample


def _score_with_gemini(resume_text: str, job: dict, gemini_api_key: str, role_profile) -> dict:
    """Same prompt shape as engines/rubric.py's _score_one, so DeepSeek and
    Gemini are judged on an identical prompt - only the model differs."""
    system_prompt = _build_system_prompt(role_profile)
    user_prompt = f"""RESUME:
{resume_text}

JOB LISTING:
Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
Description: {job['description']}
"""
    text = call_gemini(system_prompt, user_prompt, gemini_api_key)
    data = extract_json(text)
    score = float(data["score"])
    return {"score": score, "grade": _score_to_grade(score), "reason": data.get("reason", "")}


def run_comparison(n: int, deepseek_runs: int, role_profile_id: str) -> list[dict]:
    with open("sample_data/resume.md") as f:
        resume = f.read()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    profile = get_profile(role_profile_id)

    picks = pick_sample(role_profile_id, n)
    results = []
    for pick in picks:
        row, job = pick["row"], pick["job"]
        cached_score = float(row["score"])

        ds_scores, ds_grades = [], []
        for _ in range(deepseek_runs):
            try:
                qs = _score_one(resume, job, api_key, profile, deepseek_key)
                ds_scores.append(qs.score)
                ds_grades.append(qs.grade)
            except Exception as e:
                ds_grades.append(f"ERROR: {e}")

        gemini_result = None
        gemini_error = None
        if gemini_key:
            try:
                gemini_result = _score_with_gemini(resume, job, gemini_key, profile)
            except Exception as e:
                gemini_error = str(e)

        results.append({
            "company": job.get("company") or row["board"],
            "title": job.get("title"),
            "url": row["url"],
            "cached_score": cached_score,
            "cached_grade": row["grade"],
            "deepseek_scores": ds_scores,
            "deepseek_grades": ds_grades,
            "deepseek_avg": round(sum(ds_scores) / len(ds_scores), 2) if ds_scores else None,
            "gemini_score": gemini_result["score"] if gemini_result else None,
            "gemini_grade": gemini_result["grade"] if gemini_result else None,
            "gemini_reason": gemini_result["reason"] if gemini_result else None,
            "gemini_error": gemini_error,
        })
    return results


def print_report(results: list[dict]) -> None:
    for r in results:
        print(f"\n=== {r['company']} — {r['title']} ===")
        print(f"cached (Haiku):  {r['cached_score']} ({r['cached_grade']})")
        print(f"DeepSeek runs:   {list(zip(r['deepseek_scores'], r['deepseek_grades']))}  avg={r['deepseek_avg']}")
        if r["gemini_error"]:
            print(f"Gemini:          FAILED — {r['gemini_error']}")
        elif r["gemini_score"] is not None:
            print(f"Gemini:          {r['gemini_score']} ({r['gemini_grade']}) — {r['gemini_reason']}")
        else:
            print("Gemini:          skipped (no GEMINI_API_KEY set)")

    print("\n=== SUMMARY ===")
    for r in results:
        ds = r["deepseek_avg"]
        gm = r["gemini_score"]
        delta = round(ds - gm, 2) if (ds is not None and gm is not None) else None
        flag = " <== DEEPSEEK/GEMINI DISAGREE" if delta is not None and abs(delta) >= 0.8 else ""
        gm_display = gm if gm is not None else ("ERR" if r["gemini_error"] else "n/a")
        print(f"{r['company']:15s} cached={r['cached_score']:>4} deepseek_avg={ds!s:>5} gemini={gm_display!s:>5} delta={delta!s:>5}{flag}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=5, help="Number of listings to sample (default 5)")
    parser.add_argument("--deepseek-runs", type=int, default=3, help="Repeat DeepSeek runs per listing (default 3)")
    parser.add_argument("--role-profile", default="product_manager", help="Role profile id (default product_manager)")
    args = parser.parse_args()

    results = run_comparison(args.n, args.deepseek_runs, args.role_profile)
    print_report(results)
