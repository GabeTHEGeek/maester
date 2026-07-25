"""
rubric_engine.py
Fast, cheap multi-dimension rubric scoring for batches of jobs. This is the
first pass over search results: score everything, rank it, then only run the
expensive 5-panelist deep-dive (panel_engine.run_panel) on whatever the user
clicks into.

Uses Haiku for speed/cost since this runs once per job in a batch.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import anthropic

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
  ML/infra depth the candidate doesn't have, cap the overall score at 2.5
  regardless of other dimensions)
- Seniority fit (over- or under-leveled counts against it)
- Domain/industry relevance
- Location/remote feasibility given what the listing states

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
  "grade": "<A|B|C|D|F>",
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


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model response")
    return json.loads(match.group(0))


def _score_one(client, resume_text: str, job: dict) -> QuickScore:
    user_prompt = f"""RESUME:
{resume_text}

JOB LISTING:
Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
Description: {job['description']}
"""
    response = client.messages.create(
        model=QUICK_MODEL,
        max_tokens=400,
        system=RUBRIC_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    data = _extract_json(response.content[0].text)
    return QuickScore(
        job_id=str(job.get("id", job["url"])),
        title=job["title"],
        company=job["company"],
        url=job["url"],
        score=float(data["score"]),
        grade=data["grade"],
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


def batch_score(resume_text: str, jobs: list[dict], api_key: str, max_workers: int = 5) -> list[QuickScore]:
    """Score every job in `jobs` against `resume_text` in parallel, return ranked results."""
    client = anthropic.Anthropic(api_key=api_key)
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_score_one, client, resume_text, job): job for job in jobs}
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
    that's already been scanned before — no API call needed."""
    return QuickScore(
        job_id=job_id,
        title=row.get("title", ""),
        company=row.get("company", ""),
        url=row.get("url", ""),
        score=float(row.get("score") or 0),
        grade=row.get("grade", "?"),
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
