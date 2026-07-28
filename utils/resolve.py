"""
resolve.py
On-demand cross-platform fallback: when a company fails on whichever
platform it was searched under, try the other supported platforms before
giving up. Only runs for companies actually selected in a real search
(naturally capped by the existing 20-per-platform UI limit) — never a
proactive bulk scan of the whole registry. This resolves your actual
working set as you use it, rather than spending ~15,000+ requests up front
resolving companies you may never search.
"""

from sources.ashby import search_ashby
from sources.gem import search_gem
from sources.greenhouse import search_greenhouse
from sources.lever import search_lever

_SEARCH_FUNCS = {
    "greenhouse": search_greenhouse,
    "ashby": search_ashby,
    "gem": search_gem,
    "lever": search_lever,
}


def resolve_cross_platform(
    failed_by_platform: dict,
    query: str,
    limit: int,
    exclude_titles: list = None,
    require_title_keywords: list = None,
) -> tuple:
    """
    failed_by_platform: {platform: [tokens that failed on it this search]}

    Returns (extra_jobs, resolutions) where resolutions is
    {token: {"platform": str|None, "status": "resolved"|"failed_all"}}.
    A token that failed on one platform gets tried on every OTHER supported
    platform it wasn't already tried on this search, stopping at the first
    one that actually has it (a non-empty postings fetch, regardless of
    whether any posting happens to match the search query's title filter).
    """
    extra_jobs = []
    resolutions = {}

    tried_platforms_by_token = {}
    for platform, tokens in failed_by_platform.items():
        for token in tokens:
            tried_platforms_by_token.setdefault(token, set()).add(platform)

    for token, tried in tried_platforms_by_token.items():
        remaining = [p for p in _SEARCH_FUNCS if p not in tried]
        resolved = False

        for platform in remaining:
            search_fn = _SEARCH_FUNCS[platform]
            try:
                jobs, meta = search_fn(
                    query,
                    boards=[token],
                    limit=limit,
                    exclude_titles=exclude_titles,
                    require_title_keywords=require_title_keywords,
                )
            except Exception:
                tried.add(platform)
                continue

            tried.add(platform)
            if token in meta.get("boards_checked", []):
                extra_jobs.extend(jobs)
                resolutions[token] = {"platform": platform, "status": "resolved"}
                resolved = True
                break

        if resolved:
            resolutions[token]["platforms_tried"] = sorted(tried)
        else:
            resolutions[token] = {"platform": None, "status": "failed_all", "platforms_tried": sorted(tried)}

    return extra_jobs, resolutions
