"""
role_profiles/chief_of_staff.py
Fourth role profile, same standard as the others - real title filters, a
real rubric gate, a distinct 5-person panel, and real tailoring archetypes,
not a stub.

Chief of Staff is a genuinely broad, generalist role by nature (unlike CS or
AE, there's no single skill/tooling depth that gates fit) - the rubric gate
here is framed around scope/trust signals (does the listing actually give
this person cross-functional authority and executive proximity, or is it a
glorified EA/PMO title) rather than a specific tooling gap, since that's the
axis this candidate's actual 2x-founder, cross-functional generalist
background maps onto most directly and where the real risk of title
mismatch (in both directions) lives.
"""

from role_profiles.base import PanelPersona, RoleProfile

_TITLE_INCLUDE = [
    "chief of staff",
    "chief-of-staff",
    "cos to the ceo",
    "chief of staff to the ceo",
    "chief of staff to the founder",
    "head of chief of staff",
    "deputy chief of staff",
    "strategy and chief of staff",
    "business operations and chief of staff",
]

# Titles sharing "operations"/"strategy"/"executive" words but describing a
# genuinely different job: a pure administrative/EA role, a narrow PMO
# function, or a generic ops/strategy role with no executive-proximity or
# cross-functional mandate.
_TITLE_EXCLUDE = [
    "executive assistant",
    "administrative assistant",
    "office manager",
    "project manager",
    "program manager",
    "operations coordinator",
    "operations analyst",
    "business analyst",
    "management consultant",
    "strategy consultant",
    "office of the ceo intern",
]

_RUBRIC_TITLE_INFLATION_NOTE = (
    'Titles can be misleading — a "Chief of Staff" title sometimes describes '
    "a glorified executive-assistant or calendar-management role with no real "
    "cross-functional authority, or conversely a narrow "
    '"Operations"/"Strategy" title that actually carries genuine executive '
    "proximity and mandate (check for signals like: who the role reports to, "
    "whether it owns cross-functional initiatives or just supports one "
    "executive's logistics, whether it has any real decision-making or "
    "influence scope stated in the listing)."
)

_RUBRIC_DIMENSIONS = """- Role/Skills match (gate: if the listing's real substance is administrative/
  logistical support (calendar management, travel booking, meeting notes) with
  no cross-functional project ownership or executive-decision involvement, the
  overall score has a CEILING of 2.5 — not a fixed value. A candidate without a
  formal "Chief of Staff" title but with real cross-functional execution,
  ambiguous-scope ownership, or direct executive/founder partnership (common in
  founder/PM backgrounds) should be judged on that SUBSTANCE, not penalized for
  the title alone — but genuine gaps (no formal executive-support experience,
  no board-meeting-prep or investor-relations exposure, no experience running
  company-wide operating cadences) still count against fit and should be named
  plainly, not glossed over. Within the gated range, differentiate by severity
  the same way as any other listing — don't default to a round anchor score.)
- Seniority fit (over- or under-leveled counts against it)
- Domain/industry relevance
- Location/remote feasibility given what the listing states"""

_PANEL_PERSONAS = [
    PanelPersona(
        role="Recruiter",
        criteria=(
            " — hard screens: years of cross-functional execution or direct "
            "executive-partnership experience, must-haves, location/comp "
            "signals, resume red flags, whether the resume survives a "
            "30-second scan."
        ),
    ),
    PanelPersona(
        role="CEO/Founder",
        criteria=(
            " — trust and scope match: would this person actually be given "
            "real authority and access, judgment under ambiguity, whether "
            'they can represent the executive\'s intent without being a '
            "yes-person. Skeptical of title inflation and vague "
            '"strategic initiatives" claims without real ownership.'
        ),
    ),
    PanelPersona(
        role="Head of Operations",
        criteria=(
            " (peer) — craft: how cross-functional projects were actually "
            "run end-to-end, operating-cadence design (OKRs, all-hands, "
            "board prep), whether outcomes reflect real process ownership "
            "or one-off task execution."
        ),
    ),
    PanelPersona(
        role="Board/Investor Stakeholder",
        criteria=(
            " — whether the candidate has actually been exposed to "
            "board-level or investor-facing work (deck prep, data rooms, "
            "fundraising support), or only internal-facing operations work "
            "with no external-facing polish."
        ),
    ),
    PanelPersona(
        role="Cross-Functional Partner",
        criteria=(
            " — how this person would actually land with a skeptical "
            "functional lead (Eng, Sales, Finance): credibility without "
            "formal authority, communication clarity, whether they'd be "
            "seen as a genuine partner or an unwelcome extra layer."
        ),
    ),
]

_TAILOR_ARCHETYPE_BLOCK = """ARCHETYPE DETECTION: classify the listing into one of these Chief of Staff
archetypes (or a hybrid of two), based on signals in the JD:
- Strategy & Operations CoS — "strategic initiatives", "cross-functional projects", "operating cadence"
- Executive Partnership CoS — "trusted advisor", "represents the CEO", "executive proximity"
- Scaling/Ops-Building CoS — "0-to-1", "building process", "scaling operations", "early-stage"
- Board & Investor-Facing CoS — "board meetings", "investor relations", "fundraising support"
- PMO/Program CoS — "program management", "company-wide initiatives", "tracking OKRs"

State the detected archetype, then let it inform which of the candidate's own
experience gets foregrounded — even where the candidate's formal title wasn't
"Chief of Staff." Surface genuinely cross-functional, ambiguous-scope, or
direct-executive-partnership work honestly as what it actually was (e.g., a
founder role that included running company-wide operating cadences, investor
communications, or direct decision-making on a co-founder's behalf), never
reframed as a Chief of Staff title the candidate didn't hold — the same
no-fabrication rule applies here as everywhere else."""

PROFILE = RoleProfile(
    id="chief_of_staff",
    display_name="Chief of Staff",
    title_include=_TITLE_INCLUDE,
    title_exclude=_TITLE_EXCLUDE,
    # Remotive has no Chief of Staff-shaped category (confirmed against its
    # real category list: Product Management, Sales, Design, Devops, Data
    # and Analytics, Marketing, Medical, Information Technology, Software
    # Development, Writing, Customer Service, All others - nothing CoS-
    # shaped) - None means "all categories," same as customer_success.py.
    remotive_category=None,
    rubric_title_inflation_note=_RUBRIC_TITLE_INFLATION_NOTE,
    rubric_dimensions=_RUBRIC_DIMENSIONS,
    panel_personas=_PANEL_PERSONAS,
    tailor_archetype_block=_TAILOR_ARCHETYPE_BLOCK,
)
