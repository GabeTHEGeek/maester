"""
role_profiles/product_manager.py
The original, default role profile - every value here is content that used
to be hardcoded directly into sources/remotive.py, engines/rubric.py,
engines/panel.py, and engines/tailor.py before role profiles existed.
Moved here verbatim (not rewritten) so this refactor changes WHERE this
content lives, not what it says.
"""

from role_profiles.base import PanelPersona, RoleProfile

# A listing's title must contain at least one of these to be considered a PM
# role at all. This exists because Remotive's search matches full description
# text, not just the title — a query like "product" will otherwise return any
# posting that mentions the word "product" anywhere (Accounts Payable, Patient
# Care, Freelance Writer, etc. all slipped through without this).
_TITLE_INCLUDE = [
    "product manager",
    "product owner",
    "product lead",
    "head of product",
    "director of product",
    "vp of product",
    "vp, product",
    "group product manager",
    "technical product manager",
    "product management",
    "product strategist",
    "outcomes manager",
    "product director",
    "chief product officer",
    "cpo",
]

# Titles containing these words are hands-on IC engineering roles, not PM roles,
# even when they also contain "product" or "AI" in the title. Excluded by default
# so a PM search doesn't get diluted with roles that were never going to fit.
_TITLE_EXCLUDE = [
    "software engineer",
    "product engineer",
    "backend engineer",
    "frontend engineer",
    "full-stack",
    "fullstack",
    "full stack",
    "devops",
    "architect",
    "developer",
    "data engineer",
    "ml engineer",
    "machine learning engineer",
    "qa engineer",
    "sre",
    "rails engineer",
    "staff engineer",
    "senior engineer",
]

_RUBRIC_TITLE_INFLATION_NOTE = (
    'Titles can be misleading — a "Product Manager" or "Staff Product Manager" '
    "title sometimes describes a hands-on technical/engineering role wearing a "
    "product-sounding name (check for signals like: owns architecture decisions, "
    'writes/reviews production code, "AI-native" tooling requirements aimed at '
    "engineers, reports into engineering rather than product)."
)

_RUBRIC_DIMENSIONS = """- Role/Skills match (gate: if this is weak, OR if the role's actual substance is
  technical/engineering despite a PM-sounding title, OR if it requires deep
  ML/infra depth the candidate doesn't have, the overall score has a CEILING of
  2.5 — not a fixed value of 2.5. Within that gated range, still use real
  judgment about how severe the specific gap is: a role with some tangential
  overlap (e.g., adjacent domain, transferable skills) can land higher within
  the range, around 2.0-2.5, while a role with no realistic alignment at all
  should land lower, around 1.0-1.5. Two different listings that fail the gate
  for two different reasons should very rarely produce the identical number —
  if they keep landing on exactly the same score, that's a sign of defaulting
  to a round anchor value instead of actually differentiating by severity.)
- Seniority fit (over- or under-leveled counts against it)
- Domain/industry relevance
- Location/remote feasibility given what the listing states"""

_PANEL_PERSONAS = [
    PanelPersona(
        role="Recruiter",
        criteria=(
            " — hard screens: years of experience, must-haves, location/comp signals, "
            "resume red flags, whether the resume survives a 30-second scan."
        ),
    ),
    PanelPersona(
        role="Hiring Manager",
        criteria=(
            " (Director of Product) — scope match, level match, domain relevance, "
            "whether this person can own the work on day one. Skeptical of title "
            "inflation and vague impact claims."
        ),
    ),
    PanelPersona(
        role="Engineering Lead",
        criteria=(
            " — technical fluency, how the candidate works with engineers, clear specs "
            "vs. throwing requirements over the wall."
        ),
    ),
    PanelPersona(
        role="Design Lead",
        criteria=(
            " — user empathy, collaboration with design, whether outcomes cited reflect "
            "user value or just shipped output."
        ),
    ),
    PanelPersona(
        role="Senior PM",
        criteria=(
            " (peer) — craft. Real product sense, prioritization under constraints, "
            "customer discovery, metrics fluency."
        ),
    ),
]

_TAILOR_ARCHETYPE_BLOCK = """ARCHETYPE DETECTION: classify the listing into one of these product-management
archetypes (or a hybrid of two), based on signals in the JD:
- AI Product Strategy — "roadmap", "vision", "0-to-1", "product strategy"
- Agentic/Automation Product — "agent", "automation", "workflow", "orchestration"
- AI Platform/Infrastructure PM — "data pipeline", "platform", "API", "developer tools"
- AI-Forward Growth/Creator Product — "community", "engagement", "creator", "retention"
- AI Marketplace/Two-Sided Platform — "marketplace", "supply/demand", "matching"
- AI Transformation/Enablement — "change management", "adoption", "enablement"

State the detected archetype, then let it inform which of the candidate's own
experience gets foregrounded: e.g. a Creator Product archetype should lead with
the Twitch/community work; a Marketplace archetype should lead with the
WarrantyPilot founder work; an Agentic/Automation archetype should lead with the
AI agent projects (Karla, Rudy, Brand Companion Agent)."""

PROFILE = RoleProfile(
    id="product_manager",
    display_name="Product Manager",
    title_include=_TITLE_INCLUDE,
    title_exclude=_TITLE_EXCLUDE,
    remotive_category="product",
    rubric_title_inflation_note=_RUBRIC_TITLE_INFLATION_NOTE,
    rubric_dimensions=_RUBRIC_DIMENSIONS,
    panel_personas=_PANEL_PERSONAS,
    tailor_archetype_block=_TAILOR_ARCHETYPE_BLOCK,
)
