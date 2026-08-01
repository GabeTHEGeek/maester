"""
rubric.py
Fast, cheap multi-dimension rubric scoring for batches of jobs. This is the
first pass over search results: score everything, rank it, then only run the
expensive 5-panelist deep-dive (panel.run_panel) on whatever the user
clicks into.

Uses Haiku for speed/cost since this runs once per job in a batch.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from utils.extract import compute_current_role_tenure
from engines.llm_fallback import call_with_fallback, extract_json

QUICK_MODEL = "claude-haiku-4-5-20251001"

RUBRIC_SYSTEM_PROMPT = """You score how well a candidate's resume fits a job listing
across weighted dimensions, the way an ATS-savvy recruiter would triage a stack of
applications fast. Be honest and calibrated — most listings should NOT score above 4.0.

CRITICAL — do not confuse keyword overlap with fit. A title or description sharing
buzzwords with the resume (e.g. both mention "Agentic AI," "Product Manager," "AI/ML")
is NOT evidence of fit by itself. Titles can be misleading — a "Product Manager" or
"Staff Product Manager" title sometimes describes a hands-on technical/engineering
role wearing a product-sounding name (check for signals like: owns architecture
decisions, writes/reviews production code, "AI-native" tooling requirements aimed at
engineers, reports into engineering rather than product). Score based on the
listing's actual substantive requirements, not surface term matching against the resume.

CANDIDATE'S AI PROFILE: applied AI/LLM product engineering (prompt engineering,
multi-model orchestration, agentic workflow design, API integration) — NOT deep ML,
NOT ML infra/deployment, NOT classical ML. A listing wanting model training, ML infra
ownership, or research-scientist depth is a real gap even if it says "AI."

Dimensions:
- Role/Skills match (gate: if this is weak, OR if the role's actual substance is
  technical/engineering despite a PM-sounding title, OR if it requires deep
  ML/infra depth the candidate doesn't have, the overall score has a CEILING of
  2.5 — not a fixed value of 2.5. Within that gated range, still use real
  judgment about how severe the specific gap is: a role with some tangential
  overlap (e.g., adjacent domain, transferable skills) can land higher within
  the range, around 2.0-2.5, while a role with no realistic alignment at all
  should land lower, around 1.0-1.5. Two different listings that fail the gate
  for two different reasons should very rarely produce the identical number —
  if they keep landing on exactly the same score, that's a sign of defaulting
  to a round anchor value instead of actually differentiating by severity.)
- Seniority fit (over- or under-leveled counts against it)
- Domain/industry relevance
- Location/remote feasibility given what the listing states

Use the full decimal range meaningfully across every dimension, not just the
gated one — two listings with genuinely different degrees of fit, even within
the same rough tier, should generally produce different scores, not the same
rounded number, unless they truly are equivalently good or bad matches.

Also produce two brief, separate signals — these do NOT affect the score:

legitimacy_tier: classify the posting as "High Confidence" (reads like a real,
specific, internally consistent posting), "Proceed with Caution" (mixed signals,
e.g. generic requirements, unclear scope — not necessarily disqualifying), or
"Suspicious" (multiple concerning indicators — requires payment, unrealistic pay
for minimal experience, high-pressure urgency language). Never frame this as an
accusation; these are signals for the candidate to weigh, not a verdict, and
vague listings often have benign explanations (early-stage startup, terse recruiter
posting). Keep legitimacy_note to one short, neutral phrase.

comp_reliability: classify how much to trust any salary figure in the listing as
"High" (stated as clear base or backed by structured public bands), "Medium"
(plausible but base/bonus/commission not clearly separated), "Low" (likely
inflated by commission/OTE/"up to" framing), or "Unknown" (no usable salary data —
do not invent a number).

Respond ONLY with valid JSON, no markdown fences, no prose outside the JSON:
{
  "score": <float 1.0-5.0>,
  "reason": "<one sentence, specific, not generic>",
  "legitimacy_tier": "<High Confidence|Proceed with Caution|Suspicious>",
  "legitimacy_note": "<one short neutral phrase>",
  "comp_reliability": "<High|Medium|Low|Unknown>"
}
"""


@dataclass
class QuickScore:
    job_id: str
    title: str
    company: str
    url: str
    score: float
    grade: str
    reason: str
    source: str = "unknown"
    board: str = "unknown"
    location: str = ""
    salary: str = ""
    legitimacy_tier: str = ""
    legitimacy_note: str = ""
    comp_reliability: str = ""
    published: str = ""


def _score_to_grade(score: float) -> str:
    """Deterministic score-to-grade mapping, computed in code rather than
    asked of the model as a separate field. Real evidence from actual use
    showed two listings with an identical 2.5 score getting different
    grades (D and C) — the model was making two loosely related judgments
    in one response instead of deriving one from the other. This removes
    that whole class of inconsistency; grade is now purely a function of
    score, so they can never disagree."""
    if score >= 4.5:
        return "A"
    if score >= 3.5:
        return "B"
    if score >= 2.5:
        return "C"
    if score >= 1.5:
        return "D"
    return "F"


def _score_one(resume_text: str, job: dict, api_key: str, deepseek_api_key: str = "") -> QuickScore:
    tenure_note = compute_current_role_tenure(resume_text)
    tenure_block = f"\nVERIFIED FACT: {tenure_note}\n" if tenure_note else ""

    user_prompt = f"""RESUME:
{resume_text}
{tenure_block}
JOB LISTING:
Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
Description: {job['description']}
"""
    text, _provider = call_with_fallback(
        system_prompt=RUBRIC_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        anthropic_api_key=api_key,
        anthropic_model=QUICK_MODEL,
        max_tokens=700,
        deepseek_api_key=deepseek_api_key,
    )
    try:
        data = extract_json(text)
    except (ValueError, json.JSONDecodeError):
        # Same truncation safety net as the deep-dive panel and tailoring —
        # quick-scan was missing this entirely, so any truncated response
        # just failed outright instead of getting a chance to retry with
        # more room, unlike the other two engines.
        text, _provider = call_with_fallback(
            system_prompt=RUBRIC_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            anthropic_api_key=api_key,
            anthropic_model=QUICK_MODEL,
            max_tokens=1200,
            deepseek_api_key=deepseek_api_key,
        )
        data = extract_json(text)
    return QuickScore(
        job_id=str(job.get("id", job["url"])),
        title=job["title"],
        company=job["company"],
        url=job["url"],
        score=float(data["score"]),
        grade=_score_to_grade(float(data["score"])),
        reason=data.get("reason", ""),
        source=job.get("source", "unknown"),
        board=job.get("board", "unknown"),
        location=job.get("location", ""),
        published=job.get("published", ""),
        salary=job.get("salary", ""),
        legitimacy_tier=data.get("legitimacy_tier", ""),
        legitimacy_note=data.get("legitimacy_note", ""),
        comp_reliability=data.get("comp_reliability", ""),
    )


def batch_score(
    resume_text: str,
    jobs: list[dict],
    api_key: str,
    deepseek_api_key: str = "",
    max_workers: int = 5,
) -> list[QuickScore]:
    """Score every job in `jobs` against `resume_text` in parallel, return ranked results."""
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_score_one, resume_text, job, api_key, deepseek_api_key): job
            for job in jobs
        }
        for future in as_completed(futures):
            job = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                results.append(
                    QuickScore(
                        job_id=str(job.get("id", job["url"])),
                        title=job["title"],
                        company=job["company"],
                        url=job["url"],
                        score=0.0,
                        grade="?",
                        reason=f"Scoring failed: {e}",
                        source=job.get("source", "unknown"),
                        board=job.get("board", "unknown"),
                        location=job.get("location", ""),
                        published=job.get("published", ""),
                        salary=job.get("salary", ""),
                    )
                )
    results.sort(key=lambda r: r.score, reverse=True)
    return results


def quick_score_from_cache(row: dict, job_id: str) -> QuickScore:
    """Reconstructs a QuickScore from a scan_history.csv row, for a listing
    that's already been scanned before — no API call needed. Grade is
    recomputed from the cached score rather than read from the row directly,
    so any older cached entry from before grade became a deterministic
    function of score self-heals automatically instead of continuing to
    show whatever mismatched grade it was cached with."""
    cached_score = float(row.get("score") or 0)
    return QuickScore(
        job_id=job_id,
        title=row.get("title", ""),
        company=row.get("company", ""),
        url=row.get("url", ""),
        score=cached_score,
        grade=_score_to_grade(cached_score),
        reason=row.get("reason", ""),
        source=row.get("source", "unknown"),
        board=row.get("board", "unknown"),
        location=row.get("location", ""),
        salary=row.get("salary", ""),
        legitimacy_tier=row.get("legitimacy_tier", ""),
        legitimacy_note=row.get("legitimacy_note", ""),
        comp_reliability=row.get("comp_reliability", ""),
        published=row.get("published", ""),
    )
