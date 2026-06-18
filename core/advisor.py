"""
advisor.py — Explicit "how many shares to sell" recommendations.

The exit monitor says HOLD/TRIM/EXIT. This goes further: for each holding it
computes ACTUAL SHARE QUANTITIES to sell under three selling philosophies, so
you can pick the one that fits you. It answers "sell how much?", not just
"should I?".

Three strategies (shown side by side):
  1. SCALE_OUT       — sell fixed portions as the stock climbs through gain
                       milestones (e.g. trim 25% at +25%, +50%, +100%).
  2. RECOVER_CAPITAL — sell exactly enough to pull your original money back out;
                       the rest rides "risk-free" (house money).
  3. TRAIL_ONLY      — sell nothing until a trailing stop is hit, then sell ALL.

Quantity sizing is RISK-BASED where applicable: a position whose open risk
(distance to stop × shares) is too large a share of capital gets trimmed back
to a target risk budget.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from . import factors as F


def _atr_last(df, period=14):
    a = F.atr(df, period).dropna()
    return float(a.iloc[-1]) if len(a) else None


def scale_out_plan(shares, gain_pct, milestones=(25, 50, 100, 200),
                   trim_frac=0.25, already_trimmed=0):
    """
    Sell trim_frac of ORIGINAL shares each time a gain milestone is crossed.
    Returns shares to sell NOW based on how many milestones are already passed.
    """
    passed = sum(1 for m in milestones if gain_pct >= m)
    target_trimmed = int(round(shares * trim_frac * passed))
    sell_now = max(0, target_trimmed - already_trimmed)
    sell_now = min(sell_now, shares)  # never more than held
    return {
        "strategy": "Scale out",
        "sell_shares": sell_now,
        "keep_shares": shares - sell_now,
        "rationale": (f"{passed} gain milestone(s) passed "
                      f"(+{gain_pct:.0f}%). Trim {int(trim_frac*100)}% per "
                      f"milestone to lock profit while riding the rest."),
    }


def recover_capital_plan(shares, entry, price):
    """Sell just enough to take your original invested money back off the table."""
    invested = shares * entry
    if price <= 0:
        return None
    sell_shares = int(np.ceil(invested / price))
    sell_shares = min(sell_shares, shares)
    freed = sell_shares * price
    return {
        "strategy": "Recover capital",
        "sell_shares": sell_shares,
        "keep_shares": shares - sell_shares,
        "rationale": (f"Sell {sell_shares} to pull back ~₹{freed:,.0f} "
                      f"(your original ₹{invested:,.0f}). The remaining "
                      f"{shares - sell_shares} shares then ride on house money."),
    }


def trail_only_plan(shares, price, stop, df, atr_mult=3.0):
    """Hold everything unless a trailing stop is breached; then sell all."""
    atr_val = _atr_last(df) if df is not None else None
    trail = price - atr_mult * atr_val if atr_val else stop
    trail = max(trail, stop)  # never below existing stop
    breached = price <= trail
    return {
        "strategy": "Trail only",
        "sell_shares": shares if breached else 0,
        "keep_shares": 0 if breached else shares,
        "suggested_stop": round(trail, 2),
        "rationale": (f"Hold all; sell everything only if price drops to the "
                      f"trailing stop (₹{trail:.2f}). "
                      + ("STOP BREACHED — exit now." if breached
                         else "Not breached — keep holding, stop rises as price does.")),
    }


def risk_trim_plan(shares, entry, price, stop, capital, max_risk_pct=2.0):
    """
    Risk-based: if this position's open risk (distance to stop × shares) exceeds
    max_risk_pct of capital, sell enough shares to bring it back to budget.
    For a deep winner whose stop is above entry, risk may already be negative
    (locked-in profit) — in which case nothing needs trimming on risk grounds.
    """
    risk_per_share = price - stop  # if stop below price, this is downside per share
    if risk_per_share <= 0:
        return {
            "strategy": "Risk-based trim",
            "sell_shares": 0,
            "keep_shares": shares,
            "rationale": ("Stop is at/above current price — no open downside risk "
                          "to trim. (Your stop already protects the gain.)"),
        }
    current_risk = risk_per_share * shares
    budget = capital * (max_risk_pct / 100)
    if current_risk <= budget:
        return {
            "strategy": "Risk-based trim",
            "sell_shares": 0,
            "keep_shares": shares,
            "rationale": (f"Open risk ₹{current_risk:,.0f} is within your "
                          f"{max_risk_pct}% budget (₹{budget:,.0f}). No trim needed."),
        }
    target_shares = int(np.floor(budget / risk_per_share))
    sell = shares - target_shares
    return {
        "strategy": "Risk-based trim",
        "sell_shares": max(0, sell),
        "keep_shares": target_shares,
        "rationale": (f"Open risk ₹{current_risk:,.0f} exceeds your "
                      f"{max_risk_pct}% budget (₹{budget:,.0f}). Sell {sell} to "
                      f"bring risk back in line."),
    }


def advise_position(pos, df, capital, factor_row=None,
                    atr_trail_mult=3.0, max_risk_pct=2.0):
    """
    Master: returns a full advisory for one holding, including all strategies and
    a headline verdict. df = recent OHLCV. factor_row = current scored row (opt).
    """
    if df is None or len(df) < 20:
        return {"symbol": pos["symbol"], "error": "no price data"}

    price = float(df["Close"].iloc[-1])
    entry = pos["entry_price"]
    shares = pos["shares"]
    stop = pos.get("stop", 0)
    gain_pct = (price / entry - 1) * 100
    already = pos.get("trimmed_shares", 0)

    strategies = {
        "scale_out": scale_out_plan(shares, gain_pct, already_trimmed=already),
        "recover_capital": recover_capital_plan(shares, entry, price),
        "trail_only": trail_only_plan(shares, price, stop, df, atr_trail_mult),
        "risk_trim": risk_trim_plan(shares, entry, price, stop, capital, max_risk_pct),
    }

    # headline verdict: thesis-break overrides everything → SELL ALL
    score = factor_row.get("final_score", np.nan) if factor_row is not None else np.nan
    thesis_broken = (not np.isnan(score)) and score <= -0.5

    if thesis_broken:
        verdict = "SELL ALL"
        headline = (f"Trend/score has broken (score {score:.2f}). The reason to "
                    f"own it is gone — exit fully regardless of profit.")
    elif gain_pct >= 25:
        verdict = "TRIM (winner)"
        headline = (f"Up {gain_pct:.0f}%. A healthy winner — consider banking some "
                    f"profit using one of the strategies below, keep the rest.")
    elif price <= stop:
        verdict = "SELL ALL"
        headline = f"Price hit your stop (₹{stop:.2f}). Exit to cap the loss."
    else:
        verdict = "HOLD"
        headline = "Within plan. Nothing to do — let it work, mind your stop."

    return {
        "symbol": pos["symbol"],
        "price": round(price, 2),
        "entry": round(entry, 2),
        "shares": shares,
        "gain_pct": round(gain_pct, 1),
        "pnl_abs": round((price - entry) * shares, 0),
        "verdict": verdict,
        "headline": headline,
        "strategies": strategies,
    }
