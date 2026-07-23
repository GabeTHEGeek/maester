# Maester

An AI hiring panel that searches live job listings, scores them against your
resume, and generates tailored, ATS-optimized applications — before you spend
hours on a listing that was never going to land.

## Why I built this

Job search advice usually says "tailor every resume." Nobody says how to know
*which* listings deserve that time. Maester simulates the actual panel that
reviews a candidate — a Hiring Manager, a Senior PM, an Engineering Lead, a
Design Lead, and a Recruiter, each with a different bar and each allowed to
disagree — and pairs it with the unglamorous plumbing real job search needs:
searching live boards, filtering out noise, flagging sketchy postings, and
generating an honest, non-fabricated tailored application when a listing is
actually worth it.

It's not a chatbot wrapper. Each panelist is prompted with a distinct
evaluation lens and is required to surface disagreement rather than converge
into generic praise. Every deep-dive is logged locally so you can compare your
pipeline at a glance.

## How it works

**1. Search & Score** — pulls live listings from two sources: Remotive (broad
job board) and Greenhouse (direct per-company boards — configurable list of
companies). A title allowlist/blocklist filters out the noise both APIs are
prone to (a "product manager" search returning "Accounts Payable Assistant"
because the word "product" appears somewhere in the description). Every result
gets a fast, cheap rubric score (Haiku) plus a Posting Legitimacy read (does
this look like a real, active opening) and a Compensation Reliability read
(does the advertised number look like real base pay or inflated OTE), with
salary and location extracted wherever the source states them.

**2. Deep Dive** — on any listing worth a closer look, a full five-perspective
panel (Sonnet) runs, citing specific sections of your resume, and returns a
fit score, tier, recommendation, top gaps, resume fixes, interview questions
to prep for, and the same legitimacy/comp checks at panel-level depth.

**3. Tailor & Export** — generates a tailored resume and cover letter grounded
in the panel's own findings: reorders and rewords your existing bullets,
detects which of six PM archetypes the role fits and foregrounds the matching
experience, weaves in the JD's own terminology where honestly applicable, and
opens the cover letter with a real project parallel when one genuinely exists.
Hard rule, enforced in the prompt: never invents experience, employers, dates,
or metrics not already in your resume. Renders to clean, single-column,
ATS-safe PDFs (region-aware — Letter for US/Canada, A4 elsewhere).

**4. Dashboard** — every deep-dive is logged to a local CSV tracker, with the
schema auto-migrating (old file archived, not corrupted) if a future update
changes what's tracked.

## Stack

- **Streamlit** — UI
- **Anthropic API (Claude)** — Haiku for the fast triage pass, Sonnet for the
  deep-dive panel and tailoring
- **Remotive + Greenhouse APIs** — live job search, no scraping
- **requests + BeautifulSoup** — fallback JD extraction for pasted URLs
- **reportlab** — ATS-safe PDF rendering (single-column, standard fonts, no
  tables/images that trip parsers)
- **CSV** — zero-setup local tracker, no database needed for an MVP

## Run it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
streamlit run app.py
```

Or paste your API key directly into the sidebar at runtime — it's never
written to disk.

## What this deliberately doesn't do

- No auto-apply — every application is your call, nothing gets submitted
- No invented experience, employers, or metrics — the tailoring prompt is
  built around this as a hard rule, not a suggestion
- No cloud storage — the tracker is a local CSV; nothing leaves your machine
  except what you send to the Anthropic API

## Roadmap

- [ ] Additional job sources (Lever, Ashby) for companies not on
      Remotive/Greenhouse
- [ ] SQLite instead of CSV once the tracker needs querying, not just viewing
- [ ] Posting liveness check (flag closed/stale listings before scoring them)
- [ ] Cost tracking per session (rough token spend estimate)

## License

MIT

