"""
role_profiles/customer_success.py
Second role profile, added to make Maester's search/scoring/panel/tailoring
flexible beyond Product Manager roles. Written to the same standard as
product_manager.py, not a stub - real title filters, a real rubric gate,
a distinct 5-person panel, and real tailoring archetypes.

Written with this candidate's actual situation in mind: mostly PM/founder
experience, no formal "Customer Success" title on the resume. That's
handled the same way every other honesty constraint in this project is -
in the prompt text itself, not by softening the panel's judgment. The
rubric gate and panel personas below are written to judge transferable,
genuinely customer-facing substance on its own merits, while still naming
real gaps (no quota/renewal ownership, no CS-specific tooling experience)
plainly rather than glossing over them.
"""

from role_profiles.base import PanelPersona, RoleProfile

_TITLE_INCLUDE = [
    "customer success manager",
    "customer success",
    "csm",
    "customer success lead",
    "head of customer success",
    "director of customer success",
    "vp of customer success",
    "vp, customer success",
    "client success manager",
    "client success",
    "customer success director",
    "chief customer officer",
    "renewal manager",
    "customer success operations",
    "customer success ops",
]

# Titles sharing "customer"/"success"/"account" words but describing a
# genuinely different job: reactive support-ticket handling, cold-outbound
# sales, or a pure account-executive quota role wearing adjacent language.
_TITLE_EXCLUDE = [
    "customer service representative",
    "customer service agent",
    "customer support",
    "technical support engineer",
    "support engineer",
    "help desk",
    "call center",
    "sales development representative",
    "account executive",
    "business development representative",
    "field service",
]

_RUBRIC_TITLE_INFLATION_NOTE = (
    'Titles can be misleading — a "Customer Success Manager" title sometimes '
    "describes a pure support/ticket-queue role with no real account ownership "
    'or renewal responsibility, or conversely a quota-carrying sales/renewals '
    'role wearing a "success" label instead of "Account Executive" (check for '
    "signals like: whether the role owns a renewal/expansion number, whether it "
    'reports into Sales vs. a dedicated CS org, whether "success" work is really '
    "reactive support metrics like ticket volume/CSAT rather than proactive "
    "account health and growth)."
)

_RUBRIC_DIMENSIONS = """- Role/Skills match (gate: if the listing requires direct book-of-business
  ownership, quota/renewal-number accountability, or CS-specific tooling depth
  (Gainsight, Vitally, Catalyst, ChurnZero) the candidate has never actually
  worked with, OR if the role's real substance is pure support-ticket handling
  with no account-management scope, the overall score has a CEILING of 2.5 —
  not a fixed value. A candidate without a formal "Customer Success" title but
  with real customer-facing account ownership, retention-relevant metrics, or
  cross-functional account work (common in founder/PM backgrounds) should be
  judged on that SUBSTANCE, not penalized for the title alone — but genuine
  gaps (no quota ownership, no renewal-number accountability, no CS-specific
  tooling experience) still count against fit and should be named plainly, not
  glossed over. Within the gated range, differentiate by severity the same way
  as any other listing — don't default to a round anchor score.)
- Seniority fit (over- or under-leveled counts against it)
- Domain/industry relevance
- Location/remote feasibility given what the listing states"""

_PANEL_PERSONAS = [
    PanelPersona(
        role="Recruiter",
        criteria=(
            " — hard screens: years of customer-facing/account-ownership experience, "
            "must-haves, location/comp signals, resume red flags, whether the "
            "resume survives a 30-second scan."
        ),
    ),
    PanelPersona(
        role="VP of Customer Success",
        criteria=(
            " — scope match, level match, whether this person can own a book of "
            "business or segment on day one. Skeptical of title inflation and "
            "vague retention claims."
        ),
    ),
    PanelPersona(
        role="CS Team Lead",
        criteria=(
            " (peer) — craft: QBR quality, health-score/account-planning rigor, "
            "escalation handling, cross-functional coordination with Sales/"
            "Product/Support."
        ),
    ),
    PanelPersona(
        role="Renewals Stakeholder",
        criteria=(
            " — whether the candidate has actually owned or directly influenced a "
            "renewal/expansion/NRR number, or only adjacent support metrics "
            "(ticket volume, CSAT) without revenue accountability."
        ),
    ),
    PanelPersona(
        role="Support Ops Lead",
        criteria=(
            " — CS tooling fluency (Gainsight/Vitally/Catalyst-type platforms), "
            "process rigor, whether outcomes cited reflect systemic process "
            "improvement or one-off firefighting."
        ),
    ),
]

_TAILOR_ARCHETYPE_BLOCK = """ARCHETYPE DETECTION: classify the listing into one of these Customer Success
archetypes (or a hybrid of two), based on signals in the JD:
- Retention & Renewals CSM — "renewal", "retention", "churn", "NRR", "expansion"
- Technical/Onboarding CSM — "onboarding", "implementation", "technical", "integration"
- Enterprise/Strategic Account CSM — "enterprise", "strategic accounts", "executive relationships"
- Scaled/Digital CS — "scaled", "digital-led", "1:many", "automation", "playbooks"
- CS Operations/Systems — "CS ops", "tooling", "Gainsight", "health scores", "reporting"

State the detected archetype, then let it inform which of the candidate's own
experience gets foregrounded — even where the candidate's formal title wasn't
"Customer Success." Surface genuinely customer-facing, retention-relevant, or
account-management work honestly as what it actually was (e.g., a PM or
founder role that included direct customer relationships, renewal
conversations, or account health ownership), never reframed as a CS title the
candidate didn't hold — the same no-fabrication rule applies here as
everywhere else."""

PROFILE = RoleProfile(
    id="customer_success",
    display_name="Customer Success",
    title_include=_TITLE_INCLUDE,
    title_exclude=_TITLE_EXCLUDE,
    # Remotive has no Customer Success category (confirmed against its real
    # category list: Product Management, Sales, Design, Devops, Data and
    # Analytics, Marketing, Medical, Information Technology, Software
    # Development, Writing, All others - nothing CS-shaped) - None means
    # "all categories," relying on title_include/title_exclude to do the
    # real filtering instead of a mismatched category guess.
    remotive_category=None,
    rubric_title_inflation_note=_RUBRIC_TITLE_INFLATION_NOTE,
    rubric_dimensions=_RUBRIC_DIMENSIONS,
    panel_personas=_PANEL_PERSONAS,
    tailor_archetype_block=_TAILOR_ARCHETYPE_BLOCK,
)
