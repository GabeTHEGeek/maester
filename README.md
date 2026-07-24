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
generates a Core Competencies tag section pulled from what's actually in your
resume. Hard rule, enforced in the prompt and backed by code-level checks, not
just instructions: never invents experience, employers, dates, or metrics not
already in your resume.

The resume PDF has a centered header with hyperlinked LinkedIn/portfolio/
GitHub links (whichever you've filled in the sidebar), employment dates
right-aligned against each role the way most resume templates do it, and
11pt body text throughout.

The cover letter opens with a real project parallel when one genuinely
exists, always opens with "Dear Hiring Manager," and is capped hard: 3
paragraphs, 4 sentences per paragraph, 280 words total, zero em dashes
anywhere. If a first draft comes back over the word limit, the app
automatically asks the model to condense it rather than trusting the first
pass. The letterhead includes your name, a short role tagline, today's date,
and the same hyperlinked links as the resume; it signs off with "Best
regards," and your name, no footer, no links repeated in the body.

Both render to clean, single-column, ATS-safe PDFs (region-aware — Letter for
US/Canada, A4 elsewhere).

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

## Running on a schedule

The Streamlit app is interactive, but the search/dedup/scoring pipeline
underneath it can run headless via `scheduled_scan.py`, the same modules,
just without a UI. It reads which queries to run from `scan_config.json`,
skips anything already in your scan history, and — only if you've set SMTP
credentials — emails you a digest, but only when something actually clears
your grade threshold. A routine run that finds nothing new sends nothing.

```bash
cp .env.example .env    # fill in your real API key and (optional) SMTP creds
python scheduled_scan.py
```

Edit `scan_config.json` to change what it searches for:
```json
{
  "queries": ["AI product manager", "technical product manager AI"],
  "sources": ["remotive", "greenhouse", "ashby"],
  "min_grade": "B",
  "results_per_query": 15
}
```

**To actually run it on a schedule** (macOS/Linux, via cron):
```bash
crontab -e
```
Add a line like this to run it every morning at 8am (adjust paths to match your setup):
```
0 8 * * * cd /path/to/maester && /path/to/maester/venv/bin/python scheduled_scan.py >> scan.log 2>&1
```
Cron runs with a minimal environment, so credentials need to come from `.env`
(loaded automatically via `python-dotenv`) rather than variables you've only
exported in your regular shell.

On Windows, use Task Scheduler with the same command, pointed at your venv's
`python.exe`.

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
- No auto-email unless you opt in — the app only sends if you enable
  auto-send or click "send now"; the scheduled script only sends if you've
  set SMTP credentials in `.env` and only when a listing actually clears your
  grade threshold
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

