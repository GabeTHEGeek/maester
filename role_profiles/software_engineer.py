"""
role_profiles/software_engineer.py
Fifth role profile, and the first written generically rather than around
this project's own candidate (Gabriel Pendleton's founder/PM background).
Product Manager, Customer Success, Account Executive, and Chief of Staff
were all written with a specific real resume's gaps in mind (no formal
title on the resume, judge transferable substance honestly). This one
exists to make Maester itself more broadly usable — a genuine test of
whether the role_profiles architecture holds up for a candidate whose
actual resume is hands-on engineering work, not adjacent/transferable
experience wearing a different title. Same standard as the others: real
title filters, a real rubric gate, a distinct 5-person panel, and
tailoring archetypes, not a stub.
"""

from role_profiles.base import PanelPersona, RoleProfile

_TITLE_INCLUDE = [
    "software engineer",
    "software developer",
    "backend engineer",
    "back-end engineer",
    "frontend engineer",
    "front-end engineer",
    "full stack engineer",
    "full-stack engineer",
    "fullstack engineer",
    "application developer",
    "systems engineer",
    "platform engineer",
    "swe",
    "sde",
    "member of technical staff",
    "engineer ii",
    "engineer iii",
    "staff engineer",
    "senior engineer",
    "principal engineer",
]

# Titles sharing "engineer"/"developer" words but describing a genuinely
# different discipline with its own distinct skill set and hiring bar.
_TITLE_EXCLUDE = [
    "engineering manager",
    "director of engineering",
    "vp of engineering",
    "sales engineer",
    "solutions engineer",
    "support engineer",
    "customer engineer",
    "qa engineer",
    "test engineer",
    "site reliability engineer",
    "sre",
    "devops engineer",
    "data engineer",
    "machine learning engineer",
    "ml engineer",
    "ai engineer",
    "security engineer",
    "hardware engineer",
    "network engineer",
    "field engineer",
    "systems administrator",
]

_RUBRIC_TITLE_INFLATION_NOTE = (
    'Titles can be misleading — a "Software Engineer" title sometimes describes '
    "a narrow scripting/configuration role with little real system ownership, or "
    'conversely a "Developer" title at a small company that actually carries '
    "full-stack architecture responsibility (check for signals like: whether the "
    "role owns production systems end-to-end, what the actual tech stack and "
    "scale are, whether it's greenfield building vs. maintenance work, how much "
    "of the job is writing code vs. configuring third-party tools)."
)

_RUBRIC_DIMENSIONS = """- Role/Skills match (gate: if the listing requires deep production experience
  with a specific language, framework, or system-at-scale the candidate has
  never actually worked with, or the role's real substance is non-coding work
  (pure configuration, pure QA, no ownership of production systems), the
  overall score has a CEILING of 2.5 — not a fixed value. Within the gated
  range, differentiate by severity the same way as any other listing: a stack
  mismatch with real transferable fundamentals (e.g. strong backend experience
  applying to a role in an unfamiliar but similar language) can land higher,
  around 2.0-2.5, while a role requiring deep specialized expertise the
  candidate has never touched should land lower, around 1.0-1.5 — don't
  default to a round anchor score.)
- Seniority fit (over- or under-leveled counts against it)
- Domain/industry relevance
- Location/remote feasibility given what the listing states"""

_PANEL_PERSONAS = [
    PanelPersona(
        role="Recruiter",
        criteria=(
            " — hard screens: years of hands-on engineering experience, required "
            "languages/frameworks, must-haves, location/comp signals, resume red "
            "flags, whether the resume survives a 30-second scan."
        ),
    ),
    PanelPersona(
        role="Engineering Manager",
        criteria=(
            " — scope match, level match, whether this person can own real "
            "production work on day one. Skeptical of title inflation and vague "
            '"built X" claims without a clear account of what was actually built '
            "and by whom."
        ),
    ),
    PanelPersona(
        role="Staff Engineer",
        criteria=(
            " (peer) — craft: code quality signals, system design judgment, "
            "debugging/incident stories, whether technical decisions show real "
            "tradeoff reasoning or just tool-listing."
        ),
    ),
    PanelPersona(
        role="Systems Architect",
        criteria=(
            " — depth on scale, reliability, and architecture: has this person "
            "actually designed systems for real production load and failure "
            "modes, or only worked within systems someone else designed."
        ),
    ),
    PanelPersona(
        role="Cross-Functional Product Partner",
        criteria=(
            " — how this person works with non-engineers: communication "
            "clarity, whether they can explain technical tradeoffs to a "
            "product/business audience, collaboration versus working in "
            "isolation."
        ),
    ),
]

_TAILOR_ARCHETYPE_BLOCK = """ARCHETYPE DETECTION: classify the listing into one of these Software
Engineering archetypes (or a hybrid of two), based on signals in the JD:
- Backend/Systems Engineer — "distributed systems", "APIs", "databases", "scalability"
- Frontend/Product Engineer — "UI", "React", "user-facing", "design collaboration"
- Full-Stack Engineer — "end-to-end", "full stack", "ship features independently"
- Infrastructure/Platform Engineer — "infrastructure", "developer tooling", "internal platform", "CI/CD"
- Mobile Engineer — "iOS", "Android", "mobile app", "React Native"

State the detected archetype, then let it inform which of the candidate's own
experience gets foregrounded. Surface genuinely hands-on engineering work
honestly as what it actually was — real languages, frameworks, and systems
the candidate worked with, at the scale and scope the resume actually
supports — never inflated to a stack, scale, or ownership level the
candidate didn't have. The same no-fabrication rule applies here as
everywhere else: no invented languages, frameworks, or production systems
not already in the source resume."""

PROFILE = RoleProfile(
    id="software_engineer",
    display_name="Software Engineer",
    title_include=_TITLE_INCLUDE,
    title_exclude=_TITLE_EXCLUDE,
    remotive_category="software-dev",
    rubric_title_inflation_note=_RUBRIC_TITLE_INFLATION_NOTE,
    rubric_dimensions=_RUBRIC_DIMENSIONS,
    panel_personas=_PANEL_PERSONAS,
    tailor_archetype_block=_TAILOR_ARCHETYPE_BLOCK,
)
