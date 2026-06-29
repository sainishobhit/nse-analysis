"""
ai_analyst.py — On-demand AI stock analysis using Claude.

What it does: takes a stock's factor scores, recent price action, sector, news
sentiment/events, and any user holding info, and asks Claude for a structured
plain-English read. Returns: a 2-3 sentence summary, key strengths, key risks,
a recommendation tag (BUY_WATCH / HOLD / TRIM / AVOID), and a confidence note.

What it ISN'T: a price predictor. The model SYNTHESIZES the data the system
already computed — it doesn't see the future and won't tell you "this will go
up." The verbal output sits alongside the numeric scores so you can see both.

Cost: Claude Haiku 4.5 (~₹0.25-0.30 per analysis at typical sizes). Tracked.
Caching: results cached for 1 hour per (symbol, score-hash) so repeated taps
don't re-hit the API.

API key: read from environment variable ANTHROPIC_API_KEY. NEVER stored in
code or in the repo. Use a `.env` file (gitignored).
"""

from __future__ import annotations
import os
import json
import hashlib
import time
from datetime import datetime, timezone

# Lazy import: only require `anthropic` package if AI is used.
_client_cache = None


def _get_client():
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError(
            "The `anthropic` Python package isn't installed. "
            "Run: pip install anthropic"
        )
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        # also check Streamlit secrets if available
        try:
            import streamlit as st
            key = st.secrets.get("ANTHROPIC_API_KEY", "").strip()
        except Exception:
            pass
    if not key:
        raise RuntimeError(
            "No ANTHROPIC_API_KEY found. Add it to a `.env` file in the project "
            "root OR set it as an environment variable. Get a key at "
            "https://console.anthropic.com"
        )
    _client_cache = Anthropic(api_key=key)
    return _client_cache


# Default model: Haiku 4.5 — fast and cheap, ideal for short analyses.
# Override with model="claude-sonnet-4-6" for deeper reads at ~3x cost.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


SYSTEM_PROMPT = """You are a careful, candid Indian-market analyst inside a quantitative trading app. You analyse one NSE stock at a time using the structured data the user provides.

RULES, NON-NEGOTIABLE:
- You synthesize the given data only. You do NOT predict prices.
- You do NOT give financial advice; you give a structured READ that helps the user decide.
- If the data is thin or conflicting, say so. Confidence > confident-sounding.
- Be brief. The user is looking at this on a phone or laptop dashboard.
- Mention India-specific context where relevant (sector, regulatory, tax — STCG/LTCG).
- NEVER invent news or fundamentals not in the input. If sentiment/news fields are empty, say "no news in window."

Return STRICT JSON in this exact shape:
{
  "summary": "<2-3 sentence plain-English read of the stock's current state>",
  "strengths": ["<bullet>", "<bullet>", ...],
  "risks": ["<bullet>", "<bullet>", ...],
  "recommendation": "<one of: BUY_WATCH | HOLD | TRIM | AVOID>",
  "confidence": "<low | medium | high>",
  "rationale": "<one sentence on WHY this recommendation given the data>"
}

No markdown, no preamble. Just the JSON object."""


def _hash_inputs(payload: dict) -> str:
    s = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


# In-memory cache: { (symbol, hash): (timestamp, result) }
_CACHE: dict = {}
CACHE_TTL_SECONDS = 3600  # 1 hour


def analyze_stock(
    symbol: str,
    factor_row: dict | None = None,   # final_score, tactical_score, structural_score, rsi, etc.
    price_summary: dict | None = None, # ltp, change_pct, 52w_high, 52w_low, etc.
    sector: str | None = None,
    news_signal: dict | None = None,   # news_sentiment, news_buzz, news_events, news_top
    holding: dict | None = None,       # entry_price, shares, days_held (optional)
    model: str = DEFAULT_MODEL,
    use_cache: bool = True,
) -> dict:
    """
    Run a Claude analysis on one stock. Returns a dict with the structured
    output plus metadata (model, cost estimate, cached flag).
    """
    payload = {
        "symbol": symbol.upper(),
        "factors": factor_row or {},
        "price": price_summary or {},
        "sector": sector,
        "news": news_signal or {},
        "holding": holding or {},
    }

    cache_key = (symbol.upper(), _hash_inputs(payload))
    if use_cache and cache_key in _CACHE:
        ts, cached = _CACHE[cache_key]
        if time.time() - ts < CACHE_TTL_SECONDS:
            cached_copy = dict(cached)
            cached_copy["cached"] = True
            try:
                from . import ai_usage
                ai_usage.log_call(symbol, cached.get("model", model),
                                  0, 0, 0.0, cached=True)
            except Exception:
                pass
            return cached_copy

    try:
        client = _get_client()
    except RuntimeError as e:
        return {"error": str(e)}

    user_prompt = (
        f"Analyse this NSE stock. Return ONLY the JSON object as specified.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=800,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        try:
            from . import ai_usage
            ai_usage.log_call(symbol, model, 0, 0, 0.0, cached=False, error=str(e))
        except Exception:
            pass
        return {"error": f"API call failed: {e}"}

    # extract text
    text = ""
    for block in resp.content:
        if hasattr(block, "text"):
            text += block.text

    # parse JSON (defensive — strip code fences if model added them)
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1] if "```" in cleaned[3:] else cleaned[3:]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"error": "Couldn't parse model response as JSON.",
                "raw": text[:500]}

    # cost estimate (very rough; based on usage if available)
    usage = getattr(resp, "usage", None)
    in_tok = getattr(usage, "input_tokens", 0) if usage else 0
    out_tok = getattr(usage, "output_tokens", 0) if usage else 0
    # Haiku 4.5 pricing: $1/M input, $5/M output. Convert to INR at ~83.
    cost_usd = (in_tok * 1.0 + out_tok * 5.0) / 1_000_000
    cost_inr = cost_usd * 83.0

    result = {
        **parsed,
        "model": model,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_estimate_inr": round(cost_inr, 3),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }

    _CACHE[cache_key] = (time.time(), result)

    try:
        from . import ai_usage
        ai_usage.log_call(symbol, model, in_tok, out_tok, cost_inr, cached=False)
    except Exception:
        pass

    return result


def is_configured() -> bool:
    """True if ANTHROPIC_API_KEY is set (in env or Streamlit secrets)."""
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return True
    try:
        import streamlit as st
        return bool(st.secrets.get("ANTHROPIC_API_KEY", "").strip())
    except Exception:
        return False
