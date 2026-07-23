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

**1. Search & Score** — pulls live listings from three sources: Remotive (broad
job board), Greenhouse, and Ashby (both direct per-company boards —
configurable list of companies for each, fetched in parallel so checking a
dozen companies doesn't mean waiting on a dozen sequential API calls). A title
allowlist/blocklist filters out the noise these APIs are prone to (a "product
manager" search returning "Accounts Payable Assistant" because the word
"product" appears somewhere in the description). Every listing you've already
scanned in a past search gets skipped, not re-scored, a local scan history
tracks every URL that's already been through the rubric, and reuses that
result instead of burning another API call on something you already have an
answer for. New listings get a fast, cheap rubric score (Haiku) plus a
Posting Legitimacy read (does this look like a real, active opening) and a
Compensation Reliability read (does the advertised number look like real base
pay or inflated OTE), with salary and location extracted wherever the source
states them.

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
or metrics not already in your resume. The cover letter always opens with
"Dear Hiring Manager," caps em dash use at one per letter, avoids AI-sounding
stock phrases ("leverage," "proven track record," "results-oriented," etc.),
and includes your portfolio/GitHub links in the signature if you've entered
them in the sidebar. Renders to clean, single-column, ATS-safe PDFs
(region-aware — Letter for US/Canada, A4 elsewhere).

**4. Email notifications** — optional. Enter your own email and an app
password (Gmail requires an App Password, not your regular one) in the
sidebar, and either click "Email me this summary" on any Deep Dive result or
turn on auto-send for every run. Sent via your own SMTP account; nothing goes
out unless you explicitly enable it.

**5. Dashboard** — every deep-dive is logged to a local CSV tracker, with the
schema auto-migrating (old file archived, not corrupted) if a future update
changes what's tracked.

## Stack

- **Streamlit** — UI
- **Anthropic API (Claude)** — Haiku for the fast triage pass, Sonnet for the
  deep-dive panel and tailoring
- **Remotive + Greenhouse + Ashby APIs** — live job search, no scraping
- **requests + BeautifulSoup** — fallback JD extraction for pasted URLs
- **reportlab** — ATS-safe PDF rendering (single-column, standard fonts, no
  tables/images that trip parsers)
- **smtplib** (standard library) — optional email summaries via your own SMTP
  account
- **CSV** — zero-setup local tracker, no database needed for an MVP

## Run it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
streamlit run app.py
```

Or paste your API key directly into the sidebar at runtime — it's never
written to disk.

## Your resume

`sample_data/resume.md` is gitignored on purpose — it's meant to hold your
real resume and is never committed. A fictional placeholder,
`sample_data/resume.example.md`, ships in the repo so the app has a working
default out of the box. To use your own: either paste it into the sidebar at
runtime, or replace `sample_data/resume.md` locally (it'll stay untracked).
If you fork this repo, double-check `git ls-files | grep resume` only shows
`resume.example.md` before you push.

## What this deliberately doesn't do

- No auto-apply — every application is your call, nothing gets submitted
- No invented experience, employers, or metrics — the tailoring prompt is
  built around this as a hard rule, not a suggestion
- No auto-email by default — summary emails only send if you explicitly
  enable auto-send or click "send now"
- No cloud storage — the tracker and scan history are both local CSVs;
  nothing leaves your machine except what you send to the Anthropic API (and,
  if you opt in, your own SMTP server for email summaries)

## Roadmap

- [ ] Lever as a fourth job source, for companies not on Remotive/Greenhouse/Ashby
- [ ] SQLite instead of CSV once the tracker needs querying, not just viewing
- [ ] Posting liveness check (flag closed/stale listings before scoring them)
- [ ] Cost tracking per session (rough token spend estimate)

## License

MIT

