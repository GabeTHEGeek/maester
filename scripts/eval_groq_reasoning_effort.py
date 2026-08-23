"""
eval_groq_reasoning_effort.py
Isolates one variable from eval_groq_vs_deepseek.py's result: that run used
reasoning_effort="low" on Groq (a workaround for gpt-oss-120b returning
empty content on a tight token budget - see engines/llm_fallback.py), which
is NOT how DeepSeek was tested (thinking fully disabled, its own normal fast
mode) - an unfair asymmetry, not a like-for-like comparison.

This calls Groq directly (bypassing call_with_fallback's hardcoded "low") at
a configurable reasoning_effort and max_tokens, same 10 listings and 3-run
design as before, to see whether Groq's higher spread/lower scores were
caused by the artificially suppressed reasoning, or are real to the model.

Usage:
    python3 scripts/eval_groq_reasoning_effort.py --reasoning-effort medium --max-tokens 2000
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

import openai

from engines.llm_fallback import GROQ_BASE_URL, GROQ_DEFAULT_MODEL, extract_json
from engines.rubric import _build_system_prompt, _score_to_grade
from role_profiles import get_profile
from scripts.eval_consistency import pick_sample


def _score_with_groq(resume_text, job, groq_api_key, role_profile, reasoning_effort, max_tokens):
    system_prompt = _build_system_prompt(role_profile)
    user_prompt = f"""RESUME:
{resume_text}

JOB LISTING:
Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
Description: {job['description']}
"""
    client = openai.OpenAI(api_key=groq_api_key, base_url=GROQ_BASE_URL)
    kwargs = {}
    if reasoning_effort != "none":
        kwargs["reasoning_effort"] = reasoning_effort
    response = client.chat.completions.create(
        model=GROQ_DEFAULT_MODEL,
        max_tokens=max_tokens,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        **kwargs,
    )
    content = response.choices[0].message.content
    reasoning_tokens = response.usage.completion_tokens_details.reasoning_tokens
    if not content:
        raise ValueError(f"Empty content (reasoning_tokens={reasoning_tokens}, finish_reason={response.choices[0].finish_reason})")
    data = extract_json(content)
    score = float(data["score"])
    return {"score": score, "grade": _score_to_grade(score), "reasoning_tokens": reasoning_tokens}


def run(n, runs, role_profile_id, reasoning_effort, max_tokens):
    with open("sample_data/resume.md") as f:
        resume = f.read()
    groq_key = os.environ.get("GROQ_API_KEY", "")
    profile = get_profile(role_profile_id)

    picks = pick_sample(role_profile_id, n)
    results = []
    for pick in picks:
        row, job = pick["row"], pick["job"]
        scores, grades, reasoning_tok = [], [], []
        errors = []
        for _ in range(runs):
            try:
                r = _score_with_groq(resume, job, groq_key, profile, reasoning_effort, max_tokens)
                scores.append(r["score"])
                grades.append(r["grade"])
                reasoning_tok.append(r["reasoning_tokens"])
            except Exception as e:
                errors.append(str(e))
        results.append({
            "company": job.get("company") or row["board"],
            "title": job.get("title"),
            "cached_score": float(row["score"]),
            "scores": scores,
            "grades": grades,
            "reasoning_tok": reasoning_tok,
            "errors": errors,
            "avg": round(sum(scores) / len(scores), 2) if scores else None,
            "spread": round(max(scores) - min(scores), 2) if scores else None,
            "flip": len(set(grades)) > 1,
        })
    return results


def print_report(results, reasoning_effort, max_tokens):
    print(f"reasoning_effort={reasoning_effort!r}  max_tokens={max_tokens}\n")
    for r in results:
        print(f"=== {r['company']} — {r['title']} ===")
        print(f"cached: {r['cached_score']}")
        print(f"runs:   {list(zip(r['scores'], r['grades']))}  avg={r['avg']}  spread={r['spread']}  flip={r['flip']}  reasoning_tokens={r['reasoning_tok']}")
        if r["errors"]:
            print(f"errors: {r['errors']}")
        print()

    flips = sum(1 for r in results if r["flip"])
    spreads = [r["spread"] for r in results if r["spread"] is not None]
    avg_spread = round(sum(spreads) / len(spreads), 3) if spreads else None
    print(f"=== SUMMARY (reasoning_effort={reasoning_effort}, max_tokens={max_tokens}) ===")
    print(f"{flips}/{len(results)} grade flips, average spread={avg_spread}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--role-profile", default="product_manager")
    parser.add_argument("--reasoning-effort", default="medium", choices=["low", "medium", "high", "none"])
    parser.add_argument("--max-tokens", type=int, default=2000)
    args = parser.parse_args()

    results = run(args.n, args.runs, args.role_profile, args.reasoning_effort, args.max_tokens)
    print_report(results, args.reasoning_effort, args.max_tokens)
