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
freshness rating, all before you open a single tab. Each score shows which
provider actually answered, how long it took, and an estimated cost, with a
one-click force-rescan if you want a fresh read instead of the cached one. A
"score a listing by URL" box lets you paste any listing directly, resolving
it through the same accurate per-platform APIs (not a generic scrape) and
registering it into the company registry — including Greenhouse or Ashby
boards embedded on a company's own careers domain (e.g. a `?gh_jid=` or
`?ashby_jid=` URL), which are resolved straight to the real board API
instead of scraping the client-rendered embed shell.

**2. Role profiles** — A sidebar dropdown switches the entire lens Maester
searches and judges through: title filters, rubric framing, the deep-dive
panel's five personas, and tailoring archetypes all swap together. Ships
with Product Manager, Customer Success, Account Executive, Chief of Staff,
and Software Engineer — each with real title include/exclude filters and a
rubric gate written to judge transferable substance honestly, not just
penalize a missing formal title.

**3. Deep Dive** — On any listing worth a closer look, a full five-
perspective panel (personas depend on the active role profile — e.g.
Recruiter, Hiring Manager, Engineering Lead, Design Lead, Senior PM for
Product Manager) evaluates real fit against your actual resume and returns
a score, tier, gaps, resume fixes, and interview prep questions.

**4. Tailor & Export** — Generates a tailored, ATS-safe resume and cover
letter grounded in the panel's own findings, with a hard no-fabrication rule
enforced in code, not just prompted for. Em dashes and AI-sounding filler
phrases ("I'm drawn to," and more) are stripped and rewritten as a code-level
backstop, not just a prompt instruction, across both the cover letter and
drafted application-question answers.

**5. Auto-Fill Applications** — Opens the real application form in a visible
browser and fills in what it confidently knows from your resume and saved
profile facts, stopping short of submit every time — that boundary is
enforced in code, not just prompted for, with zero exceptions. Profile facts
(work authorization, visa needs, EEO/demographic answers) and a reusable
answer bank for common application questions are both editable from the
in-app **Setup** tab — no manual JSON editing required.

**6. Batch** — Check off multiple listings on Search & Score, then run Deep
Dive, Tailor & Export, and Auto-Fill on all of them together from the
**Batch** tab instead of one at a time. Deep Dive runs concurrently across
the selection; each listing still opens as its own browser tab for Auto-Fill
and still stops short of submit — batching changes how many listings you
process per click, not what the app is willing to do unsupervised.

**7. Tracking** — A manually-maintained application pipeline
(Saved/Applied/Interviewing/Offer/Rejected/Withdrawn), deliberately separate
from the auto-populated Dashboard. Includes a funnel chart, status
breakdown, an "applied by day" chart for outreach-goal tracking, and
conversion-rate metrics (response rate, interview rate, offer rate,
rejection rate) computed off everyone who ever reached "Applied" or
further.

**8. Dashboard & notifications** — Every evaluation is logged locally,
newest first, for comparison at a glance, with optional email summaries sent
through your own SMTP account.

**9. Automatic fallback** — Three-tier provider chain (Anthropic → DeepSeek
→ Groq, free) so a billing hiccup or timeout mid-session doesn't stop your
search; a sidebar dropdown lets you pick which tier goes first, the other
two follow automatically. Groq's fallback tier runs at a lower, tested
temperature than the other two — a real consistency check found the
default setting produced flip-flopping grades run-to-run on that specific
model, and locking it down to 0 fixed it without needing to touch the
other providers, which were already reliable.

## Stack

- **Streamlit** — UI
- **Anthropic API (Claude)** — tiered models for triage vs. deep evaluation,
  primary provider with DeepSeek and Groq as automatic fallbacks
- **Remotive, Greenhouse, Ashby, Gem, Lever, BambooHR APIs** — live job search, no scraping
- **Playwright** — visible-browser application auto-fill
- **Plotly** — Tracking tab funnel, status, and time-series charts
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
   A DeepSeek key and/or a free Groq key are optional but recommended as
   fallbacks if Anthropic billing hiccups mid-session — either can also be
   set as the primary provider from the sidebar dropdown.
4. **Add your resume** — replace `sample_data/resume.md` with your own
   (gitignored, stays local — see "Your resume" below), or just paste it
   into the sidebar at runtime.
5. **Run the app**
   ```bash
   streamlit run app.py
   ```
6. **Fill in your Setup tab** — the app opens with a warning banner if
   you're still on the fictional example resume/profile/answer bank. The
   **Setup** tab has a checklist plus in-app editors for your profile facts
   (work authorization, visa needs, EEO/demographic answers) and answer
   bank (reusable answers to common application questions) — no manual JSON
   editing needed, everything saves straight to `sample_data/` locally. Both
   only matter for Auto-Fill Applications; Search & Score, Deep Dive, and
   Tailor & Export only need your resume.
7. **(Optional) Set up local-only extras** — a `.env` file in the project
   root can hold `LINKEDIN_URL`, `PORTFOLIO_URL`, `GITHUB_URL` (pre-fill the
   sidebar's link fields), `DEEPSEEK_API_KEY`, and `GROQ_API_KEY`. `.env` is
   gitignored, never committed.

## Your resume, profile, and answer bank

`sample_data/resume.md`, `sample_data/profile.json`, and
`sample_data/answer_bank.json` are all gitignored on purpose — they're meant
to hold your real, personal data and are never committed. Fictional
placeholders (`resume.example.md`, `profile.example.json`,
`answer_bank.example.json`) ship in the repo so the app has a working
default out of the box, and the sidebar shows a warning banner whenever
you're still running on one of them. To use your own: paste your resume
into the sidebar at runtime or replace `resume.md` locally, and use the
**Setup** tab to fill in your profile facts and answer bank (no manual
JSON editing needed). If you fork this repo, double-check
`git ls-files | grep -E "resume|profile|answer_bank"` only shows the
`.example.*` files before you push.

## What this deliberately doesn't do

- No auto-apply — every application is your call, nothing gets submitted
- No invented experience, employers, or metrics — enforced as a hard rule
- No auto-email unless you opt in
- No cloud storage — everything stays local except what you send to the
  Anthropic API, the optional DeepSeek/Groq fallbacks, and (if you opt in)
  your own SMTP server

## Roadmap

- [ ] SQLite instead of CSV once the tracker needs querying, not just viewing
- [ ] Cost tracking per session
- [ ] Cross-listing detection — flag the same role reposted by an agency
      under a different name

## License

MIT
