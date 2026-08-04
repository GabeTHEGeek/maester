"""
role_profiles/base.py
The shape every role profile must provide. A role profile is everything
that changes about Maester when the user is searching for a different KIND
of role (Product Manager vs. Customer Success vs. whatever gets added
next) - the four things that used to be hardcoded PM-only:

1. Search title filtering (title_include/title_exclude) - which listings
   even count as "this kind of role" in the first place, shared by every
   job source (Remotive, Greenhouse, Ashby, Gem, Lever, BambooHR).
2. Rubric (quick-scan) framing - what "good fit" means as scoring
   dimensions, fed into the fast Haiku triage pass.
3. Deep-dive panel personas - who's actually on the simulated hiring
   panel. A Senior PM peer and a Design Lead make sense for evaluating a
   PM candidate; they don't for a Customer Success candidate, so the
   panel itself needs to change, not just get relabeled.
4. Tailoring archetypes - how the resume/cover-letter generator
   classifies a listing and decides what to foreground.

Deliberately NOT part of a role profile: anything about the CANDIDATE
themselves (their actual AI experience, their real projects, their
resume). That context is the same person regardless of which role type
they're being evaluated against this search, so it stays in the shared
base prompts in engines/rubric.py, engines/panel.py, and engines/tailor.py
rather than being duplicated per profile.

To add a new role type: create role_profiles/<name>.py exporting a
`PROFILE = RoleProfile(...)`, then register it in role_profiles/__init__.py's
_PROFILES dict. Nothing else needs to change - app.py and all three engines
read everything through this shape.
"""

from dataclasses import dataclass, field


@dataclass
class PanelPersona:
    """One seat on the simulated hiring panel. `role` is both the display
    name and the JSON schema key the model is asked to use, so keep it
    short and stable - changing it after real evaluations have been logged
    means old tracker.csv rows show the old name.

    `criteria` is appended directly after `role` with no separator added in
    between (e.g. "1. {role}{criteria}") - it must supply its own leading
    space and punctuation, e.g. " — hard screens: ..." or
    " (Director of Product) — scope match, ...". This is so a persona with
    a parenthetical qualifier ("(peer)", "(Director of Product)") reads
    naturally instead of getting a second, redundant em dash inserted
    before it."""

    role: str
    criteria: str


@dataclass
class RoleProfile:
    id: str
    display_name: str

    # Search filtering - shared verbatim by every job source.
    title_include: list = field(default_factory=list)
    title_exclude: list = field(default_factory=list)

    # Remotive's own category tag is a soft, Remotive-only preference (see
    # sources/remotive.py) - not every role type maps cleanly onto one of
    # Remotive's actual categories ('product', 'project-management',
    # 'all-others', etc.), so this can be None ("all categories," rely on
    # title_include/title_exclude to do the real filtering).
    remotive_category: str = None

    # Rubric (quick-scan) framing.
    rubric_title_inflation_note: str = ""
    rubric_dimensions: str = ""

    # Deep-dive panel - Recruiter first by convention (fastest hard-screen
    # read), same ordering rule applied in engines/panel.py regardless of
    # which profile is active.
    panel_personas: list = field(default_factory=list)

    # Tailoring - the full "ARCHETYPE DETECTION" section text, including
    # the foregrounding guidance sentence, since for this candidate that
    # guidance is itself part of what's role-specific (which real
    # experience gets surfaced first depends on what kind of role this is).
    tailor_archetype_block: str = ""

    @property
    def panelist_order(self) -> list:
        return [p.role for p in self.panel_personas]
