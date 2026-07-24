"""
Maester — an agent that searches live job listings, scores every result
against your resume on a weighted rubric, ranks them, and runs a full
5-perspective hiring panel deep-dive on whichever ones you click into.

Run: streamlit run app.py
"""

import os
import re
import tempfile

import streamlit as st

import job_source
import job_source_ashby
import job_source_greenhouse
from company_registry import add_company, load_registry, record_discovery, save_registry, tokens_for_platform
from dedup import load_seen_urls, record_scans
from email_notify import build_deep_dive_summary, send_summary_email
from extract import extract_salary
from fetch_job import fetch_job_text
from job_source import search_jobs
from panel_engine import run_panel
from pdf_export import render_cover_letter_pdf, render_resume_pdf
from rubric_engine import batch_score, quick_score_from_cache
from tailor_engine import generate_tailored_materials
from tracker import load_all, log_result

st.set_page_config(page_title="Maester", page_icon="\U0001F56F", layout="wide")

# resume.md is gitignored — it's your real personal resume, kept local-only.
# resume.example.md is tracked and ships in the repo — a fictional resume so
# the app has a working default for anyone else who clones this project
# without exposing anyone's real name, contact info, or employment history.
DEFAULT_RESUME_PATH = os.path.join(os.path.dirname(__file__), "sample_data", "resume.md")
EXAMPLE_RESUME_PATH = os.path.join(os.path.dirname(__file__), "sample_data", "resume.example.md")


def load_default_resume() -> str:
    path = DEFAULT_RESUME_PATH if os.path.exists(DEFAULT_RESUME_PATH) else EXAMPLE_RESUME_PATH
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return ""


if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "jobs_by_id" not in st.session_state:
    st.session_state.jobs_by_id = {}
if "deep_dive_job" not in st.session_state:
    st.session_state.deep_dive_job = None

st.title("\U0001F56F Maester")
st.caption(
    "An agent that searches live job listings, scores every result against your resume "
    "on a weighted rubric, and ranks them, so you know which ones are worth your time "
    "before you write a single word of a tailored application."
)

with st.sidebar:
    st.header("Setup")
    api_key = st.text_input(
        "Anthropic API key",
        type="password",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="Get one at console.anthropic.com. Never stored, only used for this session.",
    )
    st.divider()
    st.subheader("Resume")
    resume_source = st.radio("Resume source", ["Use default", "Paste my own"], index=0)
    if resume_source == "Paste my own":
        resume_text = st.text_area("Paste resume text", height=300)
    else:
        resume_text = load_default_resume()
        st.text_area("Preview", value=resume_text, height=200, disabled=True)

    st.divider()
    st.subheader("Links (optional)")
    st.caption("Included as hyperlinks in the header of both the tailored resume and cover letter, when provided.")
    linkedin_url = st.text_input("LinkedIn URL", value="")
    portfolio_url = st.text_input("Portfolio URL", value="")
    github_url = st.text_input("GitHub URL", value="")

    st.divider()
    with st.expander("Email notifications (optional)"):
        st.caption(
            "Sends via your own SMTP account. For Gmail, use an App Password, "
            "not your regular password (Google Account → Security → App passwords). "
            "Nothing is sent unless you enable auto-send below or click 'Send now'."
        )
        smtp_email = st.text_input("Your email address", value="", key="smtp_email")
        smtp_password = st.text_input("App password", value="", type="password", key="smtp_password")
        recipient_email = st.text_input(
            "Send summary to", value="", placeholder="defaults to your email above", key="recipient_email"
        )
        col_srv, col_port = st.columns([2, 1])
        with col_srv:
            smtp_server = st.text_input("SMTP server", value="smtp.gmail.com", key="smtp_server")
        with col_port:
            smtp_port = st.number_input("Port", value=587, key="smtp_port")
        auto_email = st.checkbox("Automatically email me a summary after each Deep Dive run", value=False)

tab_search, tab_deep_dive, tab_dashboard = st.tabs(
    ["Search & Score", "Deep Dive", "Dashboard"]
)

# ---------------------------------------------------------------------------
# TAB 1: Search & Score — the agentic loop. Query -> live listings -> ranked scores.
# ---------------------------------------------------------------------------
with tab_search:
    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input(
            "Search live job listings for...",
            placeholder="e.g. AI product manager",
        )
    with col2:
        limit = st.number_input("Max results", min_value=5, max_value=30, value=15)

    with st.expander("Search filters"):
        sources = st.multiselect(
            "Search sources",
            options=["Remotive", "Greenhouse", "Ashby"],
            default=["Remotive", "Greenhouse", "Ashby"],
            help="Remotive is a broad job board (full-text matched). Greenhouse and Ashby pull directly from specific companies' own job boards (title-matched, no full-text noise).",
        )
        if "company_registry" not in st.session_state:
            st.session_state.company_registry = load_registry()
        registry_rows = st.session_state.company_registry

        gh_registry_tokens = tokens_for_platform(registry_rows, "greenhouse")
        ab_registry_tokens = tokens_for_platform(registry_rows, "ashby")

        greenhouse_boards = st.multiselect(
            "Greenhouse companies to check",
            options=gh_registry_tokens,
            default=gh_registry_tokens,
            help="Includes companies marked 'unknown' platform too — those get tried here and on Ashby, and the registry below records whichever one actually works.",
        )
        ashby_boards = st.multiselect(
            "Ashby companies to check",
            options=ab_registry_tokens,
            default=ab_registry_tokens,
            help="Includes companies marked 'unknown' platform too — those get tried here and on Greenhouse, and the registry below records whichever one actually works.",
        )

        with st.expander("Manage companies (add, edit, verify)"):
            st.caption(
                "Edit directly — add a row, fix a wrong platform, or add notes. "
                "'verified' means confirmed by a real search hit; 'unverified' is a guess; "
                "'unknown' platform gets tried on both Greenhouse and Ashby until discovered."
            )
            edited_rows = st.data_editor(
                registry_rows,
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "platform": st.column_config.SelectboxColumn(
                        options=["greenhouse", "ashby", "unknown"]
                    ),
                    "status": st.column_config.SelectboxColumn(
                        options=["verified", "unverified", "failed"]
                    ),
                },
                key="company_editor",
            )
            if st.button("Save company changes"):
                st.session_state.company_registry = edited_rows
                save_registry(edited_rows)
                st.success("Saved. Re-open this panel's dropdowns above to see new companies.")
                st.rerun()

        category = st.selectbox(
            "Remotive category",
            options=["product", "project-management", "all-others", None],
            format_func=lambda c: "All categories" if c is None else c,
            index=0,
            help="Remotive's own category tag. 'product' filters out most engineering-only boards up front.",
        )
        exclude_engineering = st.checkbox(
            "Exclude hands-on engineering titles (Software Engineer, Architect, DevOps, etc.)",
            value=True,
            help="Drops listings whose title signals a hands-on IC engineering role, even if 'product' or 'AI' also appears in the title.",
        )
        require_pm_title = st.checkbox(
            "Require a PM-shaped title (Product Manager, Product Owner, Head of Product, etc.)",
            value=True,
            help="Remotive matches your search against the full job description, not just the title, so a generic query can return unrelated roles that just happen to mention 'product' somewhere. This requires the title itself to look like a PM role.",
        )

    if st.button("Search & score", type="primary"):
        if not api_key:
            st.error("Add your Anthropic API key in the sidebar first.")
        elif not resume_text.strip():
            st.error("Add a resume first.")
        elif not query.strip():
            st.error("Enter a search term.")
        elif not sources:
            st.error("Pick at least one search source.")
        else:
            jobs = []
            search_meta = {}
            gh_meta = {}
            ab_meta = {}

            if "Remotive" in sources:
                with st.spinner(f"Searching Remotive for '{query}'..."):
                    try:
                        rt_jobs, search_meta = search_jobs(
                            query,
                            limit=int(limit),
                            category=category,
                            exclude_titles=job_source.DEFAULT_TITLE_EXCLUDE if exclude_engineering else [],
                            require_title_keywords=job_source.DEFAULT_TITLE_INCLUDE if require_pm_title else None,
                        )
                        jobs.extend(rt_jobs)
                    except Exception as e:
                        st.error(f"Remotive search failed: {e}")

            if "Greenhouse" in sources:
                with st.spinner(f"Checking {len(greenhouse_boards)} Greenhouse boards for '{query}'..."):
                    try:
                        gh_jobs, gh_meta = job_source_greenhouse.search_greenhouse(
                            query,
                            boards=greenhouse_boards,
                            limit=int(limit),
                            exclude_titles=job_source.DEFAULT_TITLE_EXCLUDE if exclude_engineering else None,
                            require_title_keywords=job_source.DEFAULT_TITLE_INCLUDE if require_pm_title else None,
                        )
                        jobs.extend(gh_jobs)
                        if gh_meta.get("boards_failed"):
                            st.caption(
                                f"Greenhouse boards that returned nothing (dead token or no matches): "
                                f"{', '.join(gh_meta['boards_failed'])}"
                            )
                    except Exception as e:
                        st.error(f"Greenhouse search failed: {e}")

            if "Ashby" in sources:
                with st.spinner(f"Checking {len(ashby_boards)} Ashby boards for '{query}'..."):
                    try:
                        ab_jobs, ab_meta = job_source_ashby.search_ashby(
                            query,
                            boards=ashby_boards,
                            limit=int(limit),
                            exclude_titles=job_source.DEFAULT_TITLE_EXCLUDE if exclude_engineering else None,
                            require_title_keywords=job_source.DEFAULT_TITLE_INCLUDE if require_pm_title else None,
                        )
                        jobs.extend(ab_jobs)
                        if ab_meta.get("boards_failed"):
                            st.caption(
                                f"Ashby boards that returned nothing (dead token or no matches): "
                                f"{', '.join(ab_meta['boards_failed'])}"
                            )
                    except Exception as e:
                        st.error(f"Ashby search failed: {e}")

            # Self-correcting registry: whatever actually worked (or didn't)
            # on this search gets recorded, so unverified guesses turn into
            # verified facts, or wrong guesses get flagged, without you
            # having to manually check.
            if gh_meta or ab_meta:
                for token in gh_meta.get("boards_checked", []):
                    registry_rows = record_discovery(registry_rows, token, "greenhouse", found=True)
                for token in gh_meta.get("boards_failed", []):
                    registry_rows = record_discovery(registry_rows, token, "greenhouse", found=False)
                for token in ab_meta.get("boards_checked", []):
                    registry_rows = record_discovery(registry_rows, token, "ashby", found=True)
                for token in ab_meta.get("boards_failed", []):
                    registry_rows = record_discovery(registry_rows, token, "ashby", found=False)
                st.session_state.company_registry = registry_rows
                save_registry(registry_rows)

            if search_meta.get("broadened"):
                note = f"No Remotive listings matched \"{search_meta['original_query']}\" with the current filters, so I broadened that search"
                changes = []
                if search_meta.get("used_query", "").lower() != search_meta.get("original_query", "").lower():
                    changes.append(f"query to \"{search_meta['used_query']}\"")
                if search_meta.get("used_category") is None and category is not None:
                    changes.append("dropped the category restriction")
                if changes:
                    note += " — " + ", ".join(changes) + "."
                note += " The panel deep-dive still judges seniority fit on its own."
                st.info(note)

            if not jobs:
                st.warning("No listings found across the selected sources. Try a broader term or more boards.")
            else:
                st.session_state.jobs_by_id = {str(j.get("id", j["url"])): j for j in jobs}

                seen = load_seen_urls()
                new_jobs = [j for j in jobs if j.get("url") not in seen]
                cached_jobs = [j for j in jobs if j.get("url") in seen]

                results = [
                    quick_score_from_cache(seen[j["url"]], str(j.get("id", j["url"])))
                    for j in cached_jobs
                ]

                if new_jobs:
                    with st.spinner(f"Scoring {len(new_jobs)} new listings against your resume..."):
                        try:
                            new_results = batch_score(resume_text, new_jobs, api_key)
                            results.extend(new_results)
                            record_scans(new_results)
                        except Exception as e:
                            st.error(f"Scoring failed: {e}")

                results.sort(key=lambda r: r.score, reverse=True)
                st.session_state.search_results = results

                if cached_jobs:
                    st.caption(
                        f"Skipped re-scoring {len(cached_jobs)} listing(s) already seen in a previous "
                        f"search — reused the cached score instead of another API call."
                    )

    if st.session_state.search_results:
        st.markdown(f"### {len(st.session_state.search_results)} listings ranked")
        st.caption(
            "These are a fast first-pass triage, not a verdict — titles can be misleading "
            "(a 'Product Manager' title sometimes describes a hands-on engineering role). "
            "Always run Deep Dive before trusting a high score."
        )
        for r in st.session_state.search_results:
            grade_color = {
                "A": "green",
                "B": "blue",
                "C": "orange",
                "D": "red",
                "F": "red",
            }.get(r.grade, "gray")
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
                with c1:
                    if r.source == "greenhouse":
                        source_label = f"Greenhouse · {r.board}"
                    elif r.source == "ashby":
                        source_label = f"Ashby · {r.board}"
                    else:
                        source_label = "Remotive"
                    meta_bits = [source_label]
                    if r.location:
                        meta_bits.append(r.location)
                    if r.salary:
                        comp_suffix = f" (reliability: {r.comp_reliability})" if r.comp_reliability else ""
                        meta_bits.append(f"{r.salary}{comp_suffix}")
                    st.markdown(f"**{r.title}** — {r.company}")
                    st.caption(f"{r.reason}  \n:gray[{' · '.join(meta_bits)}]")
                    if r.legitimacy_tier and r.legitimacy_tier != "High Confidence":
                        legit_color = "red" if r.legitimacy_tier == "Suspicious" else "orange"
                        st.caption(f":{legit_color}[⚠ {r.legitimacy_tier}] — {r.legitimacy_note}")
                with c2:
                    st.markdown(f":{grade_color}[**{r.grade}**]  {r.score:.1f}/5.0")
                with c3:
                    st.link_button("Open ↗", r.url, use_container_width=True)
                with c4:
                    if st.button("Deep dive", key=f"dive_{r.job_id}", use_container_width=True):
                        st.session_state.deep_dive_job = st.session_state.jobs_by_id.get(r.job_id)
                        st.rerun()

# ---------------------------------------------------------------------------
# TAB 2: Deep Dive — full 5-panelist evaluation on a selected listing.
# ---------------------------------------------------------------------------
with tab_deep_dive:
    job = st.session_state.deep_dive_job

    st.markdown("Run the full panel on a listing you picked from search results, or paste one directly.")
    manual_url = st.text_input("...or paste a job URL directly", key="manual_url")

    target_job = None
    if job:
        st.info(f"Selected from search: **{job['title']}** at **{job['company']}**")
        st.link_button("Open listing ↗", job["url"])
        target_job = job
    elif manual_url:
        target_job = {"title": "", "company": "", "url": manual_url, "description": ""}

    if st.button("Run full panel", type="primary"):
        if not api_key:
            st.error("Add your Anthropic API key in the sidebar first.")
        elif not resume_text.strip():
            st.error("Add a resume first.")
        elif not target_job:
            st.error("Pick a listing from Search & Score, or paste a URL.")
        else:
            with st.spinner("Fetching listing and convening the panel..."):
                try:
                    if target_job.get("description"):
                        job_text = target_job["description"]
                    else:
                        job_text = fetch_job_text(target_job["url"])

                    # Manually pasted URLs never go through job_source's extraction,
                    # so always try extracting from the actual text we're about to
                    # hand the panel, and only fall back to whatever the search result
                    # already had if that fails.
                    salary = extract_salary(job_text) or target_job.get("salary", "")

                    # Some ATSes (Greenhouse in particular) render the salary line via
                    # their own compliance template rather than the employer-authored
                    # description the API returns, so it can be genuinely absent from
                    # a cached search result's description even though it's visible on
                    # the live page. If we still don't have a salary and this came from
                    # a search result (not a fresh fetch already), try the live page once.
                    if not salary and target_job.get("url") and target_job.get("description"):
                        try:
                            live_text = fetch_job_text(target_job["url"])
                            salary = extract_salary(live_text)
                        except Exception:
                            pass

                    result = run_panel(
                        resume_text=resume_text,
                        job_text=job_text,
                        company=target_job.get("company") or "Unknown",
                        role_title=target_job.get("title") or "Unknown role",
                        api_key=api_key,
                        job_url=target_job.get("url", ""),
                        source=target_job.get("source", "unknown"),
                        board=target_job.get("board", "unknown"),
                        location=target_job.get("location", ""),
                        salary=salary,
                    )
                    log_result(result)
                    # Persisted so the tailoring button below survives the rerun
                    # it triggers, independent of when the panel was actually run.
                    st.session_state.deep_dive_result = result
                    st.session_state.deep_dive_job_text = job_text
                    st.session_state.tailored_materials = None

                    if auto_email and smtp_email and smtp_password:
                        try:
                            send_summary_email(
                                smtp_email=smtp_email,
                                smtp_password=smtp_password,
                                recipient=recipient_email or smtp_email,
                                subject=f"Maester: {result.role_title} at {result.company} — {result.fit_score}/100",
                                body=build_deep_dive_summary(result),
                                smtp_server=smtp_server,
                                smtp_port=int(smtp_port),
                            )
                            st.success("Summary emailed.")
                        except Exception as e:
                            st.warning(f"Deep dive completed, but the email failed to send: {e}")
                except Exception as e:
                    st.error(f"Something went wrong: {e}")

    result = st.session_state.get("deep_dive_result")

    if result:
        tier_color = {
            "Strong fit": "green",
            "Competitive": "blue",
            "Stretch": "orange",
            "Poor fit": "red",
        }.get(result.tier, "gray")

        st.markdown(f"## Fit score: {result.fit_score}/100 — :{tier_color}[{result.tier}]")
        st.write(result.tier_reason)
        meta_bits = []
        if result.location:
            meta_bits.append(f"📍 {result.location}")
        if result.salary:
            meta_bits.append(f"💰 {result.salary}")
        if meta_bits:
            st.caption(" · ".join(meta_bits))
        col_open, col_email = st.columns([1, 1])
        with col_open:
            if result.job_url:
                st.link_button("Open listing ↗", result.job_url)
        with col_email:
            if st.button("Email me this summary"):
                if not smtp_email or not smtp_password:
                    st.error("Add your email and app password in the sidebar first.")
                else:
                    try:
                        send_summary_email(
                            smtp_email=smtp_email,
                            smtp_password=smtp_password,
                            recipient=recipient_email or smtp_email,
                            subject=f"Maester: {result.role_title} at {result.company} — {result.fit_score}/100",
                            body=build_deep_dive_summary(result),
                            smtp_server=smtp_server,
                            smtp_port=int(smtp_port),
                        )
                        st.success("Sent.")
                    except Exception as e:
                        st.error(f"Email failed to send: {e}")

        st.markdown("### Panel verdicts")
        for p in result.panelists:
            with st.expander(f"{p['role']} — lean: {p['lean']}"):
                st.write(p["verdict"])

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("### Where the panel agrees")
            st.write(result.agreement)
        with col_b:
            st.markdown("### Sharpest disagreement")
            st.write(result.sharpest_disagreement)

        st.markdown("### Top gaps")
        for gap in result.top_gaps:
            st.write(f"- {gap}")

        st.markdown(f"### Recommendation: {result.recommendation}")

        st.markdown("### Highest-leverage resume fixes")
        for fix in result.resume_fixes:
            st.write(f"- {fix}")

        st.markdown("### Interview questions to prep for")
        for q in result.interview_questions:
            st.write(f"- {q}")

        st.divider()
        legit_color = {
            "High Confidence": "green",
            "Proceed with Caution": "orange",
            "Suspicious": "red",
        }.get(result.legitimacy_tier, "gray")
        col_leg, col_comp = st.columns(2)
        with col_leg:
            st.markdown(f"### Posting legitimacy: :{legit_color}[{result.legitimacy_tier or 'Unknown'}]")
            st.caption(result.legitimacy_notes)
        with col_comp:
            st.markdown(f"### Comp reliability: {result.comp_reliability or 'Unknown'}")
            st.caption(f"{result.company_type} — {result.comp_notes}" if result.company_type else result.comp_notes)

        st.divider()
        st.markdown("### Tailor & export")
        st.caption(
            "Reorders and rewords your existing resume bullets for this listing, weaving in the "
            "JD's own terminology where it's honestly applicable — never invents experience, "
            "employers, or metrics that aren't already in your resume."
        )

        if st.button("Generate tailored resume + cover letter"):
            with st.spinner("Tailoring resume and drafting cover letter..."):
                try:
                    materials = generate_tailored_materials(
                        resume_text=resume_text,
                        job_text=st.session_state.get("deep_dive_job_text", result.raw_job_text),
                        company=result.company,
                        role_title=result.role_title,
                        top_gaps=result.top_gaps,
                        resume_fixes=result.resume_fixes,
                        api_key=api_key,
                    )
                    st.session_state.tailored_materials = materials
                except Exception as e:
                    st.error(f"Tailoring failed: {e}")

        materials = st.session_state.get("tailored_materials")
        if materials:
            if materials.get("detected_archetype"):
                st.caption(f"Detected archetype: **{materials['detected_archetype']}**")
            st.markdown("#### What changed")
            for change in materials.get("changes_summary", []):
                st.write(f"- {change}")
            if materials.get("keywords_emphasized"):
                st.caption("Keywords emphasized: " + ", ".join(materials["keywords_emphasized"]))
            if materials.get("core_competencies"):
                st.caption("Core competencies (rendered as tags on the resume): " + " · ".join(materials["core_competencies"]))

            with st.expander("Preview tailored resume (Markdown)"):
                st.markdown(materials["tailored_resume_markdown"])
            with st.expander("Preview cover letter"):
                word_count = len(materials["cover_letter"].split())
                if word_count > 280:
                    st.warning(f"{word_count} words — over the 280-word target. Consider regenerating.")
                else:
                    st.caption(f"{word_count} words")
                st.write(materials["cover_letter"])

            if st.button("Render PDFs"):
                with st.spinner("Rendering PDFs..."):
                    try:
                        safe_company = re.sub(r"[^\w\-]+", "_", result.company or "company")
                        resume_pdf_path = os.path.join(
                            tempfile.gettempdir(), f"resume_{safe_company}.pdf"
                        )
                        cover_pdf_path = os.path.join(
                            tempfile.gettempdir(), f"cover_letter_{safe_company}.pdf"
                        )
                        render_resume_pdf(
                            materials["tailored_resume_markdown"],
                            resume_pdf_path,
                            location=result.location,
                            linkedin_url=linkedin_url,
                            portfolio_url=portfolio_url,
                            github_url=github_url,
                            core_competencies=materials.get("core_competencies", []),
                        )
                        render_cover_letter_pdf(
                            materials["cover_letter"],
                            cover_pdf_path,
                            location=result.location,
                            candidate_name=materials.get("candidate_name", ""),
                            candidate_tagline=materials.get("candidate_tagline", ""),
                            linkedin_url=linkedin_url,
                            portfolio_url=portfolio_url,
                            github_url=github_url,
                        )

                        with open(resume_pdf_path, "rb") as f:
                            st.download_button(
                                "Download tailored resume (PDF)",
                                f.read(),
                                file_name=f"resume_{safe_company}.pdf",
                                mime="application/pdf",
                            )
                        with open(cover_pdf_path, "rb") as f:
                            st.download_button(
                                "Download cover letter (PDF)",
                                f.read(),
                                file_name=f"cover_letter_{safe_company}.pdf",
                                mime="application/pdf",
                            )
                    except Exception as e:
                        st.error(f"PDF rendering failed: {e}")

# ---------------------------------------------------------------------------
# TAB 3: Dashboard — everything you've deep-dived on, logged locally.
# ---------------------------------------------------------------------------
with tab_dashboard:
    st.subheader("All deep-dive evaluations")
    rows = load_all()
    if not rows:
        st.info("No deep-dive evaluations logged yet.")
    else:
        rows_sorted = sorted(rows, key=lambda r: int(r.get("fit_score") or 0), reverse=True)
        st.dataframe(
            rows_sorted,
            use_container_width=True,
            column_config={
                "url": st.column_config.LinkColumn("Listing", display_text="Open ↗")
            },
        )
