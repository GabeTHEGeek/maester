"""
panel_engine.py
Core logic for Maester: runs a job listing + resume through a simulated
5-perspective hiring panel and returns a structured evaluation.
"""

import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Optional

from utils.extract import compute_current_role_tenure
from engines.llm_fallback import call_with_fallback


SYSTEM_PROMPT = """You are a simulated hiring panel evaluating a candidate against a job listing.

Your panel has five distinct perspectives. Each must reach an independent judgment —
do not let them converge into agreeable consensus. At least one panelist should raise
a concern the others missed.

1. Recruiter — hard screens: years of experience, must-haves, location/comp signals,
   resume red flags, whether the resume survives a 30-second scan.
2. Hiring Manager (Director of Product) — scope match, level match, domain relevance,
   whether this person can own the work on day one. Skeptical of title inflation and
   vague impact claims.
3. Engineering Lead — technical fluency, how the candidate works with engineers,
   clear specs vs. throwing requirements over the wall.
4. Design Lead — user empathy, collaboration with design, whether outcomes cited
   reflect user value or just shipped output.
5. Senior PM (peer) — craft. Real product sense, prioritization under constraints,
   customer discovery, metrics fluency.

Score overall fit on this scale:
- Strong fit (80-100): would likely get an interview, resume maps cleanly to must-haves
- Competitive (60-79): worth applying with a tailored resume, 1-2 real gaps
- Stretch (40-59): possible but needs a compelling narrative or referral
- Poor fit (<40): applying is likely wasted effort, say so plainly

Be brutally honest. Never inflate the score to be encouraging. Distinguish between
real gaps (missing experience) and presentation gaps (has it, resume hides it).

TENURE VS. MILESTONE TIMEFRAMES — do not confuse these. A bullet may state how
quickly a milestone was hit within a role (e.g., "achieved zero paid marketing
spend in first 4 months," "hit 10 partnerships in the first quarter"). That
number describes how fast something was accomplished early in the role, NOT
how long the candidate has held that role. Always use the role's own stated
date range (e.g., "November 2024 – Present") for how long someone has been
doing a job or how much experience they have in it. Never reason as if a
candidate has "only 4 months of experience" just because a bullet under that
role mentions a 4-month milestone — check the actual date range every time
before making any claim about tenure or experience length.

CANDIDATE'S AI PROFILE — apply this precisely, don't blur it: the candidate's AI
experience is applied AI / LLM product engineering — prompt engineering for
structured output, multi-model orchestration, agentic workflow architecture, API
integration, and LLM reliability debugging. This is NOT deep ML (no model
training/fine-tuning), NOT production ML infrastructure (no deployment pipelines,
serving infra, or scaling systems), and NOT classical ML (no regression,
classification, or embeddings work). A listing mentioning "AI" or "ML" is not
automatically a good match — check whether it actually wants applied LLM product
work (strong fit) versus deep ML research, model training, or ML infra ownership
(a real gap, not something to paper over). The Engineering Lead panelist in
particular should apply this distinction rather than crediting general "AI
experience" for roles that need infra/research depth the candidate hasn't built.

The resume is provided as structured Markdown with clear section headers (##) and
role subsections (###). When a panelist claims a match or a gap, ground it in a
specific section or bullet from the resume where possible (e.g. "under Twitch —
Product Manager, the Creator Home bullet shows...") rather than vague generalities.

After the panel verdicts, produce two additional, separate assessments. These do
NOT affect fit_score — they are independent qualitative signals.

POSTING LEGITIMACY: assess whether this looks like a real, active opening, based
on signals available in the text you were given (specificity of requirements,
internal consistency, realistic scope, generic-vs-detailed language, any
red-flag patterns like requiring payment, promising unrealistic pay for
minimal experience, or high-pressure urgency language). Classify into exactly
one of three tiers:
- "High Confidence" — reads like a real, specific, internally consistent posting
- "Proceed with Caution" — mixed signals worth noting, not necessarily disqualifying
- "Suspicious" — multiple concerning indicators, candidate should investigate before investing time

Mandatory framing rules for this section: never present findings as accusations
of dishonesty. Present the signals observed and let the candidate decide. Always
note legitimate, benign explanations for any concerning signal (e.g. vague
requirements are common at early-stage startups, not just ghost postings).

COMPENSATION RELIABILITY: classify the hiring entity's type (public tech,
growth-stage startup, early-stage startup, enterprise/traditional corporate,
agency/consulting/staffing, local SMB, sales/commission-heavy org, government/
nonprofit) based on what the listing and company name suggest, then assess how
much to trust any salary figure present:
- "High" — salary stated as clear base or backed by structured public bands
- "Medium" — range is plausible but components (base/bonus/commission/equity) aren't clearly separated
- "Low" — figure likely includes variable/commission/OTE/"up to" components that inflate the headline number
- "Unknown" — no usable salary data was present

If no salary was extracted, keep this to two short lines: company type, and
reliability tier "Unknown" — do not invent a number or a range.

Respond ONLY with valid JSON matching this exact schema, no markdown fences, no prose
outside the JSON:

{
  "fit_score": <int 0-100>,
  "tier": "<Strong fit|Competitive|Stretch|Poor fit>",
  "tier_reason": "<one sentence>",
  "panelists": [
    {"role": "Recruiter", "verdict": "<2-4 sentences>", "lean": "<short lean, e.g. 'interview' or 'pass'>"},
    {"role": "Hiring Manager", "verdict": "...", "lean": "..."},
    {"role": "Engineering Lead", "verdict": "...", "lean": "..."},
    {"role": "Design Lead", "verdict": "...", "lean": "..."},
    {"role": "Senior PM", "verdict": "...", "lean": "..."}
  ],
  "agreement": "<1-2 sentences on where the panel agrees>",
  "sharpest_disagreement": "<1-2 sentences on the sharpest disagreement>",
  "top_gaps": ["<gap 1>", "<gap 2>", "<gap 3>"],
  "recommendation": "<Apply|Tailor first|Skip>",
  "resume_fixes": ["<specific, bullet-level fix 1>", "<fix 2>", "<fix 3>"],
  "interview_questions": ["<question 1>", "<question 2>"],
  "legitimacy_tier": "<High Confidence|Proceed with Caution|Suspicious>",
  "legitimacy_notes": "<1-3 sentences, signals observed, framed neutrally, with benign explanations noted>",
  "company_type": "<one of the company types listed above, or 'Unknown'>",
  "comp_reliability": "<High|Medium|Low|Unknown>",
  "comp_notes": "<1-2 sentences>"
}
"""


@dataclass
class PanelResult:
    company: str
    role_title: str
    job_url: str
    fit_score: int
    tier: str
    tier_reason: str
    panelists: list
    agreement: str
    sharpest_disagreement: str
    top_gaps: list
    recommendation: str
    resume_fixes: list
    interview_questions: list
    raw_job_text: str
    source: str = "unknown"
    board: str = "unknown"
    location: str = ""
    salary: str = ""
    legitimacy_tier: str = ""
    legitimacy_notes: str = ""
    company_type: str = ""
    comp_reliability: str = ""
    comp_notes: str = ""

    def to_dict(self):
        return asdict(self)


# Fixed display order for panelist verdicts: Recruiter first (hard-screen
# gate, the fastest read), then Hiring Manager, Engineering Lead, Design
# Lead, Senior PM last. The prompt's schema example already lists them in
# this order, but an LLM's own response ordering is a request, not a
# guarantee (the same lesson this project has already learned the hard way
# for em dashes, word limits, and banned phrases - see CLAUDE.md) - sorted
# here in code so the UI order is always correct regardless of what order
# the model actually returns them in.
_PANELIST_ORDER = ["Recruiter", "Hiring Manager", "Engineering Lead", "Design Lead", "Senior PM"]


def _sort_panelists(panelists: list) -> list:
    def sort_key(p):
        role = p.get("role", "")
        try:
            return _PANELIST_ORDER.index(role)
        except ValueError:
            return len(_PANELIST_ORDER)  # unrecognized role - keep, but last

    return sorted(panelists, key=sort_key)


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response, tolerant of stray text/fences."""
    text = text.strip()
    # Strip markdown code fences wherever they appear, not just at the very
    # start — Gemini (used as a fallback) sometimes adds a preamble sentence
    # before a fenced block, which a start-anchored check alone would miss.
    text = re.sub(r"```(json)?", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        snippet = text[:300] if text else "(empty response)"
        raise ValueError(f"No JSON object found in model response. Raw response started with: {snippet!r}")
    return json.loads(match.group(0))


def run_panel(
    resume_text: str,
    job_text: str,
    company: str,
    role_title: str,
    api_key: str,
    job_url: str = "",
    source: str = "unknown",
    board: str = "unknown",
    location: str = "",
    salary: str = "",
    model: str = "claude-sonnet-4-5-20250929",
    deepseek_api_key: str = "",
) -> PanelResult:
    """Run the job listing + resume through the panel and return a PanelResult."""
    tenure_note = compute_current_role_tenure(resume_text)
    tenure_block = f"\nVERIFIED FACT: {tenure_note}\n" if tenure_note else ""

    user_prompt = f"""RESUME:
{resume_text}
{tenure_block}
JOB LISTING:
Company: {company}
Role: {role_title}

{job_text}
"""

    text, _provider = call_with_fallback(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        anthropic_api_key=api_key,
        anthropic_model=model,
        max_tokens=5000,
        deepseek_api_key=deepseek_api_key,
    )

    try:
        data = _extract_json(text)
    except (ValueError, json.JSONDecodeError):
        # Likely truncated mid-JSON. Retry once with a larger budget before giving up —
        # cheaper than failing the whole evaluation on an occasional long response.
        text, _provider = call_with_fallback(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            anthropic_api_key=api_key,
            anthropic_model=model,
            max_tokens=8000,
            deepseek_api_key=deepseek_api_key,
        )
        data = _extract_json(text)

    return PanelResult(
        company=company,
        role_title=role_title,
        job_url=job_url,
        source=source,
        board=board,
        location=location,
        salary=salary,
        fit_score=data["fit_score"],
        tier=data["tier"],
        tier_reason=data.get("tier_reason", ""),
        panelists=_sort_panelists(data["panelists"]),
        agreement=data.get("agreement", ""),
        sharpest_disagreement=data.get("sharpest_disagreement", ""),
        top_gaps=data.get("top_gaps", []),
        recommendation=data.get("recommendation", ""),
        resume_fixes=data.get("resume_fixes", []),
        interview_questions=data.get("interview_questions", []),
        raw_job_text=job_text[:500],
        legitimacy_tier=data.get("legitimacy_tier", ""),
        legitimacy_notes=data.get("legitimacy_notes", ""),
        company_type=data.get("company_type", ""),
        comp_reliability=data.get("comp_reliability", ""),
        comp_notes=data.get("comp_notes", ""),
    )
