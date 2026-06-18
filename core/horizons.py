"""
horizons.py — Investment horizon profiles.

Maps three human timeframes onto concrete strategy settings. The same universe
and factors are reused, but WHAT MATTERS changes with how long you intend to
hold. Short-term cares about momentum and entry timing; long-term cares about
trend durability and riding winners through noise.

  SHORT   (< 3 months)        → tactical-led, tight management, quick exits
  MEDIUM  (3 months – 1 year) → balanced, trend-following
  LONG    (1 – 2+ years)      → structural-led, wide stops, let winners run

Each profile drives: scoring horizon, recommended stop/target style, rebalance
cadence, and a plain-English "what good looks like" so the user knows how to
read the output for THEIR timeframe.
"""

from __future__ import annotations

PROFILES = {
    "short": {
        "label": "Short-term",
        "window": "Less than 3 months",
        "scoring_horizon": "tactical",   # momentum/volume/RSI dominate
        "hold_days": 21,                 # ~1 month typical hold
        "rebalance": "Weekly — check entries/exits often",
        "atr_stop_mult": 2.0,            # tighter stop
        "reward_mult": 2.0,
        "min_turnover_cr": 3.0,          # need liquidity for quick in/out
        "require_above_ema200": False,
        "what_good_looks_like": (
            "Strong recent momentum (5–21 day), a volume surge, RSI in the "
            "50–70 sweet spot, price above its 20-EMA, and near a breakout. "
            "You're renting the move, not marrying the stock."
        ),
        "watch_out": (
            "Costs and taxes hurt most here (STCG + brokerage on frequent "
            "trades). Don't overtrade. A top rank that's already run up 15% is "
            "a BAD entry — wait for a pullback."
        ),
        "tax_note": "Gains under 12 months = Short-Term Capital Gains (15% in India).",
    },
    "medium": {
        "label": "Medium-term",
        "window": "3 months to 1 year",
        "scoring_horizon": "blend",      # tactical + structural balanced
        "hold_days": 63,                 # ~3 months typical hold
        "rebalance": "Monthly — let trends develop",
        "atr_stop_mult": 3.0,            # medium room
        "reward_mult": 2.5,
        "min_turnover_cr": 2.0,
        "require_above_ema200": True,    # only uptrends
        "what_good_looks_like": (
            "A healthy 3–6 month trend, price above the 200-EMA, outperforming "
            "the Nifty, strong directional trend (high ADX), and shallow "
            "drawdowns. Momentum confirms but the bigger trend leads."
        ),
        "watch_out": (
            "Don't get shaken out by normal wobbles — your edge is sitting "
            "through them. But respect a real trend break."
        ),
        "tax_note": "Crossing 12 months shifts gains to LTCG (lower tax) — worth "
                    "considering near the 1-year mark.",
    },
    "long": {
        "label": "Long-term",
        "window": "1 to 2+ years",
        "scoring_horizon": "structural", # trend durability dominates
        "hold_days": 126,                # ~6 months between reviews
        "rebalance": "Quarterly — minimal churn",
        "atr_stop_mult": 4.0,            # wide stop, ride the noise
        "reward_mult": 3.0,
        "min_turnover_cr": 1.0,          # can tolerate slightly less liquid
        "require_above_ema200": True,
        "what_good_looks_like": (
            "Durable multi-month/years uptrend, consistently above the "
            "200-EMA, steady relative strength vs the market, and resilience "
            "(it recovers from dips). You're owning a compounding trend."
        ),
        "watch_out": (
            "Patience is the edge. Wide stops mean bigger paper swings — that's "
            "the price of letting a multi-year winner run. Review quarterly, "
            "not daily, or you'll fiddle a good position to death."
        ),
        "tax_note": "Held over 12 months = Long-Term Capital Gains (10% over ₹1L/yr "
                    "in India) — the most tax-efficient bucket.",
    },
}


ORDER = ["short", "medium", "long"]


def get(profile_key: str) -> dict:
    return PROFILES.get(profile_key, PROFILES["medium"])
