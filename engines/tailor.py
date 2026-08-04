"""
tailor.py
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

from role_profiles import DEFAULT_PROFILE_ID, RoleProfile, get_profile
from utils.extract import compute_current_role_tenure
from engines.llm_fallback import call_with_fallback, extract_json

TAILOR_MODEL = "claude-sonnet-4-5-20250929"

_TAILOR_SYSTEM_PROMPT_TEMPLATE = """You tailor a candidate's resume and draft a cover letter
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

__ARCHETYPE_BLOCK__

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
the summary/headline to foreground the detected archetype. The summary should
lead with the candidate's strongest concrete numbers already present in the
resume (retention/conversion percentages, dollar amounts, team size, scale)
rather than descriptive adjectives — "led a team that grew retention 27%"
beats "experienced leader focused on growth," using whatever specific figures
the source resume actually has. HARD LIMIT: the summary paragraph is 3
sentences maximum — compress by cutting words, not by removing the strongest
proof points; a tight 2-sentence summary beats a 3-sentence one padded to
fill the limit. Keep the same structure (same headers, same roles, same
companies, same dates) and the same overall length otherwise — this is a
reordering and rewording pass, not a rewrite.

BULLET QUALITY: when rewording a bullet, follow the shape Action + system/
scope + tool or approach + outcome + proof — "Resolved X in Y, improving Z,"
"Built X with Y, enabling Z," "Migrated X to Y, reducing Z," "Improved metric
from X to Y by Z" are the right shapes. Never open a bullet with a weak,
passive-sounding verb when the resume shows real ownership: banned openers
are "helped," "assisted," "responsible for," "worked on," "participated in" —
replace with the actual verb for what the candidate did (led, built, shipped,
designed, launched, owned, drove, cut, grew), never invented, always what the
source resume already supports.

SIX-SECOND CLARITY GATE: the top third of the tailored resume (name, tagline,
summary) has to make fit for THIS role impossible to miss within about six
seconds of reading. That means the summary and tagline together must cover:
the target role/archetype, the single strongest matching skill or domain,
one concrete production/business outcome (a real number from the resume),
and location/remote fit only if the JD's location terms make that relevant.
If a reader would have to hunt through bullets to figure out why this
candidate fits this specific role, the summary isn't doing its job — rewrite
it so the fit is stated, not implied.

LOGISTICS: if the JD states a specific location, remote policy, or work-
authorization requirement that the resume's own facts can speak to (e.g. the
candidate's stated location, willingness to relocate if that's in the source
resume), the summary or contact context is the right place to surface it —
but only using facts already present in the source resume, never invented or
assumed.

TENURE VS. MILESTONE TIMEFRAMES: a bullet may state how quickly a milestone
was hit early in a role (e.g., "achieved zero paid marketing spend in first
4 months"). That describes how fast something was accomplished, not how long
the candidate has held the role — always use the role's own stated date
range for tenure or experience length, never a milestone timeframe mentioned
inside a bullet. Do not reword a bullet in a way that would make this
ambiguous or imply the role itself only lasted that long.

Do NOT add a "Core Competencies," "Skills," or similarly named section to
tailored_resume_markdown itself, even though the resume may not have one.
Competencies are handled entirely through the separate core_competencies field
below and rendered as their own visual section by the document layout — adding
one into the markdown body as well produces a duplicate section in the final
document.

If the source resume's Summary section opens with a standalone one-line
title/headline (e.g. "Senior Product Manager | AI Products | Founder" as its
own line, separate from the descriptive paragraph below it), DROP that line
entirely from tailored_resume_markdown. The candidate_tagline field below
already renders as a headline above the Summary section — keeping a second,
near-duplicate headline line as the first line of the Summary content itself
produces two nearly identical lines stacked on top of each other in the final
document. The Summary section should start directly with the descriptive
paragraph.

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
  body (salutation through sign-off), and 3 sentences maximum per paragraph.
  This is a ceiling, not a target to fill — a tight, well-argued 200-word
  letter beats a 280-word one padded to hit the limit. All four content beats
  (opening hook, skills, experience, closing) still need to be present within
  that budget; compress by cutting words and combining beats into fewer
  paragraphs, not by dropping one entirely. Count your own sentences and
  words before finalizing — if any paragraph is over 3 sentences or the
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
  "results-oriented," "best practices" (name the actual practice instead),
  "holistic," "championed," "orchestrated" (unless literally describing
  multi-agent/system orchestration), "excited," "stakeholder alignment,"
  "data-driven" (say what the data actually drove instead), "actionable
  insights," "move the needle," "north star," "unique opportunity," "perfect
  fit," "strong track record," "I'm drawn to" (say specifically why instead:
  what problem, what detail, what fact — "drawn to" names a feeling without
  a reason attached to it), "delve," "harness," "unlock," "paradigm,"
  "showcasing," "crucial," "pivotal," "meticulously," "unparalleled,"
  "testament," "garner," "transformative," "empower," "streamline,"
  "elevate," "insightful," "disruptive," "unprecedented," "dynamic,"
  "game-changer," "groundbreaking," "foster," "enhance," "optimize,"
  "scalable," "breakthrough."
- NEGATIVE PARALLELISM BAN (hard rule): never negate a framing before
  asserting the real one. Banned patterns: "This isn't X, this is Y,"
  "It's not about X, it's about Y," "Not just X, but Y," "X is dead, Y is
  the future," "You don't need X, you need Y," or any sentence structured as
  reject-assumption-then-replace-it. This is one of the most reliable
  tells of AI-generated writing. If a draft sentence fits this shape, delete
  the negated half entirely and state the positive claim directly. "It's
  about the context" beats "It's not about the prompt, it's about the
  context" every time, the negated half adds zero information.
- COPULATIVE AVOIDANCE: don't dress up "is" or "has" as "serves as," "stands
  as," "represents," "marks a," "holds the distinction of being." Just say
  "is" or "has."
- Numbers as digits, not spelled out ("3 years," "10 partnerships," not
  "three years," "ten partnerships").
- Bold exactly ONE key moment in the letter, the single most compelling
  metric or proof point, not zero, not several. Everything else stays plain.
- SELF-CHECK before finalizing: read each sentence and ask "could this exact
  sentence appear in a cover letter for any other company, from any other
  candidate?" If yes, rewrite it to be specific to this resume and this JD.
  A sentence that survives this check unchanged is a sentence that isn't
  doing its job.

CONTENT: after the salutation, open with a concrete parallel between one of
the candidate's own AI projects (from the AI Projects section of the resume:
Karla, Rudy, Brand Companion Agent, Maester, or a project explicitly mentioned
in additional context below) and what this specific role would have them
build. Proof, not a claim. Only do this if a genuine, honest parallel exists;
if none of the candidate's projects meaningfully connects to this role, open
with the strongest resume-grounded hook instead, ideally the single most
relevant metric from the resume, stated plainly and early rather than saved
for later.

IF THE ROLE IS GENUINELY AI-FORWARD (the detected archetype is AI-native, or
the JD itself emphasizes LLM/agent/AI product work as a core part of the
job, not just a passing mention): lean into Maester specifically. It's the
candidate's strongest, most differentiated proof point for exactly this kind
of role, an actual shipped multi-agent system with real reliability
engineering behind it, not a claimed skill. For a genuinely AI-forward role,
this should be the opening parallel by default, not just a candidate for it,
and it's also fair game as one of the 2-3 experience stories below, not only
the opening line. For roles that are NOT genuinely AI-forward, stay
conservative as before: only reach for it if the parallel is real, and don't
force it in just to feature it.

For the experience paragraph(s), pick 2-3 stories using the underlying shape
of Situation, Task, Action, Result, and a real Metric (STAR-M) even though the
letter shouldn't be literally labeled that way. These can be drawn from either
the resume's work Experience section OR, for a genuinely AI-forward role,
Maester itself (the keyword-overlap-vs-real-fit reliability story, the
multi-provider fallback work, or the panel's disagreement-by-design
architecture are all real, specific stories, not just a project description).
Quantify wherever the resume already has a number; don't describe a project
in vague terms when the resume states a concrete result. Then make the "why
them, why you" connection explicit: name a specific requirement or problem
from the JD and state directly how the resume evidence answers it, not just
parallel accomplishments listed side by side with no stated connection.

Respond ONLY with valid JSON, no markdown fences, no prose outside the JSON:
{
  "candidate_name": "<parsed from the resume header, exactly as written>",
  "candidate_tagline": "<short role/focus line — derived from the resume's own summary/headline, optionally leaning toward the detected archetype, never inventing a title the candidate doesn't hold>",
  "detected_archetype": "<one of the archetypes above, or a hybrid>",
  "tailored_resume_markdown": "<the full revised resume in Markdown>",
  "core_competencies": ["<phrase 1>", "<phrase 2>", "..."],
  "cover_letter": "<the full cover letter text, body only, no header/links/signature-block links>",
  "keywords_emphasized": ["<keyword 1>", "<keyword 2>", "..."],
  "changes_summary": ["<one-line description of change 1>", "<change 2>", "..."]
}
"""


def _build_system_prompt(role_profile: RoleProfile) -> str:
    """Everything here is shared candidate context (hard no-fabrication
    rules, this candidate's real AI positioning, bullet/format/cover-letter
    rules) except the ARCHETYPE DETECTION section, which is supplied by the
    active role_profiles.RoleProfile - see role_profiles/base.py for why
    the archetype list and its foregrounding guidance are role-specific
    while everything else about the candidate stays fixed."""
    return _TAILOR_SYSTEM_PROMPT_TEMPLATE.replace(
        "__ARCHETYPE_BLOCK__", role_profile.tailor_archetype_block
    )


def generate_tailored_materials(
    resume_text: str,
    job_text: str,
    company: str,
    role_title: str,
    top_gaps: list,
    resume_fixes: list,
    api_key: str,
    model: str = TAILOR_MODEL,
    deepseek_api_key: str = "",
    role_profile: RoleProfile = None,
) -> dict:
    """Returns {"candidate_name": str, "candidate_tagline": str,
    "detected_archetype": str, "tailored_resume_markdown": str,
    "core_competencies": list, "cover_letter": str,
    "keywords_emphasized": list, "changes_summary": list}.
    Links (LinkedIn/portfolio/GitHub) are intentionally NOT handled here —
    they're rendered directly into the PDF header by pdf_export.py, not
    written into the letter body by the model. `role_profile` selects
    which role_profiles.RoleProfile's archetypes classify the listing -
    defaults to Product Manager for callers that don't pass one explicitly."""
    role_profile = role_profile or get_profile(DEFAULT_PROFILE_ID)
    system_prompt = _build_system_prompt(role_profile)
    tenure_note = compute_current_role_tenure(resume_text)
    tenure_block = f"\nVERIFIED FACT: {tenure_note}\n" if tenure_note else ""

    user_prompt = f"""RESUME (Markdown, source of truth — do not invent beyond this):
{resume_text}
{tenure_block}
JOB LISTING:
Company: {company}
Role: {role_title}
{job_text}

HIRING PANEL'S FINDINGS (use these to guide what to emphasize, not what to invent):
Top gaps identified: {"; ".join(top_gaps) if top_gaps else "none noted"}
Suggested resume fixes: {"; ".join(resume_fixes) if resume_fixes else "none noted"}
"""

    text, _provider = call_with_fallback(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        anthropic_api_key=api_key,
        anthropic_model=model,
        max_tokens=6000,
        deepseek_api_key=deepseek_api_key,
    )

    try:
        data = extract_json(text)
    except (ValueError, json.JSONDecodeError):
        # Same truncation safety net as the deep-dive panel.
        text, _provider = call_with_fallback(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            anthropic_api_key=api_key,
            anthropic_model=model,
            max_tokens=10000,
            deepseek_api_key=deepseek_api_key,
        )
        data = extract_json(text)

    if "tailored_resume_markdown" in data:
        data["tailored_resume_markdown"] = _strip_duplicate_competencies_section(
            data["tailored_resume_markdown"]
        )
        data["tailored_resume_markdown"] = _strip_duplicate_summary_headline(
            data["tailored_resume_markdown"]
        )
        data["tailored_resume_markdown"] = _enforce_summary_sentence_limit(
            data["tailored_resume_markdown"], max_sentences=3
        )

    if "cover_letter" in data:
        data["cover_letter"] = _strip_em_dashes(data["cover_letter"])
        word_count = len(data["cover_letter"].split())
        over_sentence_limit = any(
            _count_sentences(p) > 3 for p in data["cover_letter"].split("\n\n") if p.strip()
        )
        if word_count > 300 or over_sentence_limit:
            data["cover_letter"] = _condense_cover_letter(
                data["cover_letter"], api_key, model, deepseek_api_key
            )
            data["cover_letter"] = _strip_em_dashes(data["cover_letter"])

        banned_phrase = _find_banned_phrase(data["cover_letter"])
        if banned_phrase:
            data["cover_letter"] = _fix_banned_phrase(
                data["cover_letter"], banned_phrase, api_key, model, deepseek_api_key
            )
            data["cover_letter"] = _strip_em_dashes(data["cover_letter"])

    return data


# Phrases the prompt already explicitly bans but has been observed slipping
# through anyway ("I'm drawn to" specifically was reported in real use). This
# list stays intentionally short — full-sentence phrases the prompt calls out
# by name as weak, not every word in the larger banned-vocabulary list, since
# most of those are single words unlikely to need a dedicated rewrite pass.
_BANNED_PHRASES_NEEDING_REWRITE = [
    "i'm drawn to",
    "i am drawn to",
]


def _find_banned_phrase(text: str) -> str:
    lower_text = text.lower()
    for phrase in _BANNED_PHRASES_NEEDING_REWRITE:
        if phrase in lower_text:
            return phrase
    return ""


def _fix_banned_phrase(cover_letter: str, phrase: str, api_key: str, model: str, deepseek_api_key: str = "") -> str:
    """Backstop for phrases the prompt already bans by name but that have
    been observed slipping through anyway — same lesson as the em-dash and
    word-limit backstops: a prompt instruction is a request, not a
    guarantee. Unlike em dashes, this isn't a clean character-level swap —
    deleting "I'm drawn to" outright leaves a broken sentence fragment — so
    this asks for a real rewrite of just the offending sentence rather than
    mechanical text surgery."""
    fix_prompt = f"""This cover letter contains the phrase "{phrase}," which names a feeling
without giving a concrete reason attached to it — exactly the kind of AI-sounding
filler this letter should never use. Rewrite ONLY the sentence(s) containing that
phrase so they state a specific, concrete reason instead (a real detail about the
role, the company, or a resume-grounded parallel), removing the phrase entirely.
Leave every other sentence in the letter completely unchanged. Keep every
formatting rule from before: zero em dashes, no invented metrics.

LETTER:
{cover_letter}

Respond with ONLY the full corrected letter text, no JSON, no commentary, no markdown fences."""

    text, _provider = call_with_fallback(
        system_prompt="",
        user_prompt=fix_prompt,
        anthropic_api_key=api_key,
        anthropic_model=model,
        max_tokens=1200,
        deepseek_api_key=deepseek_api_key,
    )
    return text.strip()


_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?]+(?=\s|$)")


def _count_sentences(text: str) -> int:
    """Rough sentence count via terminal punctuation — same level of
    heuristic as the existing word-count check (won't perfectly handle
    abbreviations like 'U.S.' or 'Inc.', but good enough for a backstop,
    not a grammar parser)."""
    return len(_SENTENCE_BOUNDARY_RE.findall(text.strip()))


def _enforce_summary_sentence_limit(markdown_text: str, max_sentences: int = 3) -> str:
    """Hard backstop: the prompt instructs a 3-sentence-max Summary paragraph,
    but that's a request, not a guarantee. Finds the Summary section's real
    narrative paragraph (skipping a standalone pipe-delimited headline line,
    if one slipped through) and truncates it to the first N sentences rather
    than trusting the model to have counted correctly. Deterministic
    truncation, not a follow-up API call — a short summary paragraph is safe
    to trim mechanically without an extra round-trip."""
    match = re.search(r"##\s*Summary\s*\n+(.*?)(?=\n##\s|\Z)", markdown_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return markdown_text

    section_text = match.group(1)
    paragraphs = [p for p in section_text.split("\n\n") if p.strip()]

    for i, para in enumerate(paragraphs):
        stripped = para.strip()
        looks_like_headline = "|" in stripped and len(stripped) < 140 and "\n" not in stripped
        if looks_like_headline:
            continue
        if _count_sentences(stripped) > max_sentences:
            sentences = _SENTENCE_BOUNDARY_RE.split(stripped)
            boundaries = _SENTENCE_BOUNDARY_RE.findall(stripped)
            trimmed = "".join(
                s + b for s, b in zip(sentences[:max_sentences], boundaries[:max_sentences])
            ).strip()
            paragraphs[i] = trimmed
        break  # only the first substantive paragraph is the narrative summary

    new_section_text = "\n\n".join(paragraphs) + "\n"
    return markdown_text[: match.start(1)] + new_section_text + markdown_text[match.end(1):]


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


_SUMMARY_HEADLINE_RE = re.compile(
    r"(##\s*Summary)\s*\n+[ \t]*([^\n]{1,140}\|[^\n]{1,140})\s*\n+",
    re.IGNORECASE,
)


def _strip_duplicate_summary_headline(markdown_text: str) -> str:
    """Hard backstop: the prompt instructs the model to drop a standalone
    pipe-delimited title line from the top of the Summary section (since
    candidate_tagline already renders as a headline right above it), but
    that's a request, not a guarantee — this strips one if it slips through,
    so the resume never shows two near-identical headlines stacked on top
    of each other."""
    def repl(match):
        return f"{match.group(1)}\n\n"
    return _SUMMARY_HEADLINE_RE.sub(repl, markdown_text, count=1)


def _condense_cover_letter(cover_letter: str, api_key: str, model: str, deepseek_api_key: str = "") -> str:
    """Word-limit enforcement backstop: the prompt asks for a 280-word, 3
    paragraph ceiling, but that's a request, not a guarantee. If the model
    still comes back over, ask it to condense rather than trust the first
    pass — cheaper and more reliable than truncating text programmatically,
    which risks cutting a sentence mid-thought."""
    condense_prompt = f"""This cover letter is over the word limit. Condense it to 280 words maximum,
3 paragraphs maximum, 3 sentences maximum per paragraph, without losing any of
its actual content beats (opening hook, skills, experience, closing) or
resume-grounded specifics. Cut words and combine ideas into fewer paragraphs —
do not drop a beat entirely. Keep every formatting rule from before: opens
with "Dear Hiring Manager,", zero em dashes, no invented metrics beyond what's
already here, sign off with the name only.

LETTER TO CONDENSE:
{cover_letter}

Respond with ONLY the condensed letter text, no JSON, no commentary, no markdown fences."""

    text, _provider = call_with_fallback(
        system_prompt="",
        user_prompt=condense_prompt,
        anthropic_api_key=api_key,
        anthropic_model=model,
        max_tokens=1200,
        deepseek_api_key=deepseek_api_key,
    )
    return text.strip()


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
