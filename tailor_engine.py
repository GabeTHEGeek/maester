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

Do NOT add a "Core Competencies," "Skills," or similarly named section to
tailored_resume_markdown itself, even though the resume may not have one.
Competencies are handled entirely through the separate core_competencies field
below and rendered as their own visual section by the document layout — adding
one into the markdown body as well produces a duplicate section in the final
document.

Also produce CORE COMPETENCIES: 6-9 short phrases (2-4 words each, e.g.
"Agentic Workflow Design," "0-to-1 Marketplace Building") pulled from what's
actually in the resume, chosen for relevance to this specific listing and the
detected archetype. These render as visual skill tags on the resume, so they
must be terse and scannable, not full sentences, and every one must be
honestly backed by something in the resume — this is a different surface for
the same no-invention rule, not an exception to it.

TASK 2 — Cover letter. Write it the way a genuinely strong candidate would
actually talk about their own work, not the way a template fills in blanks.
Hiring managers reading this want to understand judgment and communication,
not just a list of accomplishments — the letter should read as one person's
reasoning, start to finish, not four interchangeable paragraphs.

STRUCTURE (as a flow, not rigid labeled sections):
- Introduction: open with genuine, specific interest in this company and
  role, tied to something real (their mission, their product, a problem
  they're visibly solving) — not a generic "I'm excited to apply."
- Relevant skills: name 2-3 skills that actually matter for this role, each
  anchored to a real outcome, not a bare adjective.
- Experience: 2-3 specific experiences from the resume that show measurable
  impact, collaboration, or real problem-solving — chosen for what this
  listing cares about, not a chronological recap of the whole resume.
  Never just restate resume bullets verbatim; tell the story behind one or
  two of them instead.
- Closing: reaffirm interest concretely (reference something specific about
  the role again, don't just repeat "I'm excited") and suggest a next step
  with confidence, not a passive "hope to hear from you."

AVOID, specifically:
- Generic language that could apply to any company or any candidate
- Spending more words on background/credentials than on impact and outcomes
- Buzzwords without a concrete example attached ("results-driven," "team
  player," "go-getter" — if you can't point to the resume line proving it,
  cut it)
- Restating resume bullets near-verbatim instead of narrating the story
  behind one or two of them
- Padding length — this should read like someone respecting the reader's
  time, not filling a page. If a sentence could be deleted without losing
  meaning or proof, delete it. No throat-clearing, no restating what the
  next sentence is about to say, no closing paragraph that just repeats the
  opening in different words.
- A weak or overly formal sign-off ("I look forward to hearing from you" as
  the entire closing thought is too passive — say what happens next)
- Dwelling on or over-explaining employment gaps or transitions if any exist
  in the resume — mention context briefly if truly relevant, don't justify at
  length
- Any sentence that would look identical in someone else's cover letter
- Any number, percentage, dollar figure, or metric not stated verbatim in
  the source resume. Never estimate, round, extrapolate, or "reasonably
  infer" a number to make a sentence sound more impressive. If a story
  doesn't have a resume-backed number, tell it without one rather than
  inventing one.

FORMAT RULES (non-negotiable):
- Always open with the literal line "Dear Hiring Manager," as its own line,
  even if a hiring manager's name appears elsewhere in context — do not
  guess at or invent a name to personalize the salutation.
- ZERO em dashes anywhere in the letter — not "at most one," none. Use a
  period, comma, semicolon, or colon instead every time you're tempted to
  reach for one. Check your own output for the — character before finalizing
  and rewrite any sentence that has one.
- HARD LIMIT: 3 paragraphs maximum, 280 words maximum for the entire letter
  body (salutation through sign-off), and 4 sentences maximum per paragraph.
  This is a ceiling, not a target to fill — a tight, well-argued 200-word
  letter beats a 280-word one padded to hit the limit. All four content beats
  (opening hook, skills, experience, closing) still need to be present within
  that budget; compress by cutting words and combining beats into fewer
  paragraphs, not by dropping one entirely. Count your own sentences and
  words before finalizing — if any paragraph is over 4 sentences or the
  total is over 280 words, cut until it isn't.
- Sign off with the candidate's name only — do NOT include links in the
  letter body or signature; those are rendered separately in the document
  header.
- Vary sentence length and structure. Do not open consecutive sentences with
  the same word or structure. Professional and human, not AI-generated
  sounding: avoid "passionate about," "proven track record," "synergies,"
  "leverage" (say "use" or name the tool), "spearheaded" (say "led"),
  "facilitated" (say "ran" or "set up"), "robust," "seamless," "cutting-edge,"
  "innovative," "in today's fast-paced world," "demonstrated ability to,"
  "results-oriented," "best practices" (name the actual practice instead).

CONTENT: after the salutation, open with a concrete parallel between one of
the candidate's own AI projects (from the AI Projects section of the resume:
Karla, Rudy, Brand Companion Agent, Maester, or a project explicitly mentioned
in additional context below) and what this specific role would have them
build. Proof, not a claim. Only do this if a genuine, honest parallel exists;
if none of the candidate's projects meaningfully connects to this role, open
with the strongest resume-grounded hook instead, ideally the single most
relevant metric from the resume, stated plainly and early rather than saved
for later.

For the experience paragraph(s), pick 2-3 stories using the underlying shape
of Situation, Task, Action, Result, and a real Metric (STAR-M) even though the
letter shouldn't be literally labeled that way. Quantify wherever the resume
already has a number; don't describe a project in vague terms when the resume
states a concrete result. Then make the "why them, why you" connection
explicit: name a specific requirement or problem from the JD and state
directly how the resume evidence answers it, not just parallel accomplishments
listed side by side with no stated connection.

Respond ONLY with valid JSON, no markdown fences, no prose outside the JSON:
{
  "candidate_name": "<parsed from the resume header, exactly as written>",
  "candidate_tagline": "<short role/focus line, e.g. 'Senior Product Manager | AI Product Builder' — derived from the resume's own summary/headline, optionally leaning toward the detected archetype, never inventing a title the candidate doesn't hold>",
  "detected_archetype": "<one of the archetypes above, or a hybrid>",
  "tailored_resume_markdown": "<the full revised resume in Markdown>",
  "core_competencies": ["<phrase 1>", "<phrase 2>", "..."],
  "cover_letter": "<the full cover letter text, body only, no header/links/signature-block links>",
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
    model: str = TAILOR_MODEL,
) -> dict:
    """Returns {"candidate_name": str, "candidate_tagline": str,
    "detected_archetype": str, "tailored_resume_markdown": str,
    "core_competencies": list, "cover_letter": str,
    "keywords_emphasized": list, "changes_summary": list}.
    Links (LinkedIn/portfolio/GitHub) are intentionally NOT handled here —
    they're rendered directly into the PDF header by pdf_export.py, not
    written into the letter body by the model."""
    client = anthropic.Anthropic(api_key=api_key)

    user_prompt = f"""RESUME (Markdown, source of truth — do not invent beyond this):
{resume_text}

JOB LISTING:
Company: {company}
Role: {role_title}
{job_text}

HIRING PANEL'S FINDINGS (use these to guide what to emphasize, not what to invent):
Top gaps identified: {"; ".join(top_gaps) if top_gaps else "none noted"}
Suggested resume fixes: {"; ".join(resume_fixes) if resume_fixes else "none noted"}
"""

    response = client.messages.create(
        model=model,
        max_tokens=4500,
        system=TAILOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = response.content[0].text
    try:
        data = _extract_json(text)
    except (ValueError, json.JSONDecodeError):
        # Same truncation safety net as the deep-dive panel.
        response = client.messages.create(
            model=model,
            max_tokens=6500,
            system=TAILOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        data = _extract_json(response.content[0].text)

    if "tailored_resume_markdown" in data:
        data["tailored_resume_markdown"] = _strip_duplicate_competencies_section(
            data["tailored_resume_markdown"]
        )

    if "cover_letter" in data:
        data["cover_letter"] = _strip_em_dashes(data["cover_letter"])
        word_count = len(data["cover_letter"].split())
        if word_count > 300:
            data["cover_letter"] = _condense_cover_letter(data["cover_letter"], client, model)
            data["cover_letter"] = _strip_em_dashes(data["cover_letter"])

    return data


_COMPETENCY_SECTION_RE = re.compile(
    r"\n##\s*(core competencies|competencies|skills)\s*\n.*?(?=\n##\s|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _strip_duplicate_competencies_section(markdown_text: str) -> str:
    """Hard backstop: the prompt instructs the model not to add its own
    Core Competencies/Skills section to the resume body (competencies are
    handled entirely via the separate core_competencies field and rendered
    as pills), but a model instruction is not a guarantee — this removes
    one if it slips through, so it never renders twice."""
    return _COMPETENCY_SECTION_RE.sub("", "\n" + markdown_text).strip()


def _condense_cover_letter(cover_letter: str, client: "anthropic.Anthropic", model: str) -> str:
    """Word-limit enforcement backstop: the prompt asks for a 280-word, 3
    paragraph ceiling, but that's a request, not a guarantee. If the model
    still comes back over, ask it to condense rather than trust the first
    pass — cheaper and more reliable than truncating text programmatically,
    which risks cutting a sentence mid-thought."""
    condense_prompt = f"""This cover letter is over the word limit. Condense it to 280 words maximum,
3 paragraphs maximum, 4 sentences maximum per paragraph, without losing any of
its actual content beats (opening hook, skills, experience, closing) or
resume-grounded specifics. Cut words and combine ideas into fewer paragraphs —
do not drop a beat entirely. Keep every formatting rule from before: opens
with "Dear Hiring Manager,", zero em dashes, no invented metrics beyond what's
already here, sign off with the name only.

LETTER TO CONDENSE:
{cover_letter}

Respond with ONLY the condensed letter text, no JSON, no commentary, no markdown fences."""

    response = client.messages.create(
        model=model,
        max_tokens=1200,
        messages=[{"role": "user", "content": condense_prompt}],
    )
    return response.content[0].text.strip()


def _strip_em_dashes(text: str) -> str:
    """Hard backstop: the prompt instructs zero em dashes, but a model
    instruction is not a guarantee. Replaces any that slip through with a
    comma, which is the closest single-character substitute for how em
    dashes are typically used in this kind of writing (a soft parenthetical
    pause), then cleans up any resulting double punctuation/spacing."""
    text = text.replace(" — ", ", ").replace("—", ", ")
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r",\s*\.", ".", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text
