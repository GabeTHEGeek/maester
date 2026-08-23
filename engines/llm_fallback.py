"""
llm_fallback.py
Wraps an Anthropic API call with an automatic fallback chain: DeepSeek
first, then Groq, when Anthropic returns a billing/credit error or times
out. Used by rubric_engine.py, panel_engine.py, and tailor_engine.py so all
three stages share one fallback path instead of three separate ad-hoc
implementations.

Groq is the third tier, tried only if DeepSeek also fails (or no DeepSeek
key is set) - real, free capacity (14,400 requests/day, no credit card,
plus a separate ~200,000-tokens/day cap confirmed directly - heavy testing
exhausted that token cap well before the request-count one)
meant to survive both an Anthropic billing hiccup AND a DeepSeek outage in
the same session, not to replace DeepSeek as the default fallback.

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

Billing/quota errors AND timeout/connection errors on the ANTHROPIC side
trigger the fallback. Any other kind of failure (a malformed request, a
truncated response) is re-raised untouched, so each engine's own existing
retry logic still runs exactly as it did before — this only adds a new
path, it doesn't change the old ones.

Explicit request timeout, shorter than the anthropic SDK's own default:
real evidence from actual use was a Deep Dive that just sat on "Fetching
listing and convening the panel..." with zero feedback — traced to the
SDK's default read timeout being 600 SECONDS (10 minutes), stacked with
its own default of 2 automatic retries on top of that. A slow or hung
request looked identical to a genuinely frozen app for up to half an hour
before anything even raised an exception for this module's own fallback
logic to catch. Cut to a real timeout so a stuck request fails fast enough
to actually fall over to DeepSeek instead of just sitting there.
"""

import json
import re
import time

import anthropic
import openai
from google import genai
from google.genai import types as genai_types

_BILLING_ERROR_MARKERS = [
    "credit balance is too low",
    "insufficient_quota",
    "billing",
]

# The anthropic SDK's own defaults (600s read timeout, 2 automatic retries)
# mean a single hung request can sit for up to ~30 minutes before this
# module's own fallback logic ever sees an exception to react to - confirmed
# directly this reads as a fully frozen app, not a slow one. 45s is generous
# for a real response (the deep-dive panel call, the largest of the three,
# typically finishes in single-digit seconds) while still failing fast
# enough that a genuinely stuck request falls over to DeepSeek in well under
# a minute rather than half an hour. max_retries=1 (not the SDK's default 2)
# keeps the worst case bounded to roughly 2x this timeout per provider, not 3x.
_REQUEST_TIMEOUT_SECONDS = 45.0
_MAX_SDK_RETRIES = 1

DEEPSEEK_BASE_URL = "https://api.deepseek.com/anthropic"
# deepseek-chat/deepseek-reasoner (the older, commonly-referenced names) were
# deprecated 2026-07-24. deepseek-v4-flash is the current non-thinking model.
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"

# OpenAI has no Anthropic-compatible endpoint (unlike DeepSeek), so it can't
# reuse the `anthropic` client the way DeepSeek does - it needs its own SDK
# and its own request/response shape (Chat Completions, not Messages).
# Mirrors the same two-tier split already used for Anthropic (Haiku for the
# cheap quick-scan rubric, Sonnet for everything expensive - Deep Dive,
# Tailor & Export, Auto-Fill's field mapping and question drafting):
# gpt-5.6-luna is OpenAI's current cost-optimized tier, gpt-5.6-sol its
# current flagship. Not wired into call_with_fallback's automatic fallback
# chain yet - call_openai() is a working, standalone call path, ready to be
# plugged in once it's decided how OpenAI should actually fit (a third
# fallback tier, a selectable primary, etc.), not a change to existing
# Anthropic-primary/DeepSeek-fallback behavior.
OPENAI_QUICK_MODEL = "gpt-5.6-luna"
OPENAI_MODEL = "gpt-5.6-sol"

# Gemini was tried before as a real fallback tier and dropped after hitting
# its free tier's request caps twice in actual use (5 req/min, then a hard
# 20 req/day ceiling - see the fallback-provider history above). Wired in
# again here ONLY as a standalone, unused call path (same treatment as
# OpenAI), never as an automatic fallback - the free tier's daily cap makes
# it unsuitable for that regardless of which model name is used.
GEMINI_DEFAULT_MODEL = "gemini-3.7-flash"

# Groq IS wired into the real fallback chain, unlike OpenAI/Gemini above -
# its free tier's 14,400-requests/day cap (confirmed via console.groq.com,
# 720x Gemini's 20/day ceiling that made Gemini unusable) comfortably covers
# a real batch scoring session instead of dying mid-search. Groq is
# OpenAI-compatible (same as DeepSeek reusing the `anthropic` client via a
# base_url swap, Groq reuses the `openai` client the same way), so it needs
# no separate SDK - just openai.OpenAI pointed at Groq's endpoint.
# openai/gpt-oss-120b is Groq's current flagship general-purpose model.
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"

# DeepSeek's paid tier has a 2,500-concurrent-request limit, so unlike the
# Gemini fallback this replaced, there's no need for aggressive cross-thread
# rate limiting — a short retry-with-backoff is enough for an occasional
# transient 429, not a structural requirement to avoid one entirely.
_MAX_RATE_LIMIT_RETRIES = 2
_DEFAULT_RETRY_DELAY_SECONDS = 5.0
_RETRY_DELAY_RE = re.compile(r"retry.{0,10}?(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


def _is_billing_error(exc: Exception) -> bool:
    return any(marker in str(exc).lower() for marker in _BILLING_ERROR_MARKERS)


def _is_timeout_or_connection_error(exc: Exception) -> bool:
    """A hung/slow/unreachable Anthropic endpoint is exactly the kind of
    failure DeepSeek fallback exists for, same as a billing error - the
    user doesn't care WHY the primary provider didn't answer, only that
    something did. Checks the SDK's own exception types first (reliable),
    falls back to a substring check on the message (covers wrapped/chained
    exceptions the SDK types don't catch)."""
    if isinstance(exc, (anthropic.APITimeoutError, anthropic.APIConnectionError)):
        return True
    message = str(exc).lower()
    return "timeout" in message or "timed out" in message


def _is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "429" in message or "rate_limit" in message or "resource_exhausted" in message


def _extract_retry_delay(exc: Exception) -> float:
    match = _RETRY_DELAY_RE.search(str(exc))
    if match:
        return float(match.group(1)) + 1.0  # small buffer past what it asked for
    return _DEFAULT_RETRY_DELAY_SECONDS


def extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response, tolerant of stray text/
    fences. Shared by rubric.py, panel.py, and tailor.py — each one's own
    prompt asks for JSON-only, but a prompt instruction is a request, not a
    guarantee (see CLAUDE.md), so all three parse defensively the same way
    rather than trusting the model's output format blindly."""
    text = text.strip()
    # Strip markdown code fences wherever they appear, not just at the very
    # start — Gemini (used as a fallback) sometimes adds a preamble sentence
    # before a fenced block, which a start-anchored check alone would miss.
    text = re.sub(r"```(json)?", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        snippet = text[:300] if text else "(empty response)"
        raise ValueError(f"No JSON object found in model response. Raw response started with: {snippet!r}")
    return json.loads(match.group(0))


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
    groq_api_key: str = "",
    groq_model: str = GROQ_DEFAULT_MODEL,
    temperature: float = 0.2,
    primary: str = "anthropic",
) -> tuple:
    """Returns (response_text, provider_used) where provider_used is
    "anthropic", "deepseek", or "groq" - whichever tier actually answered.

    `primary` picks which of the three goes first (a sidebar dropdown lets
    the user choose); the other two follow, in a fixed order, as fallback.
    The primary tier only falls through to the next one on a billing/credit
    or timeout/connection error - a malformed request or a genuinely bad
    response surfaces immediately rather than silently retrying on a
    different provider. Once past the primary, every subsequent tier falls
    through on ANY failure (rate-limit retries happen internally first) -
    by that point something real already went wrong, so there's no reason
    to gate further. If every configured tier fails, the ORIGINAL error
    from the FIRST tier actually tried is what surfaces, not whichever
    fallback failed last - that's the one that explains the real problem.

    Temperature defaults low (0.2, not the API default of ~1.0) because a
    hiring-fit score should mean the same thing if you run it on the same
    listing twice — real evidence from actual use showed the same URL
    scoring 72/64/72 across three deep-dive runs, and 85 vs 88 (crossing an
    actual recommendation-tier boundary) on another."""
    tiers = {
        "anthropic": (anthropic_api_key, anthropic_model, _try_anthropic),
        "deepseek": (deepseek_api_key, deepseek_model, _try_deepseek),
        "groq": (groq_api_key, groq_model, _try_groq),
    }
    order = [primary] + [t for t in ("anthropic", "deepseek", "groq") if t != primary]

    first_error = None
    for i, tier in enumerate(order):
        key, model, try_fn = tiers[tier]
        if not key:
            continue
        try:
            text = try_fn(system_prompt, user_prompt, key, model, max_tokens, temperature)
            return text, tier
        except Exception as e:
            if first_error is None:
                first_error = e
            is_primary_attempt = i == 0
            if is_primary_attempt and not (_is_billing_error(e) or _is_timeout_or_connection_error(e)):
                raise  # not a fallback-eligible failure - surface it immediately, don't mask it
            print(f"[llm_fallback] {tier} failed, trying next configured provider...", flush=True)

    if first_error is None:
        raise ValueError(f"No API key configured for any provider (tried: {order})")
    raise first_error


def _try_anthropic(system_prompt: str, user_prompt: str, api_key: str, model: str, max_tokens: int, temperature: float) -> str:
    client = anthropic.Anthropic(api_key=api_key, timeout=_REQUEST_TIMEOUT_SECONDS, max_retries=_MAX_SDK_RETRIES)
    _start = time.monotonic()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            temperature=temperature,
            messages=[{"role": "user", "content": user_prompt}],
        )
        elapsed = time.monotonic() - _start
        if elapsed > 20:
            print(f"[llm_fallback] Anthropic call succeeded but took {elapsed:.1f}s", flush=True)
        return _extract_text(response)
    except Exception as e:
        # Nothing was printed here before — a slow-but-working request and a
        # genuinely frozen one looked identical from the terminal, since this
        # exception was caught and handled silently. Real evidence from
        # actual use: a single Deep Dive took ~5 minutes wall time with zero
        # log output the entire way, impossible to tell apart from a hang
        # without adding this. `max_retries=1` above means the SDK may have
        # already silently retried once before this exception ever surfaces,
        # so the elapsed time here can already be ~2x the request timeout.
        elapsed = time.monotonic() - _start
        print(f"[llm_fallback] Anthropic call failed after {elapsed:.1f}s ({type(e).__name__}: {e})", flush=True)
        raise


def _try_deepseek(system_prompt: str, user_prompt: str, api_key: str, model: str, max_tokens: int, temperature: float) -> str:
    client = anthropic.Anthropic(
        api_key=api_key, base_url=DEEPSEEK_BASE_URL, timeout=_REQUEST_TIMEOUT_SECONDS, max_retries=_MAX_SDK_RETRIES
    )
    last_error = None
    for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
        _attempt_start = time.monotonic()
        try:
            response = client.messages.create(
                model=model,
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
            print(f"[llm_fallback] DeepSeek call succeeded after {time.monotonic() - _attempt_start:.1f}s (attempt {attempt + 1})", flush=True)
            return _extract_text(response)
        except Exception as e:
            last_error = e
            attempt_elapsed = time.monotonic() - _attempt_start
            print(f"[llm_fallback] DeepSeek attempt {attempt + 1} failed after {attempt_elapsed:.1f}s ({type(e).__name__}: {e})", flush=True)
            if not _is_rate_limit_error(e) or attempt == _MAX_RATE_LIMIT_RETRIES:
                raise
            delay = _extract_retry_delay(e)
            print(f"[llm_fallback] Rate limited, retrying in {delay:.1f}s...", flush=True)
            time.sleep(delay)
    raise last_error


def _try_groq(system_prompt: str, user_prompt: str, api_key: str, model: str, max_tokens: int, temperature: float) -> str:
    client = openai.OpenAI(api_key=api_key, base_url=GROQ_BASE_URL, timeout=_REQUEST_TIMEOUT_SECONDS, max_retries=_MAX_SDK_RETRIES)
    last_error = None
    for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
        _attempt_start = time.monotonic()
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                # Groq's gpt-oss models put reasoning in a separate field
                # BEFORE any real answer, same shape as DeepSeek's
                # thinking-mode bug - confirmed directly: a real Maester
                # call site (browser/fields.py's constrained-option
                # drafts, max_tokens=60) came back with 58 of 60 tokens
                # spent on hidden reasoning and EMPTY content. Unlike
                # Gemini (no working disable found), Groq/gpt-oss has a
                # real documented knob - reasoning_effort="low" cut
                # reasoning to 19 tokens on the same prompt and let the
                # real answer through within the same tight budget.
                #
                # Also confirmed directly (scripts/eval_groq_reasoning_effort.py):
                # raising this to "medium" with a 2000-token budget did NOT
                # reduce the score instability found in
                # scripts/eval_groq_vs_deepseek.py (6/10 grade flips across 3
                # identical runs, both at "low" and "medium") - so "low" is
                # kept here since it's cheaper and equally (un)reliable, not
                # because it's the cause of that instability. The instability
                # itself looks real to gpt-oss-120b on this task, not an
                # artifact of a suppressed reasoning budget.
                reasoning_effort="low",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError(f"Empty content in Groq response: {response!r}")
            print(f"[llm_fallback] Groq call succeeded after {time.monotonic() - _attempt_start:.1f}s (attempt {attempt + 1})", flush=True)
            return content
        except Exception as e:
            last_error = e
            attempt_elapsed = time.monotonic() - _attempt_start
            print(f"[llm_fallback] Groq attempt {attempt + 1} failed after {attempt_elapsed:.1f}s ({type(e).__name__}: {e})", flush=True)
            if not _is_rate_limit_error(e) or attempt == _MAX_RATE_LIMIT_RETRIES:
                raise
            delay = _extract_retry_delay(e)
            print(f"[llm_fallback] Rate limited, retrying in {delay:.1f}s...", flush=True)
            time.sleep(delay)
    raise last_error


def call_openai(
    system_prompt: str,
    user_prompt: str,
    openai_api_key: str,
    model: str = OPENAI_MODEL,
    max_tokens: int = 1000,
    temperature: float = 0.2,
) -> str:
    """Standalone OpenAI call, separate from call_with_fallback since OpenAI
    needs its own SDK and request/response shape (Chat Completions, not the
    Anthropic Messages format DeepSeek's compatible endpoint reuses). Not
    invoked from anywhere in the app yet - this exists so the call path is
    real and tested, ready to be wired into a specific provider strategy
    (fallback tier, selectable primary, etc.) once that's decided, same
    temperature default as the Anthropic path for the same reason (a score
    should mean the same thing run twice)."""
    client = openai.OpenAI(api_key=openai_api_key, timeout=_REQUEST_TIMEOUT_SECONDS, max_retries=_MAX_SDK_RETRIES)
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError(f"Empty content in OpenAI response: {response!r}")
    return content


def call_gemini(
    system_prompt: str,
    user_prompt: str,
    gemini_api_key: str,
    model: str = GEMINI_DEFAULT_MODEL,
    max_tokens: int = 2000,
    temperature: float = 0.2,
) -> str:
    """Standalone Gemini call, same treatment as call_openai above - wired
    in and working, but not part of call_with_fallback's automatic fallback
    chain. Deliberately kept out of that chain: Gemini was the ORIGINAL
    fallback provider here and was dropped specifically because its free
    tier's request caps (5/min, then 20/day) made it fail mid-session on
    real usage - re-adding it as an automatic fallback would just walk back
    into the same problem, regardless of which model name is current.

    thinking_budget=0 is passed to try to disable extended reasoning, same
    intent as DeepSeek's thinking={"type": "disabled"} - but confirmed
    directly this model does NOT fully honor it: a max_tokens=20 call still
    spent 99 tokens on invisible "thoughts" before any real output and came
    back completely empty, identical in shape to the DeepSeek thinking-mode
    bug this project already hit once (see CLAUDE.md). Unlike DeepSeek,
    there's no way found so far to fully turn it off, so the default here is
    set generously (2000, not 1000) to leave room for both the reasoning
    tokens AND the actual answer - a caller passing a small max_tokens for a
    short answer should still pass a real one, not assume 1:1 like the other
    two providers."""
    client = genai.Client(api_key=gemini_api_key)
    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config=genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
            temperature=temperature,
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
        ),
    )
    if not response.text:
        raise ValueError(f"Empty text in Gemini response: {response!r}")
    return response.text
