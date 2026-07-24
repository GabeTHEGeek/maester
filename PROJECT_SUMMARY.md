# Maester — Project Summary

## What it is

Maester is a job-search tool that searches live job listings across three
sources, deduplicates against every prior search, scores every result against
a resume on a weighted rubric, and runs a simulated five-perspective hiring
panel on any listing worth a closer look — then, if it's genuinely worth
applying to, generates a tailored, ATS-optimized resume and cover letter
grounded in what the panel found.

It's built as a **workflow**, not an autonomous agent: a fixed pipeline of
deterministic steps (search → dedup → score → optional deep-dive → optional
tailor & export), each doing real LLM reasoning inside the step, but with the
control flow — what runs, in what order, how many times — decided by code,
not by the model. That's a deliberate architecture choice, not a limitation
(more on this below).

## What it actually does

1. **Search** — pulls live listings from three sources: Remotive (broad job
   board, full-text matched), Greenhouse, and Ashby (both direct per-company
   boards, title-matched, no full-text noise). Companies to check live in a
   user-editable, self-correcting registry: entries start as "unverified"
   guesses and automatically flip to "verified" (or get flagged as wrong)
   based on what a real search actually finds — this is how a wrong guess
   about which platform a given company uses gets caught and corrected
   instead of silently staying wrong.
2. **Dedup** — every listing that's already been scanned in a past search
   gets skipped, not re-scored; a local scan history means the same posting
   showing up under a different query doesn't burn another API call.
3. **Filter** — a title allowlist/blocklist stops these sources' biggest
   failure mode: search APIs matching on any word appearing anywhere in a job
   description, which otherwise returns things like "Accounts Payable
   Assistant" on a "product manager" search.
4. **Quick score** — every new result gets a fast, cheap rubric pass (Haiku)
   across role/skills match, seniority fit, domain relevance, and location
   feasibility, explicitly instructed not to confuse keyword overlap with
   actual fit (a title sharing buzzwords with the resume isn't evidence of a
   match), plus a fast Posting Legitimacy and Compensation Reliability read.
5. **Deep dive** — on demand, a full five-perspective panel (Sonnet) —
   Hiring Manager, Senior PM, Engineering Lead, Design Lead, Recruiter — each
   reaches an independent verdict, citing specific sections of the resume
   (which is structured Markdown for exactly this reason), and the panel is
   required to surface disagreement rather than converge into generic praise,
   plus panel-level Posting Legitimacy and Compensation Reliability checks.
6. **Tailor & Export** — for anything worth applying to, generates a tailored
   resume (reordered/reworded bullets, detected PM archetype, Core
   Competencies tags) and a cover letter (280-word/3-paragraph hard cap, zero
   em dashes, no fabricated metrics, opens with a real project parallel when
   one exists), rendered to clean, ATS-safe, region-aware PDFs.
7. **Salary/location extraction** — pulled from structured fields where
   available, regex-extracted from the full job text otherwise (fixed a bug
   where truncating the description *before* extracting was silently
   dropping comp info that appeared late in longer postings).
8. **Dashboard** — every deep-dive evaluation is logged locally (CSV,
   auto-migrating schema so past data never silently corrupts on an update),
   with clickable links back to the original listing, plus optional email
   summaries via the user's own SMTP account.

## Why it's a workflow, not an agent

This matters as a technical distinction, not just semantics. A workflow is
predictable, auditable, and cheap — the right choice when the task shape is
known in advance, which job search is. An agent (LLM decides what happens
next, loops via something like the ReAct pattern — thought → tool call →
observation → repeat) earns its complexity when the task genuinely can't be
predicted ahead of time. Maester doesn't need the model deciding whether to
search again or which tool to call next; it needs deterministic, repeatable
scoring you can trust and audit. Knowing when *not* to reach for agent
architecture is itself a real design decision worth being able to explain.

## Timeline (what actually got built, in order)

- MVP: search + rubric score + panel deep-dive + local tracker
- Fixed title filtering twice (missed "Product Engineer" titles, then fixed
  hyphen/spacing variants like "Full-Stack" vs "fullstack")
- Added a positive title allowlist after discovering Remotive's search
  matches full description text, not just titles (a "product" search was
  returning Patient Care Specialist and Accounts Payable roles)
- Added automatic query broadening when an exact seniority phrase ("Principal
  Product Manager") returns zero results
- Added clickable listing URLs throughout
- Made Remotive's category filter a soft fallback instead of a hard filter,
  after discovering Remotive's own category tagging is unreliable
- Added Greenhouse as a second source with per-board provenance tracking
- Added auto-migrating tracker schema (a stale CSV from an earlier version
  was crashing the dashboard with invalid JSON/NaN)
- Added salary + location extraction, then fixed a truncation-order bug that
  was silently dropping comp info appearing late in longer job descriptions
- Added Posting Legitimacy and Compensation Reliability assessments, modeled
  on the open-source career-ops project's published methodology
- Reformatted the resume as structured Markdown so the panel can cite
  specific sections instead of vague generalities
- Fixed a quick-score calibration bug where keyword overlap with the resume
  (shared buzzwords like "Agentic AI") was inflating scores independent of
  actual fit
- Fixed a token-budget bug causing occasional truncated/invalid JSON from the
  deep-dive panel after the schema grew
- Added Ashby as a third source, same per-board pattern as Greenhouse
- Fixed a real board-assignment error (Mercury was on the wrong platform in
  the seed data) — the kind of mistake that motivated the next item
- Replaced hardcoded company lists with a user-editable, self-correcting
  registry that verifies its own platform guesses against real search results
- Added deduplication (skip re-scoring listings already seen) and
  parallelized Greenhouse/Ashby board fetching, both pulled from a published
  retrospective on a similar open-source tool
- Fixed a job-page-scraping bug where application forms (especially EEO/
  demographic dropdowns) were eating the character budget before the real
  job description — and later removed an unverified CSS-selector guess that
  risked silently cutting off content, in favor of the simpler, proven fix
- Built Tailor & Export: archetype detection, keyword placement rules,
  region-aware PDF rendering, and a hard no-fabrication rule for tailored
  resumes and cover letters
- Added optional email summaries via the user's own SMTP account
- Fixed a resume-header centering bug (contact line was silently falling
  through to left-aligned body text due to a state-tracking bug), added
  hyperlinked LinkedIn/portfolio/GitHub, and added a Core Competencies tag
  section — then fixed a duplicate-rendering bug where the model was adding
  its own copy of that section directly into the resume body
- Enforced zero em dashes and a 280-word/3-paragraph cap on cover letters
  with code-level backstops (a compression retry, an automatic dash-stripper)
  rather than trusting prompt instructions alone, after both limits were
  initially violated despite being explicitly instructed

---

## How to talk about it to employers

### The 30-second version

"I built a tool that searches live job postings across three sources, scores
them against my resume, and runs a simulated hiring panel — five different
perspectives, each grounded in specific resume evidence — on anything worth a
closer look. For roles that clear the bar, it generates a tailored resume and
cover letter, with a hard rule against ever fabricating experience or metrics.
It's a deliberate workflow architecture, not an agent, because job scoring
needs to be deterministic and auditable, not something the model freelances
on."

### If they ask "is it agentic?"

Be precise, don't oversell. "It's a workflow — the pipeline order is fixed in
code, the LLM reasons inside each step but doesn't control what happens next.
I know exactly what it'd take to make it a true agent — expose the
search/score/deep-dive functions as MCP tools, wrap them in a ReAct loop so
the model decides when to broaden a search or which listings to dig into —
and I chose not to, because deterministic scoring is the right call for this
use case." This answer signals you understand the distinction most people
blur, which is a stronger signal than claiming "agentic" and not being able
to defend it under a follow-up question.

### Technical depth to have ready

- **Two-tier model routing**: cheap/fast model (Haiku) for the wide first
  pass across many listings, expensive/careful model (Sonnet) only on demand
  for the handful worth a real look. This is a cost/quality tradeoff decision
  you made deliberately, not a default.
- **The keyword-overlap bug and fix**: a real, concrete story about catching
  and fixing an AI reliability failure — the quick scorer was rating a
  listing 4.8/5 based on surface buzzword overlap with the resume, while the
  deeper panel correctly caught that the role's actual substance was a
  mismatch. This is a genuinely good story about the gap between shallow
  pattern-matching and real reasoning in agentic systems — directly relevant
  to any AI product role.
- **The truncation-order bug**: extracting data from a fixed text window
  before deciding what to keep vs. after are different bugs with the same
  symptom (missing salary) — a small, concrete example of debugging
  discipline.
- **Schema evolution without data loss**: the tracker auto-detects when its
  own CSV schema has drifted from a code update and archives the old file
  rather than silently corrupting it. Small detail, but signals you think
  about production failure modes, not just the happy path.

### Honest limitations (say these before they ask)

- It's an MVP built over roughly two weeks of iteration, not a production
  system — no authentication, no persistent database, single-user.
- Coverage gaps: Remotive, Greenhouse, and Ashby only, so companies on Lever
  or a fully custom career site aren't covered yet.
- The quick-score rubric is a triage tool, not a verdict — it's explicitly
  designed to be fast and cheap, with real judgment deferred to the deep-dive
  panel.
- Some guardrails (zero em dashes, word-count caps) needed a code-level
  backstop in addition to a prompt instruction, because the prompt alone
  wasn't consistently followed — worth being upfront about rather than
  claiming prompting alone solved it.

### The narrative thread to Structured specifically

The whole build mirrors the same shape as their own product — agents doing
useful work across multiple stages (their Curate → Calculate stages; here,
Search → Score → Deep Dive), with governance and trust layers (Posting
Legitimacy, Comp Reliability) built in rather than bolted on. That's an
Outcomes Manager conversation, not a "look what I built" conversation: you're
demonstrating you think about the risk and trust surface of agentic systems
before someone has to ask you to.
