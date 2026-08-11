"""
role_profiles/account_executive.py
Third role profile, same standard as product_manager.py/customer_success.py -
real title filters, a real rubric gate, a distinct 5-person panel, and real
tailoring archetypes, not a stub.

Written with this candidate's actual situation in mind: no formal
quota-carrying sales title on the resume, but real founder-stage revenue
generation, partnership/deal-making, and customer-facing negotiation
experience. Same approach as customer_success.py - judge that substance on
its own merits in the prompt text, while still naming real gaps (no formal
quota ownership, no closed-deal count, no CRM pipeline-forecasting
experience) plainly rather than glossing over them.
"""

from role_profiles.base import PanelPersona, RoleProfile

_TITLE_INCLUDE = [
    "account executive",
    "ae",
    "enterprise account executive",
    "mid-market account executive",
    "smb account executive",
    "strategic account executive",
    "senior account executive",
    "account manager",
    "sales executive",
    "territory account executive",
    "new business account executive",
    "commercial account executive",
]

# Titles sharing "account"/"sales" words but describing a genuinely
# different job: reactive support, cold-outbound prospecting-only roles, or
# a pure customer-success/renewal role wearing adjacent language.
_TITLE_EXCLUDE = [
    "customer success manager",
    "customer success",
    "csm",
    "customer service representative",
    "customer support",
    "sales development representative",
    "business development representative",
    "sdr",
    "bdr",
    "account coordinator",
    "accounts payable",
    "accounts receivable",
    "key account support",
]

_RUBRIC_TITLE_INFLATION_NOTE = (
    'Titles can be misleading — an "Account Executive" title sometimes describes '
    "a pure outbound-prospecting role with no real closing authority or quota "
    'ownership, or conversely a "Customer Success"/"Account Manager" label that '
    "actually carries a hard renewal/expansion quota (check for signals like: "
    "whether the role owns a number and a quota, whether it's full-cycle "
    "(source-to-close) or closing-only, what the sales motion actually is "
    "(inbound vs. outbound, transactional vs. enterprise/multi-stakeholder))."
)

_RUBRIC_DIMENSIONS = """- Role/Skills match (gate: if the listing requires a formal quota-carrying
  sales track record, a specific CRM/sales-tooling depth (Salesforce, Outreach,
  Gong, Clari) the candidate has never actually worked with, or full-cycle
  enterprise deal experience the candidate hasn't done, the overall score has a
  CEILING of 2.5 — not a fixed value. A candidate without a formal "Account
  Executive" title but with real revenue-generation, partnership/deal-making,
  or customer-facing negotiation work (common in founder/PM backgrounds)
  should be judged on that SUBSTANCE, not penalized for the title alone — but
  genuine gaps (no formal quota ownership, no closed-deal count, no CRM
  pipeline-forecasting experience) still count against fit and should be named
  plainly, not glossed over. Within the gated range, differentiate by severity
  the same way as any other listing — don't default to a round anchor score.)
- Seniority fit (over- or under-leveled counts against it)
- Domain/industry relevance
- Location/remote feasibility given what the listing states"""

_PANEL_PERSONAS = [
    PanelPersona(
        role="Recruiter",
        criteria=(
            " — hard screens: years of quota-carrying or revenue-generating "
            "experience, must-haves, location/comp signals, resume red flags, "
            "whether the resume survives a 30-second scan."
        ),
    ),
    PanelPersona(
        role="VP of Sales",
        criteria=(
            " — scope match, level match, whether this person can run a full "
            "sales cycle and carry a quota on day one. Skeptical of title "
            "inflation and vague \"drove revenue\" claims without real numbers."
        ),
    ),
    PanelPersona(
        role="Senior Account Executive",
        criteria=(
            " (peer) — craft: discovery quality, negotiation rigor, how deals "
            "were actually sourced and closed, multi-stakeholder/enterprise "
            "deal handling versus purely transactional selling."
        ),
    ),
    PanelPersona(
        role="Sales Ops Stakeholder",
        criteria=(
            " — whether the candidate has actually owned or directly "
            "influenced a quota/pipeline number with real forecasting "
            "discipline, or only adjacent activity metrics (calls, meetings "
            "booked) without revenue accountability."
        ),
    ),
    PanelPersona(
        role="Customer Reference",
        criteria=(
            " — how this person would actually come across to a prospect: "
            "trustworthiness, consultative vs. pushy selling style, whether "
            "cited outcomes reflect genuine customer value or pure quota "
            "chasing."
        ),
    ),
]

_TAILOR_ARCHETYPE_BLOCK = """ARCHETYPE DETECTION: classify the listing into one of these Account Executive
archetypes (or a hybrid of two), based on signals in the JD:
- Enterprise/Strategic AE — "enterprise", "strategic accounts", "multi-stakeholder", "long sales cycle"
- Mid-Market/SMB AE — "mid-market", "SMB", "transactional", "high-velocity"
- Full-Cycle AE — "full-cycle", "source to close", "prospecting and closing"
- Closing-Only AE — "qualified pipeline provided", "closing", "SDR-sourced leads"
- Partnerships/Channel AE — "partnerships", "channel", "co-sell", "reseller"

State the detected archetype, then let it inform which of the candidate's own
experience gets foregrounded — even where the candidate's formal title wasn't
"Account Executive." Surface genuinely revenue-generating, deal-making, or
customer-facing negotiation work honestly as what it actually was (e.g., a
founder role that included raising funding, closing partnerships, or
negotiating commercial terms), never reframed as an AE title or quota the
candidate didn't hold — the same no-fabrication rule applies here as
everywhere else."""

PROFILE = RoleProfile(
    id="account_executive",
    display_name="Account Executive",
    title_include=_TITLE_INCLUDE,
    title_exclude=_TITLE_EXCLUDE,
    # Remotive's own category list (confirmed against product_manager.py's
    # equivalent check) has "Sales" as a real category - use it rather than
    # relying on title_include/title_exclude alone the way customer_success.py
    # has to (Remotive has no CS-shaped category).
    remotive_category="sales",
    rubric_title_inflation_note=_RUBRIC_TITLE_INFLATION_NOTE,
    rubric_dimensions=_RUBRIC_DIMENSIONS,
    panel_personas=_PANEL_PERSONAS,
    tailor_archetype_block=_TAILOR_ARCHETYPE_BLOCK,
)
