# Maester

An AI hiring panel that searches live job listings, scores them against your
resume, and generates tailored, ATS-optimized applications — before you spend
hours on a listing that was never going to land.

## Why I built this

Job search advice says "tailor every resume." Nobody says how to know
*which* listings deserve that time. Maester simulates the actual panel that
reviews a candidate — a Hiring Manager, a Senior PM, an Engineering Lead, a
Design Lead, and a Recruiter, each with a different bar, each required to
reach an independent verdict rather than converge into generic praise — and
pairs it with the plumbing a real job search needs: live search, noise
filtering, legitimacy checks, and an honest, non-fabricated tailored
application when a listing is actually worth the time.

## How it works

**1. Search & Score** — Pulls live listings from six job board APIs
(Remotive, Greenhouse, Ashby, Gem, Lever, BambooHR) across a self-correcting
company registry. Every result gets a fast rubric score, a posting
legitimacy read, a compensation reliability read, and a seniority-aware
freshness rating, all before you open a single tab.

**2. Deep Dive** — On any listing worth a closer look, a full five-
perspective panel (Recruiter, Hiring Manager, Engineering Lead, Design Lead,
Senior PM) evaluates real fit against your actual resume and returns a
score, tier, gaps, resume fixes, and interview prep questions.

**3. Tailor & Export** — Generates a tailored, ATS-safe resume and cover
letter grounded in the panel's own findings, with a hard no-fabrication rule
enforced in code, not just prompted for.

**4. Auto-Fill Applications** — Opens the real application form in a visible
browser and fills in what it confidently knows from your resume and saved
profile facts, stopping short of submit every time — that boundary is
enforced in code, not just prompted for, with zero exceptions.

**5. Dashboard & notifications** — Every evaluation is logged locally,
newest first, for comparison at a glance, with optional email summaries sent
through your own SMTP account.

**6. Automatic fallback** — Optional secondary provider so a billing hiccup
mid-session doesn't stop your search.

## Stack

- **Streamlit** — UI
- **Anthropic API (Claude)** — tiered models for triage vs. deep evaluation
- **Remotive, Greenhouse, Ashby, Gem, Lever, BambooHR APIs** — live job search, no scraping
- **Playwright** — visible-browser application auto-fill
- **requests + BeautifulSoup** — fallback extraction for manually-pasted URLs
- **reportlab** — ATS-safe PDF rendering
- **smtplib** (standard library) — optional email summaries via your own SMTP
- **CSV** — zero-setup local storage, no database needed for an MVP

## Getting started

1. **Clone and install dependencies**
   ```bash
   git clone https://github.com/GabeTHEGeek/maester.git
   cd maester
   pip install -r requirements.txt
   ```
2. **Install the Playwright browser** (one-time, needed for Auto-Fill Applications)
   ```bash
   playwright install chromium
   ```
3. **Add your Anthropic API key** — either export it or paste it into the
   sidebar at runtime (never written to disk either way):
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```
   A DeepSeek key is optional but recommended as a fallback if Anthropic
   billing hiccups mid-session.
4. **Add your resume** — replace `sample_data/resume.md` with your own
   (gitignored, stays local — see "Your resume" below), or just paste it
   into the sidebar at runtime.
5. **Run the app**
   ```bash
   streamlit run app.py
   ```
6. **(Optional) Set up local-only extras** — a `.env` file in the project
   root can hold `LINKEDIN_URL`, `PORTFOLIO_URL`, `GITHUB_URL` (pre-fill the
   sidebar's link fields) and `DEEPSEEK_API_KEY`. `.env` is gitignored, never
   committed.

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
- No invented experience, employers, or metrics — enforced as a hard rule
- No auto-email unless you opt in
- No cloud storage — everything stays local except what you send to the
  Anthropic API (and, if you opt in, your own SMTP server)

## Roadmap

- [ ] SQLite instead of CSV once the tracker needs querying, not just viewing
- [ ] Cost tracking per session
- [ ] Cross-listing detection — flag the same role reposted by an agency
      under a different name

## License

MIT
