"""
Maester — an agent that searches live job listings, scores every result
against your resume on a weighted rubric, ranks them, and runs a full
5-perspective hiring panel deep-dive on whichever ones you click into.

Run: streamlit run app.py
"""

import os
import re
import tempfile

from dotenv import load_dotenv
import streamlit as st

load_dotenv()

import sources.ashby as job_source_ashby
import sources.bamboohr as job_source_bamboohr
import sources.gem as job_source_gem
import sources.greenhouse as job_source_greenhouse
import sources.lever as job_source_lever
from data.company_registry import load_registry, mark_failed_all, record_discovery, save_registry, tokens_for_platform
from utils.resolve import resolve_cross_platform
from data.dedup import load_seen_urls, record_scans
from utils.email_notify import build_deep_dive_summary, send_summary_email
from utils.extract import extract_salary, format_published_date, parse_company_and_source_from_url, parse_contact_info
from utils.freshness import compute_freshness
from utils.fetch_job import check_liveness, fetch_job_page, fetch_job_text
from sources.remotive import search_jobs
from engines.panel import run_panel
from utils.pdf_export import render_cover_letter_pdf, render_resume_pdf
from engines.rubric import batch_score, quick_score_from_cache
from engines.tailor import generate_tailored_materials
from data.tracker import load_all, log_result
from browser.autofill import open_and_fill
from data.fill_log import log_fill_attempt
from role_profiles import get_profile, list_profiles

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


# Platform -> that source's own search_* function, reused to fetch a single
# pasted listing's real data (title/description/location/salary) instead of
# a generic page scrape. This matters specifically because Gem's job DETAIL
# pages are entirely client-rendered (confirmed directly: a static scrape
# gets a near-empty shell) - a generic scrape here would silently
# reintroduce the exact "generic title, no details" bug already fixed for
# real searches. Querying with an empty query/no title filters returns every
# posting on that one board unfiltered, so the exact same, already-correct
# per-platform fetch/normalize logic used by real searches finds the pasted
# URL's own entry - no new per-platform code needed.
_URL_SEARCH_FUNCS = {
    "greenhouse": lambda token: job_source_greenhouse.search_greenhouse("", boards=[token], limit=250),
    "ashby": lambda token: job_source_ashby.search_ashby("", boards=[token], limit=250),
    "gem": lambda token: job_source_gem.search_gem("", boards=[token], limit=250),
    "lever": lambda token: job_source_lever.search_lever("", boards=[token], limit=250),
    "bamboohr": lambda token: job_source_bamboohr.search_bamboohr("", boards=[token], limit=250),
}


def _fetch_listing_by_url(url: str, token: str, source: str) -> dict:
    """Finds the exact posting a pasted URL points to by pulling that one
    board's full listing (unfiltered) through its normal source module and
    matching by URL - real title/description/location/salary, the same
    quality real search results get. Returns None if the platform isn't
    recognized, has no token, or the specific posting isn't in the board's
    current listing (a stale bookmark, a closed role already dropped from
    the board) - callers should fall back to a generic page fetch in that
    case, not treat it as a hard failure."""
    search_fn = _URL_SEARCH_FUNCS.get(source)
    if not search_fn or not token:
        return None
    try:
        jobs, _meta = search_fn(token)
    except Exception:
        return None
    target = url.rstrip("/")
    for job in jobs:
        if (job.get("url") or "").rstrip("/") == target:
            return job
    return None


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
    deepseek_api_key = st.text_input(
        "DeepSeek API key (optional fallback)",
        type="password",
        value=os.environ.get("DEEPSEEK_API_KEY", ""),
        help="Get one at platform.deepseek.com — a few dollars of credit goes a very long "
        "way (roughly $0.001 per call). If Anthropic returns a billing/credit error, "
        "Maester automatically retries with DeepSeek instead of failing outright. "
        "Leave blank to disable — a billing error will just fail normally, as before.",
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
    st.subheader("Role type")
    _profiles = list_profiles()
    active_profile = st.selectbox(
        "What kind of role are you searching for?",
        options=_profiles,
        format_func=lambda p: p.display_name,
        index=0,
        help="Changes search title filters, the quick-scan rubric, the deep-dive panel's "
        "personas, and the resume/cover-letter tailoring archetypes - everything downstream "
        "is framed for this role type. Applies to your next search.",
        key="role_profile_select",
    )

    st.divider()
    st.subheader("Links (optional)")
    st.caption("Included as hyperlinks in the header of both the tailored resume and cover letter, when provided.")
    linkedin_url = st.text_input("LinkedIn URL", value=os.environ.get("LINKEDIN_URL", ""))
    portfolio_url = st.text_input("Portfolio URL", value=os.environ.get("PORTFOLIO_URL", ""))
    github_url = st.text_input("GitHub URL", value=os.environ.get("GITHUB_URL", ""))

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
        limit = st.number_input(
            "Max results per company/source",
            min_value=5,
            max_value=50,
            value=15,
            help="Applies per company (Greenhouse/Ashby) or per source (Remotive), not as a shared total — "
            "selecting more companies means more total results, not fewer per company. Most companies have "
            "far fewer than 15 open roles matching the active role type at once, so raising this rarely "
            "changes results for Greenhouse/Ashby; it matters more for Remotive's broader search.",
        )

    with st.expander("Search filters"):
        sources = st.multiselect(
            "Search sources",
            options=["Remotive", "Greenhouse", "Ashby", "Gem", "Lever", "BambooHR"],
            default=["Remotive", "Greenhouse", "Ashby", "Gem", "Lever", "BambooHR"],
            help="Remotive is a broad job board (full-text matched). Greenhouse, Ashby, Gem, Lever, and BambooHR pull directly from specific companies' own job boards (title-matched, no full-text noise).",
            key="search_sources",
        )
        if "company_registry" not in st.session_state:
            st.session_state.company_registry = load_registry()
        registry_rows = st.session_state.company_registry

        MAX_COMPANIES_PER_PLATFORM = 20

        gh_registry_tokens = tokens_for_platform(registry_rows, "greenhouse")
        ab_registry_tokens = tokens_for_platform(registry_rows, "ashby")
        gem_registry_tokens = tokens_for_platform(registry_rows, "gem")
        lever_registry_tokens = tokens_for_platform(registry_rows, "lever")
        bamboohr_registry_tokens = tokens_for_platform(registry_rows, "bamboohr")

        # Bulk-imported companies (there can be thousands) are available as
        # options but never pre-selected by default — only the small, originally
        # curated set is. Otherwise a fresh page load would try to default-select
        # every company on a platform, which is both what max_selections below
        # is specifically there to prevent, and just a bad default regardless.
        curated_tokens = {r["token"] for r in registry_rows if not (r.get("notes") or "").startswith("Bulk-imported")}

        def _default_for(tokens):
            return [t for t in tokens if t in curated_tokens][:MAX_COMPANIES_PER_PLATFORM]

        gh_default = _default_for(gh_registry_tokens)
        ab_default = _default_for(ab_registry_tokens)
        gem_default = _default_for(gem_registry_tokens)
        lever_default = _default_for(lever_registry_tokens)
        bamboohr_default = _default_for(bamboohr_registry_tokens)

        greenhouse_boards = st.multiselect(
            f"Greenhouse companies to check ({len(gh_default)}/{MAX_COMPANIES_PER_PLATFORM} selected by default — {len(gh_registry_tokens)} available)",
            options=gh_registry_tokens,
            default=gh_default,
            max_selections=MAX_COMPANIES_PER_PLATFORM,
            help="Includes companies marked 'unknown' platform too — those get tried across all platforms, and the registry below records whichever one actually works. Capped so a search can't accidentally try to query thousands of companies at once.",
            key="greenhouse_boards_select",
        )
        ashby_boards = st.multiselect(
            f"Ashby companies to check ({len(ab_default)}/{MAX_COMPANIES_PER_PLATFORM} selected by default — {len(ab_registry_tokens)} available)",
            options=ab_registry_tokens,
            default=ab_default,
            max_selections=MAX_COMPANIES_PER_PLATFORM,
            help="Includes companies marked 'unknown' platform too — those get tried across all platforms, and the registry below records whichever one actually works. Capped so a search can't accidentally try to query thousands of companies at once.",
            key="ashby_boards_select",
        )
        gem_boards = st.multiselect(
            f"Gem companies to check ({len(gem_default)}/{MAX_COMPANIES_PER_PLATFORM} selected by default — {len(gem_registry_tokens)} available)",
            options=gem_registry_tokens,
            default=gem_default,
            max_selections=MAX_COMPANIES_PER_PLATFORM,
            help="Gem's API returns listings quickly but not full descriptions — matching jobs get an extra page fetch for the real JD text, so this is a bit slower per match than Greenhouse/Ashby.",
            key="gem_boards_select",
        )
        lever_boards = st.multiselect(
            f"Lever companies to check ({len(lever_default)}/{MAX_COMPANIES_PER_PLATFORM} selected by default — {len(lever_registry_tokens)} available)",
            options=lever_registry_tokens,
            default=lever_default,
            max_selections=MAX_COMPANIES_PER_PLATFORM,
            help="Lever doesn't publish a customer list, so these tokens are only as good as whoever last verified them — wrong or stale tokens will just show up as a failed board below.",
            key="lever_boards_select",
        )
        bamboohr_boards = st.multiselect(
            f"BambooHR companies to check ({len(bamboohr_default)}/{MAX_COMPANIES_PER_PLATFORM} selected by default — {len(bamboohr_registry_tokens)} available)",
            options=bamboohr_registry_tokens,
            default=bamboohr_default,
            max_selections=MAX_COMPANIES_PER_PLATFORM,
            help="BambooHR customers span every industry, not just tech — expect a wider mix of role types than the other sources.",
            key="bamboohr_boards_select",
        )

        with st.expander("Manage companies (add, edit, verify)"):
            st.caption(
                "Edit directly — add a row, fix a wrong platform, or add notes. "
                "'verified' means confirmed by a real search hit or your own direct knowledge; "
                "'unverified' is a guess; 'unknown' platform gets tried across all three platforms until discovered."
            )
            edited_rows = st.data_editor(
                registry_rows,
                num_rows="dynamic",
                width='stretch',
                column_config={
                    "platform": st.column_config.SelectboxColumn(
                        options=["greenhouse", "ashby", "gem", "lever", "bamboohr", "unknown"]
                    ),
                    "status": st.column_config.SelectboxColumn(
                        options=["verified", "unverified", "failed"]
                    ),
                },
                key="company_editor",
            )
            if st.button("Save company changes"):
                # A newly-added row's blank cells come back as None (not ""),
                # which broke downstream code elsewhere that assumed these
                # fields are always strings (e.g. notes.startswith(...)).
                # Sanitize here, at the point of saving, rather than trying
                # to defend every place that later reads these fields.
                sanitized_rows = []
                for r in edited_rows:
                    company = (r.get("company") or "").strip()
                    token = (r.get("token") or "").strip().lower() or company.lower().replace(" ", "")
                    if not company and not token:
                        continue  # a fully blank row added but never filled in — skip it
                    sanitized_rows.append({
                        "company": company or token,
                        "token": token,
                        "platform": (r.get("platform") or "unknown"),
                        "status": (r.get("status") or "unverified"),
                        "last_checked": r.get("last_checked") or "",
                        "notes": r.get("notes") or "",
                    })
                st.session_state.company_registry = sanitized_rows
                save_registry(sanitized_rows)
                st.success("Saved. Re-open this panel's dropdowns above to see new companies.")
                st.rerun()

        _category_options = ["product", "project-management", "all-others", None]
        category = st.selectbox(
            "Remotive category",
            options=_category_options,
            format_func=lambda c: "All categories" if c is None else c,
            index=_category_options.index(active_profile.remotive_category)
            if active_profile.remotive_category in _category_options
            else _category_options.index(None),
            help="Remotive's own category tag - a soft preference, not a hard filter. Defaults based on the selected role type above.",
        )
        exclude_engineering = st.checkbox(
            f"Exclude titles that don't match {active_profile.display_name} (unrelated roles sharing a keyword)",
            value=True,
            help="Drops listings whose title matches one of the active role type's exclude keywords, even if the search query term also appears in the title.",
        )
        require_role_title = st.checkbox(
            f"Require a {active_profile.display_name}-shaped title",
            value=True,
            help="Remotive matches your search against the full job description, not just the title, so a generic query can return unrelated roles that just happen to mention a search word somewhere. This requires the title itself to match the active role type.",
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
            gem_meta = {}
            lever_meta = {}
            bamboohr_meta = {}

            if "Remotive" in sources:
                with st.spinner(f"Searching Remotive for '{query}'..."):
                    try:
                        rt_jobs, search_meta = search_jobs(
                            query,
                            limit=int(limit),
                            category=category,
                            exclude_titles=active_profile.title_exclude if exclude_engineering else [],
                            require_title_keywords=active_profile.title_include if require_role_title else None,
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
                            exclude_titles=active_profile.title_exclude if exclude_engineering else None,
                            require_title_keywords=active_profile.title_include if require_role_title else None,
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
                            exclude_titles=active_profile.title_exclude if exclude_engineering else None,
                            require_title_keywords=active_profile.title_include if require_role_title else None,
                        )
                        jobs.extend(ab_jobs)
                        if ab_meta.get("boards_failed"):
                            st.caption(
                                f"Ashby boards that returned nothing (dead token or no matches): "
                                f"{', '.join(ab_meta['boards_failed'])}"
                            )
                    except Exception as e:
                        st.error(f"Ashby search failed: {e}")

            if "Gem" in sources:
                with st.spinner(f"Checking {len(gem_boards)} Gem boards for '{query}'..."):
                    try:
                        gem_jobs, gem_meta = job_source_gem.search_gem(
                            query,
                            boards=gem_boards,
                            limit=int(limit),
                            exclude_titles=active_profile.title_exclude if exclude_engineering else None,
                            require_title_keywords=active_profile.title_include if require_role_title else None,
                        )
                        jobs.extend(gem_jobs)
                        if gem_meta.get("boards_failed"):
                            st.caption(
                                f"Gem boards that returned nothing (dead token or no matches): "
                                f"{', '.join(gem_meta['boards_failed'])}"
                            )
                    except Exception as e:
                        st.error(f"Gem search failed: {e}")

            if "Lever" in sources:
                with st.spinner(f"Checking {len(lever_boards)} Lever boards for '{query}'..."):
                    try:
                        lever_jobs, lever_meta = job_source_lever.search_lever(
                            query,
                            boards=lever_boards,
                            limit=int(limit),
                            exclude_titles=active_profile.title_exclude if exclude_engineering else None,
                            require_title_keywords=active_profile.title_include if require_role_title else None,
                        )
                        jobs.extend(lever_jobs)
                        if lever_meta.get("boards_failed"):
                            st.caption(
                                f"Lever boards that returned nothing (dead token or no matches): "
                                f"{', '.join(lever_meta['boards_failed'])}"
                            )
                    except Exception as e:
                        st.error(f"Lever search failed: {e}")

            if "BambooHR" in sources:
                with st.spinner(f"Checking {len(bamboohr_boards)} BambooHR boards for '{query}'..."):
                    try:
                        bamboohr_jobs, bamboohr_meta = job_source_bamboohr.search_bamboohr(
                            query,
                            boards=bamboohr_boards,
                            limit=int(limit),
                            exclude_titles=active_profile.title_exclude if exclude_engineering else None,
                            require_title_keywords=active_profile.title_include if require_role_title else None,
                        )
                        jobs.extend(bamboohr_jobs)
                        if bamboohr_meta.get("boards_failed"):
                            st.caption(
                                f"BambooHR boards that returned nothing (dead subdomain or no matches): "
                                f"{', '.join(bamboohr_meta['boards_failed'])}"
                            )
                    except Exception as e:
                        st.error(f"BambooHR search failed: {e}")

            # Self-correcting registry: whatever actually worked (or didn't)
            # on this search gets recorded, so unverified guesses turn into
            # verified facts, or wrong guesses get flagged, without you
            # having to manually check.
            if gh_meta or ab_meta or gem_meta or lever_meta or bamboohr_meta:
                for token in gh_meta.get("boards_checked", []):
                    registry_rows = record_discovery(registry_rows, token, "greenhouse", found=True)
                for token in gh_meta.get("boards_failed", []):
                    registry_rows = record_discovery(registry_rows, token, "greenhouse", found=False)
                for token in ab_meta.get("boards_checked", []):
                    registry_rows = record_discovery(registry_rows, token, "ashby", found=True)
                for token in ab_meta.get("boards_failed", []):
                    registry_rows = record_discovery(registry_rows, token, "ashby", found=False)
                for token in gem_meta.get("boards_checked", []):
                    registry_rows = record_discovery(registry_rows, token, "gem", found=True)
                for token in gem_meta.get("boards_failed", []):
                    registry_rows = record_discovery(registry_rows, token, "gem", found=False)
                for token in lever_meta.get("boards_checked", []):
                    registry_rows = record_discovery(registry_rows, token, "lever", found=True)
                for token in lever_meta.get("boards_failed", []):
                    registry_rows = record_discovery(registry_rows, token, "lever", found=False)
                for token in bamboohr_meta.get("boards_checked", []):
                    registry_rows = record_discovery(registry_rows, token, "bamboohr", found=True)
                for token in bamboohr_meta.get("boards_failed", []):
                    registry_rows = record_discovery(registry_rows, token, "bamboohr", found=False)

                # Cross-platform fallback: a company that failed on the platform
                # it was searched under gets tried on the other supported
                # platforms before giving up — only for companies actually
                # selected this search, never a proactive bulk scan. This is
                # what turns "OpenAI failed on Greenhouse" into "OpenAI found
                # on Ashby, verified" in the same search, instead of silently
                # staying wrong until someone happens to notice and re-select
                # it under the right platform manually.
                failed_by_platform = {
                    "greenhouse": gh_meta.get("boards_failed", []),
                    "ashby": ab_meta.get("boards_failed", []),
                    "gem": gem_meta.get("boards_failed", []),
                    "lever": lever_meta.get("boards_failed", []),
                    "bamboohr": bamboohr_meta.get("boards_failed", []),
                }
                failed_by_platform = {p: t for p, t in failed_by_platform.items() if t}

                if failed_by_platform:
                    with st.spinner("Checking whether any failed companies are actually on a different platform..."):
                        extra_jobs, resolutions = resolve_cross_platform(
                            failed_by_platform,
                            query,
                            limit=int(limit),
                            exclude_titles=active_profile.title_exclude if exclude_engineering else None,
                            require_title_keywords=active_profile.title_include if require_role_title else None,
                        )
                        jobs.extend(extra_jobs)

                        resolved_bits = []
                        for token, result in resolutions.items():
                            if result["status"] == "resolved":
                                registry_rows = record_discovery(registry_rows, token, result["platform"], found=True)
                                resolved_bits.append(f"{token} → {result['platform']}")
                            else:
                                registry_rows = mark_failed_all(registry_rows, token, result["platforms_tried"])

                        if resolved_bits:
                            st.caption(f"Resolved to a different platform this search: {', '.join(resolved_bits)}")

                st.session_state.company_registry = registry_rows
                save_registry(registry_rows)

            if search_meta.get("broadened"):
                note = f"No Remotive listings matched \"{search_meta['original_query']}\" with the current filters, so I broadened that search"
                changes = []
                if (search_meta.get("used_query") or "").lower() != (search_meta.get("original_query") or "").lower():
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

                # Cache reuse is scoped to the active role profile - a URL
                # scored under a different role type (e.g. Product Manager)
                # is treated as unseen here and re-scored, not silently
                # shown with a stale, wrong-lens score (see data/dedup.py).
                seen = load_seen_urls()

                def _cached_for_active_profile(job):
                    row = seen.get(job.get("url"))
                    return row is not None and row.get("role_profile") == active_profile.id

                new_jobs = [j for j in jobs if not _cached_for_active_profile(j)]
                cached_jobs = [j for j in jobs if _cached_for_active_profile(j)]

                results = [
                    quick_score_from_cache(seen[j["url"]], str(j.get("id", j["url"])))
                    for j in cached_jobs
                ]

                if new_jobs:
                    with st.spinner(f"Scoring {len(new_jobs)} new listings against your resume..."):
                        try:
                            new_results = batch_score(resume_text, new_jobs, api_key, role_profile=active_profile, deepseek_api_key=deepseek_api_key)
                            results.extend(new_results)
                            # Only cache genuine successes — a failed attempt (grade "?")
                            # shouldn't get treated as "already scored" and silently block
                            # that listing from ever being retried on a future search, even
                            # after whatever caused the failure gets fixed.
                            succeeded = [r for r in new_results if r.grade != "?"]
                            record_scans(succeeded)
                            failed_count = len(new_results) - len(succeeded)
                            if failed_count:
                                st.caption(f"{failed_count} listing(s) failed to score and were not cached — they'll be retried on your next search.")
                        except Exception as e:
                            st.error(f"Scoring failed: {e}")

                results.sort(key=lambda r: r.score, reverse=True)
                st.session_state.search_results = results

                if cached_jobs:
                    st.caption(
                        f"Skipped re-scoring {len(cached_jobs)} listing(s) already seen in a previous "
                        f"search — reused the cached score instead of another API call."
                    )

    st.divider()
    st.markdown("**Or score a specific listing by URL**")
    paste_url = st.text_input(
        "Paste a job URL directly",
        key="score_url_input",
        placeholder="https://job-boards.greenhouse.io/company/jobs/12345",
        help="Recognizes Greenhouse, Ashby, Lever, Gem, and BambooHR URLs (including a Greenhouse board "
        "embedded on a company's own custom careers domain, e.g. a \"?gh_jid=\" URL) and pulls the real "
        "listing data the same way a search would, registering the company in the registry below for "
        "future searches. Other career pages get a best-effort page scrape instead.",
    )
    if st.button("Score this URL"):
        if not api_key:
            st.error("Add your Anthropic API key in the sidebar first.")
        elif not resume_text.strip():
            st.error("Add a resume first.")
        elif not paste_url.strip():
            st.error("Paste a job URL first.")
        else:
            with st.spinner("Fetching and scoring this listing..."):
                try:
                    token, source = parse_company_and_source_from_url(paste_url)
                    job = _fetch_listing_by_url(paste_url, token, source)
                    if job is None and not token:
                        # Not a recognized job-boards.greenhouse.io/ashby/
                        # lever/gem/bamboohr URL, but many companies embed a
                        # Greenhouse board on their OWN custom careers domain
                        # instead (a "?gh_jid=<id>" URL) - confirmed directly
                        # this style of page is ALSO itself client-rendered,
                        # so a generic scrape gets nav chrome, not the job.
                        # Resolve straight to Greenhouse's API using the
                        # board token discovered from the embed widget's own
                        # script tag, still present in the static HTML.
                        job = job_source_greenhouse.resolve_embedded_job(paste_url)
                        if job:
                            token, source = job["board"], "greenhouse"
                    if job is None:
                        # Unrecognized platform (custom career page), or a
                        # recognized one where this exact posting wasn't in
                        # the board's current listing (a stale bookmark,
                        # already-closed role) - fall back to a generic
                        # page scrape rather than failing outright.
                        page = fetch_job_page(paste_url)
                        liveness = check_liveness(page["text"], page["final_url"])
                        if liveness["status"] == "expired":
                            st.warning(f"⚠ This posting may no longer be active: {liveness['reason']}")
                        job = {
                            "id": paste_url,
                            "title": page.get("title") or "Unknown role",
                            "company": token or "Unknown",
                            "url": paste_url,
                            "location": "",
                            "salary": extract_salary(page["text"]),
                            "category": "",
                            "published": "",
                            "description": page["text"],
                            "source": source or "unknown",
                            "board": token or "unknown",
                        }

                    # Same cache-reuse logic as a real search, scoped to the
                    # active role profile (see data/dedup.py) - a URL already
                    # scored under this exact profile doesn't burn a second
                    # API call.
                    seen = load_seen_urls()
                    cached_row = seen.get(job["url"])
                    if cached_row and cached_row.get("role_profile") == active_profile.id:
                        result = quick_score_from_cache(cached_row, str(job.get("id", job["url"])))
                        st.caption("Reused a cached score from a previous search.")
                    else:
                        scored = batch_score(
                            resume_text, [job], api_key, role_profile=active_profile, deepseek_api_key=deepseek_api_key
                        )
                        result = scored[0]
                        if result.grade != "?":
                            record_scans([result])

                    # Ties the pasted URL to the exact job board it came
                    # from, same self-correcting registry real searches
                    # already use - only when the URL actually parsed to a
                    # known platform with a real token; a custom career page
                    # has nothing to register.
                    if token and source and source != "unknown":
                        registry_rows = st.session_state.get("company_registry") or load_registry()
                        registry_rows = record_discovery(registry_rows, token, source, found=True)
                        st.session_state.company_registry = registry_rows
                        save_registry(registry_rows)

                    st.session_state.jobs_by_id[str(result.job_id)] = job
                    # Prepend, don't replace - coexists with whatever's
                    # already in search_results instead of wiping it out.
                    # Re-pasting the same URL replaces its own prior entry
                    # rather than duplicating it.
                    existing = [r for r in st.session_state.search_results if r.job_id != result.job_id]
                    st.session_state.search_results = [result] + existing
                    st.success(f"Scored: **{result.title}** at **{result.company}** — {result.grade} ({result.score:.1f}/5.0)")
                except Exception as e:
                    st.error(f"Couldn't fetch or score this listing: {e}")

    if st.session_state.search_results:
        st.markdown(f"### {len(st.session_state.search_results)} listings ranked")
        st.caption(
            "These are a fast first-pass triage, not a verdict — titles can be misleading. "
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
                    elif r.source == "gem":
                        source_label = f"Gem · {r.board}"
                    elif r.source == "lever":
                        source_label = f"Lever · {r.board}"
                    elif r.source == "bamboohr":
                        source_label = f"BambooHR · {r.board}"
                    else:
                        source_label = "Remotive"
                    meta_bits = [source_label]
                    if r.location:
                        meta_bits.append(r.location)
                    if r.salary:
                        comp_suffix = f" (reliability: {r.comp_reliability})" if r.comp_reliability else ""
                        meta_bits.append(f"{r.salary}{comp_suffix}")

                    published_display = format_published_date(r.published)
                    freshness = compute_freshness(r.published, r.title)
                    title_line = f"**{r.title}** — {r.company}"
                    if published_display:
                        freshness_prefix = f"{freshness['emoji']} {freshness['label']} · " if freshness["label"] else ""
                        title_line += f"  &nbsp;&nbsp;:gray[{freshness_prefix}posted {published_display}]"

                    st.markdown(title_line)
                    st.caption(f"{r.reason}  \n:gray[{' · '.join(meta_bits)}]")
                    if r.legitimacy_tier and r.legitimacy_tier != "High Confidence":
                        legit_color = "red" if r.legitimacy_tier == "Suspicious" else "orange"
                        st.caption(f":{legit_color}[⚠ {r.legitimacy_tier}] — {r.legitimacy_note}")
                with c2:
                    st.markdown(f":{grade_color}[**{r.grade}**]  {r.score:.1f}/5.0")
                with c3:
                    st.link_button("Open ↗", r.url, width='stretch')
                with c4:
                    if st.button("Deep dive", key=f"dive_{r.job_id}", width='stretch'):
                        st.session_state.deep_dive_job = st.session_state.jobs_by_id.get(r.job_id)
                        st.rerun()

# ---------------------------------------------------------------------------
# TAB 2: Deep Dive — full 5-panelist evaluation on a selected listing.
# ---------------------------------------------------------------------------
with tab_deep_dive:
    job = st.session_state.deep_dive_job

    st.markdown("Run the full panel on a listing you picked from search results, or paste one directly.")
    manual_url = st.text_input("...or paste a job URL directly", key="manual_url")

    # If the user actively types a new URL, treat that as a clear signal they
    # want to switch away from a previously-selected search result — without
    # this, "job" stays set in session_state forever once chosen, and the
    # if/elif below would keep re-running the old selection no matter what
    # gets typed here.
    previous_manual_url = st.session_state.get("_last_manual_url", "")
    if manual_url and manual_url != previous_manual_url and job:
        st.session_state.deep_dive_job = None
        job = None
    st.session_state["_last_manual_url"] = manual_url

    target_job = None
    if job:
        st.info(f"Selected from search: **{job['title']}** at **{job['company']}**")
        col_open, col_clear = st.columns([3, 1])
        with col_open:
            st.link_button("Open listing ↗", job["url"])
        with col_clear:
            if st.button("✕ Clear selection", width='stretch'):
                st.session_state.deep_dive_job = None
                st.rerun()
        target_job = job
    elif manual_url:
        # Try the same accurate, per-platform fetch Search & Score's "score
        # a listing by URL" uses, including Greenhouse-embed resolution
        # (see sources/greenhouse.py) - a manually-pasted URL used to always
        # fall straight to a generic page scrape below (target_job's
        # "description" was never populated here), which is exactly what
        # produced an unreadable result for a client-rendered page like a
        # Greenhouse embed on a company's own domain.
        parsed_company, parsed_source = parse_company_and_source_from_url(manual_url)
        resolved = _fetch_listing_by_url(manual_url, parsed_company, parsed_source)
        if resolved is None and not parsed_company:
            resolved = job_source_greenhouse.resolve_embedded_job(manual_url)
            if resolved:
                parsed_company, parsed_source = resolved["board"], "greenhouse"
        if resolved:
            target_job = resolved
        else:
            target_job = {
                "title": "",
                "company": parsed_company,
                "url": manual_url,
                "description": "",
                "source": parsed_source or "unknown",
                "board": parsed_company or "unknown",
            }

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
                    liveness = None
                    if target_job.get("description"):
                        job_text = target_job["description"]
                    else:
                        page = fetch_job_page(target_job["url"])
                        job_text = page["text"]
                        liveness = check_liveness(job_text, page["final_url"])

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
                    # a search result (not a fresh fetch already), try the live page once —
                    # and replace job_text itself with the fuller live version, not just
                    # the extracted salary string, so the panel's own Comp Reliability
                    # reasoning sees the same salary text the regex found, instead of the
                    # two disagreeing because only one of them got the live page's content.
                    if not salary and target_job.get("url") and target_job.get("description"):
                        try:
                            live_text = fetch_job_text(target_job["url"])
                            live_salary = extract_salary(live_text)
                            if live_salary:
                                salary = live_salary
                                job_text = live_text
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
                        deepseek_api_key=deepseek_api_key,
                        role_profile=active_profile,
                    )
                    log_result(result)
                    # Persisted so the tailoring button below survives the rerun
                    # it triggers, independent of when the panel was actually run.
                    st.session_state.deep_dive_result = result
                    st.session_state.deep_dive_job_text = job_text
                    st.session_state.deep_dive_liveness = liveness
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

        liveness = st.session_state.get("deep_dive_liveness")
        if liveness and liveness["status"] == "expired":
            st.error(f"⚠ This posting may no longer be active. {liveness['reason']} The evaluation below is still shown, but check the listing directly before acting on it.")
        elif liveness and liveness["status"] == "unknown":
            st.warning(f"⚠ Couldn't confirm this posting is still active. {liveness['reason']}")

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
                        deepseek_api_key=deepseek_api_key,
                        # Matches the role profile the Deep Dive itself ran
                        # under (result.role_profile), not necessarily
                        # today's sidebar selection - the tailoring is
                        # grounded in that specific evaluation's gaps/fixes,
                        # so it should stay consistent with it even if the
                        # sidebar's role type has since been changed.
                        role_profile=get_profile(result.role_profile),
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
                            candidate_tagline=materials.get("candidate_tagline", ""),
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

                        # Persisted so the Apply button below (a separate
                        # rerun) can still find these paths.
                        st.session_state.resume_pdf_path = resume_pdf_path
                        st.session_state.cover_pdf_path = cover_pdf_path
                    except Exception as e:
                        st.error(f"PDF rendering failed: {e}")

            resume_pdf_path = st.session_state.get("resume_pdf_path")
            cover_pdf_path = st.session_state.get("cover_pdf_path")
            if resume_pdf_path and cover_pdf_path:
                st.divider()
                st.markdown("#### Apply")
                st.caption(
                    "Opens the real application page in a visible browser, checks it's still live, "
                    "and fills in your contact info, tailored resume, cover letter, and custom "
                    "question answers. It never clicks submit — you review the filled page and do "
                    "that yourself."
                )
                if st.button("Open application & auto-fill"):
                    with st.spinner("Checking the listing and opening a browser..."):
                        contact_info = parse_contact_info(resume_text)
                        links = {
                            "linkedin_url": linkedin_url,
                            "portfolio_url": portfolio_url,
                            "github_url": github_url,
                        }
                        fill_result = open_and_fill(
                            url=result.job_url,
                            resume_text=resume_text,
                            company=result.company,
                            role_title=result.role_title,
                            contact_info=contact_info,
                            links=links,
                            resume_pdf_path=resume_pdf_path,
                            cover_letter_pdf_path=cover_pdf_path,
                            api_key=api_key,
                            deepseek_api_key=deepseek_api_key,
                        )

                    if fill_result.status == "dead":
                        st.error(f"This posting looks closed, so nothing was opened. {fill_result.reason}")
                    elif fill_result.status == "error":
                        st.error(fill_result.reason)
                    else:
                        log_fill_attempt(
                            company=result.company,
                            role_title=result.role_title,
                            url=result.job_url,
                            fields_auto_mapped=fill_result.fields_auto_mapped,
                            fields_flagged=fill_result.fields_flagged,
                        )
                        st.success(
                            "Browser opened and filled. Review it yourself, especially anything "
                            "flagged below, then submit it on your own."
                        )
                        if fill_result.reason:
                            st.warning(fill_result.reason)
                        if fill_result.fields_auto_mapped:
                            st.caption("Auto-filled: " + ", ".join(fill_result.fields_auto_mapped))
                        if fill_result.fields_flagged:
                            st.warning("Needs your attention: " + ", ".join(fill_result.fields_flagged))

# ---------------------------------------------------------------------------
# TAB 3: Dashboard — everything you've deep-dived on, logged locally.
# ---------------------------------------------------------------------------
with tab_dashboard:
    st.subheader("All deep-dive evaluations")
    rows = load_all()
    if not rows:
        st.info("No deep-dive evaluations logged yet.")
    else:
        # Latest deep dive first - timestamps are ISO-format strings
        # (log_result uses datetime.isoformat()), so a plain lexicographic
        # sort is already chronological, no parsing needed.
        rows_sorted = sorted(rows, key=lambda r: r.get("timestamp") or "", reverse=True)
        st.dataframe(
            rows_sorted,
            width='stretch',
            column_config={
                "url": st.column_config.LinkColumn("Listing", display_text="Open ↗")
            },
        )
