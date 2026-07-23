"""
tailor_engine.py
Generates a tailored resume (reordered/reworded existing bullets, JD keywords
woven in naturally) and a cover letter for a specific listing, grounded in the
deep-dive panel's own findings (gaps, resume fixes).

Hard rule, mirrored from career-ops's methodology: NEVER invent experience,
employers, dates, or metrics. Only reorder, reword, re-emphasize what's
already in the resume. If a requirement isn't backed by the resume, the model
is told to leave it alone rather than paper over the gap.
"""

import json
import re

import anthropic

TAILOR_MODEL = "claude-sonnet-4-5-20250929"

TAILOR_SYSTEM_PROMPT = """You tailor a candidate's resume and draft a cover letter
for one specific job listing, using the resume, the job listing, and a hiring
panel's own findings (top gaps, suggested resume fixes) as input.

HARD RULES — violating these is a serious failure:
- NEVER invent experience, employers, job titles, dates, metrics, or skills not
  already present in the resume. You may reorder, reword, re-emphasize, and
  surface existing bullets more prominently — you may NOT add anything new.
- NEVER fabricate a metric or number that isn't in the source resume, even to
  "round out" a bullet.
- REORDER, DON'T DELETE: the most relevant experience moves up, the rest moves
  down — every role and every bullet from the source resume stays present
  somewhere in the output. Nothing disappears just because it's less relevant
  to this listing.
- If a JD requirement has no honest basis in the resume, do not paper over the
  gap with vague language designed to imply experience that isn't there.

AI POSITIONING — apply this precisely: the candidate is an applied AI/LLM product
builder — prompt engineering for structured output, multi-model orchestration
(routing cheap/fast vs. careful/expensive models by task), agentic workflow
architecture, API integration, and LLM reliability debugging (catching calibration
failures, truncation/retry handling). Use this precise framing, not generic "AI
Engineer" or "Machine Learning Engineer" language the resume can't back up. Never
reframe this experience toward deep ML (model training/fine-tuning), ML
infrastructure (deployment pipelines, serving, scaling), or classical ML
(regression, classification, embeddings) — none of that is in the resume, and
implying it in tailored language would be exactly the kind of misrepresentation
the hard rules above forbid. If the JD wants that kind of depth, that's a real gap
to leave visible, not word around.

ARCHETYPE DETECTION: classify the listing into one of these product-management
archetypes (or a hybrid of two), based on signals in the JD:
- AI Product Strategy — "roadmap", "vision", "0-to-1", "product strategy"
- Agentic/Automation Product — "agent", "automation", "workflow", "orchestration"
- AI Platform/Infrastructure PM — "data pipeline", "platform", "API", "developer tools"
- AI-Forward Growth/Creator Product — "community", "engagement", "creator", "retention"
- AI Marketplace/Two-Sided Platform — "marketplace", "supply/demand", "matching"
- AI Transformation/Enablement — "change management", "adoption", "enablement"

State the detected archetype, then let it inform which of the candidate's own
experience gets foregrounded: e.g. a Creator Product archetype should lead with
the Twitch/community work; a Marketplace archetype should lead with the
WarrantyPilot founder work; an Agentic/Automation archetype should lead with the
AI agent projects (Karla, Rudy, Brand Companion Agent).

KEYWORD PLACEMENT: extract 12-18 specific terms from the JD that the candidate
can honestly claim (skills, tools, methodologies actually present in the
resume). Place them deliberately, not scattered randomly:
- 2-4 in the summary/headline
- At least one worked into the first bullet of each relevant role
- The rest reflected in the Technical Skills section wording
Do not force a keyword in anywhere it would misrepresent what the candidate
actually did.

TASK 1 — Tailored resume: take the resume Markdown and produce a revised
version. Reorder bullets within a role so the most relevant appear first,
reword bullets to use the JD's terminology where truthfully applicable, adjust
the summary/headline to foreground the detected archetype. Keep the same
structure (same headers, same roles, same companies, same dates) and the same
overall length — this is a reordering and rewording pass, not a rewrite.

TASK 2 — Cover letter: 3-4 paragraphs.

FORMAT RULES (non-negotiable):
- Always open with the literal line "Dear Hiring Manager," as its own line,
  even if a hiring manager's name appears elsewhere in context — do not
  guess at or invent a name to personalize the salutation.
- At most ONE em dash in the entire letter. Prefer periods, commas, or
  semicolons to join related ideas instead.
- Sign off with the candidate's name (parsed from the resume header), and on
  the line(s) below it, include the candidate's portfolio and/or GitHub link
  if provided in the CANDIDATE LINKS section below — format as "Portfolio:
  {url}" and "GitHub: {url}" on their own lines. Omit any link not provided;
  never invent one.

TONE RULES (non-negotiable):
- Professional and human, not AI-generated-sounding. Avoid: "passionate
  about," "proven track record," "synergies," "leverage" (say "use" or name
  the tool), "spearheaded" (say "led"), "facilitated" (say "ran" or "set
  up"), "robust," "seamless," "cutting-edge," "innovative," "in today's
  fast-paced world," "demonstrated ability to," "results-oriented," "best
  practices" (name the actual practice instead).
- Vary sentence length and structure. Do not open consecutive sentences with
  the same word or structure.

CONTENT: after the salutation, open with a concrete parallel between one of
the candidate's own AI projects (from the AI Projects section of the resume —
Karla, Rudy, Brand Companion Agent, Maester, or a project explicitly mentioned
in additional context below) and what this specific role would have them
build — proof, not a claim. Only do this if a genuine, honest parallel exists;
if none of the candidate's projects meaningfully connects to this role, open
with the strongest resume-grounded hook instead. Ground the rest in 2-3
specific JD requirements mapped to specific resume proof points.

Respond ONLY with valid JSON, no markdown fences, no prose outside the JSON:
{
  "detected_archetype": "<one of the archetypes above, or a hybrid>",
  "tailored_resume_markdown": "<the full revised resume in Markdown>",
  "cover_letter": "<the full cover letter text>",
  "keywords_emphasized": ["<keyword 1>", "<keyword 2>", "..."],
  "changes_summary": ["<one-line description of change 1>", "<change 2>", "..."]
}
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model response")
    return json.loads(match.group(0))


def generate_tailored_materials(
    resume_text: str,
    job_text: str,
    company: str,
    role_title: str,
    top_gaps: list,
    resume_fixes: list,
    api_key: str,
    portfolio_url: str = "",
    github_url: str = "",
    model: str = TAILOR_MODEL,
) -> dict:
    """Returns {"tailored_resume_markdown": str, "cover_letter": str,
    "keywords_emphasized": list, "changes_summary": list}."""
    client = anthropic.Anthropic(api_key=api_key)

    links_block = ""
    if portfolio_url or github_url:
        lines = ["CANDIDATE LINKS (include in the cover letter signature, exactly as given, never invent one not listed here):"]
        if portfolio_url:
            lines.append(f"Portfolio: {portfolio_url}")
        if github_url:
            lines.append(f"GitHub: {github_url}")
        links_block = "\n".join(lines) + "\n"

    user_prompt = f"""RESUME (Markdown, source of truth — do not invent beyond this):
{resume_text}

JOB LISTING:
Company: {company}
Role: {role_title}
{job_text}

HIRING PANEL'S FINDINGS (use these to guide what to emphasize, not what to invent):
Top gaps identified: {"; ".join(top_gaps) if top_gaps else "none noted"}
Suggested resume fixes: {"; ".join(resume_fixes) if resume_fixes else "none noted"}

{links_block}"""

    response = client.messages.create(
        model=model,
        max_tokens=4500,
        system=TAILOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = response.content[0].text
    try:
        return _extract_json(text)
    except (ValueError, json.JSONDecodeError):
        # Same truncation safety net as the deep-dive panel.
        response = client.messages.create(
            model=model,
            max_tokens=6500,
            system=TAILOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return _extract_json(response.content[0].text)
