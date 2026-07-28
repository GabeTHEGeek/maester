"""
llm_fallback.py
Wraps an Anthropic API call with an automatic fallback to DeepSeek when
Anthropic returns a billing/credit error. Used by rubric_engine.py,
panel_engine.py, and tailor_engine.py so all three stages share one
fallback path instead of three separate ad-hoc implementations.

Switched from Gemini after hitting its free-tier limits twice in real use —
first 5 requests/minute, then a 20-requests/day cap on gemini-3.6-flash that
made it impractical for any real batch scoring session. DeepSeek's paid tier
costs a fraction of a cent per call (roughly $0.0008 for a typical scoring
call at current pricing) and has a 2,500-concurrent-request limit, which
comfortably covers Maester's actual usage pattern without needing the
aggressive rate limiting and daily-quota special-casing the Gemini fallback
needed.

DeepSeek exposes an Anthropic-format-compatible endpoint
(api.deepseek.com/anthropic), so the fallback reuses the exact same
`anthropic` client and request/response shape as the primary call, just
pointed at a different base_url with a different key and model — no
separate SDK, unlike the Gemini integration this replaces.

Only billing/quota errors on the ANTHROPIC side trigger the fallback. Any
other kind of failure (a malformed request, a truncated response, a network
blip) is re-raised untouched, so each engine's own existing retry logic
still runs exactly as it did before — this only adds a new path, it doesn't
change the old ones.
"""

import re
import time

import anthropic

_BILLING_ERROR_MARKERS = [
    "credit balance is too low",
    "insufficient_quota",
    "billing",
]

DEEPSEEK_BASE_URL = "https://api.deepseek.com/anthropic"
# deepseek-chat/deepseek-reasoner (the older, commonly-referenced names) were
# deprecated 2026-07-24. deepseek-v4-flash is the current non-thinking model.
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"

# DeepSeek's paid tier has a 2,500-concurrent-request limit, so unlike the
# Gemini fallback this replaced, there's no need for aggressive cross-thread
# rate limiting — a short retry-with-backoff is enough for an occasional
# transient 429, not a structural requirement to avoid one entirely.
_MAX_RATE_LIMIT_RETRIES = 2
_DEFAULT_RETRY_DELAY_SECONDS = 5.0
_RETRY_DELAY_RE = re.compile(r"retry.{0,10}?(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


def _is_billing_error(exc: Exception) -> bool:
    return any(marker in str(exc).lower() for marker in _BILLING_ERROR_MARKERS)


def _is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "429" in message or "rate_limit" in message or "resource_exhausted" in message


def _extract_retry_delay(exc: Exception) -> float:
    match = _RETRY_DELAY_RE.search(str(exc))
    if match:
        return float(match.group(1)) + 1.0  # small buffer past what it asked for
    return _DEFAULT_RETRY_DELAY_SECONDS


def _extract_text(response) -> str:
    """Anthropic-format responses can include non-text content blocks (e.g.
    a ThinkingBlock, if the model does visible reasoning before its answer)
    ahead of the actual text block. DeepSeek's Anthropic-compatible endpoint
    does this even for its non-"thinking" model name. Find the real text
    block instead of assuming content[0] always is one."""
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    raise ValueError(f"No text block found in response content: {response.content!r}")


def call_with_fallback(
    system_prompt: str,
    user_prompt: str,
    anthropic_api_key: str,
    anthropic_model: str,
    max_tokens: int,
    deepseek_api_key: str = "",
    deepseek_model: str = DEEPSEEK_DEFAULT_MODEL,
    temperature: float = 0.2,
) -> tuple:
    """Returns (response_text, provider_used) where provider_used is
    "anthropic" or "deepseek". Tries Anthropic first; on a billing/credit
    error, falls back to DeepSeek (via its Anthropic-compatible endpoint) if
    a key was provided. If it's a billing error and no DeepSeek key is set,
    the original error is re-raised so the user still sees the real problem
    instead of a confusing new one.

    Temperature defaults low (0.2, not the API default of ~1.0) because a
    hiring-fit score should mean the same thing if you run it on the same
    listing twice — real evidence from actual use showed the same URL
    scoring 72/64/72 across three deep-dive runs, and 85 vs 88 (crossing an
    actual recommendation-tier boundary) on another."""
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    try:
        response = client.messages.create(
            model=anthropic_model,
            max_tokens=max_tokens,
            system=system_prompt,
            temperature=temperature,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return _extract_text(response), "anthropic"
    except Exception as e:
        if not _is_billing_error(e) or not deepseek_api_key:
            raise

    deepseek_client = anthropic.Anthropic(api_key=deepseek_api_key, base_url=DEEPSEEK_BASE_URL)
    last_error = None
    for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
        try:
            response = deepseek_client.messages.create(
                model=deepseek_model,
                max_tokens=max_tokens,
                system=system_prompt,
                temperature=temperature,
                # DeepSeek's "flash" vs "thinking" distinction isn't actually
                # two different models — it's the same model name gated by
                # this parameter, and it defaults to ENABLED if omitted. Left
                # on, the model spends the entire max_tokens budget on visible
                # reasoning and never reaches the actual answer at all (seen
                # directly: a response containing only a ThinkingBlock, no
                # text block whatsoever). Explicitly disabling it is the
                # documented, tested way to get a direct answer instead.
                thinking={"type": "disabled"},
                messages=[{"role": "user", "content": user_prompt}],
            )
            return _extract_text(response), "deepseek"
        except Exception as e:
            if not _is_rate_limit_error(e) or attempt == _MAX_RATE_LIMIT_RETRIES:
                raise
            last_error = e
            time.sleep(_extract_retry_delay(e))

    raise last_error
