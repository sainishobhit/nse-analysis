"""
monitor.py — The sell-side brain: evaluates open positions and signals action.

For each holding it checks, in priority order:
  1. STOP HIT      → EXIT now (hard risk rule, non-negotiable).
  2. TARGET HIT    → EXIT (or TRIM) — booked the planned reward.
  3. TRAIL UPDATE  → raise the stop as price advances (ATR chandelier-style),
                     locking in gains without exiting prematurely.
  4. SCORE DECAY   → the thesis weakened: momentum reversed, fell below trend,
                     score dropped sharply → TRIM or EXIT depending on severity.
  5. TIME STOP     → optional: held longer than max_days with no progress.
  6. Otherwise     → HOLD.

This is deliberately mechanical. The whole point of a stop is that you honor it
without negotiating. The monitor surfaces the decision; you execute it in your
broker (the system never places orders).
"""

from __future__ import annotations
import numpy as np
import pandas as pd

from . import factors as F


# Action constants
EXIT = "EXIT"
TRIM = "TRIM"
HOLD = "HOLD"
RAISE_STOP = "RAISE_STOP"


def evaluate_position(
    pos: dict,
    df: pd.DataFrame,
    factor_row: pd.Series | None = None,
    atr_trail_mult: float = 3.0,
    score_exit_threshold: float = -0.5,
    score_trim_threshold: float = 0.0,
    max_days: int | None = None,
) -> dict:
    """
    pos: a position dict from store (symbol, entry_price, shares, stop, target...).
    df:  recent OHLCV for the symbol.
    factor_row: current scored row for the symbol (optional; enables score-decay).
    Returns a verdict dict: action, reason, current price, P&L, suggested new stop.
    """
    if df is None or len(df) < 20:
        return {
            "symbol": pos.get("symbol", "?"),
            "price": None,
            "entry": round(pos.get("entry_price", 0), 2),
            "stop": round(pos.get("stop", 0), 2),
            "target": round(pos["target"], 2) if pos.get("target") else None,
            "pnl_pct": 0.0,
            "pnl_abs": 0.0,
            "action": HOLD,
            "reason": "no price data (network/feed) — couldn't evaluate",
            "new_stop": None,
        }

    close = df["Close"]
    price = float(close.iloc[-1])
    entry = pos["entry_price"]
    stop = pos["stop"]
    target = pos.get("target")

    pnl_pct = (price / entry - 1) * 100
    pnl_abs = (price - entry) * pos["shares"]

    verdict = {
        "symbol": pos["symbol"],
        "price": round(price, 2),
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2) if target else None,
        "pnl_pct": round(pnl_pct, 2),
        "pnl_abs": round(pnl_abs, 0),
        "action": HOLD,
        "reason": "within plan",
        "new_stop": None,
    }

    # 1. STOP HIT (hard rule)
    if price <= stop:
        verdict["action"] = EXIT
        verdict["reason"] = f"stop hit (₹{price:.2f} ≤ ₹{stop:.2f})"
        return verdict

    # 2. TARGET HIT
    if target and price >= target:
        verdict["action"] = TRIM
        verdict["reason"] = f"target reached (₹{price:.2f} ≥ ₹{target:.2f}) — book/trim & trail rest"
        # also compute a trailing stop to protect remainder
        atr_val = _atr_last(df)
        if atr_val:
            new_stop = max(stop, price - atr_trail_mult * atr_val)
            if new_stop > stop:
                verdict["new_stop"] = round(new_stop, 2)
        return verdict

    # 3. TRAILING STOP (only ratchets UP, never down)
    atr_val = _atr_last(df)
    if atr_val:
        trail = price - atr_trail_mult * atr_val
        if trail > stop:
            verdict["action"] = RAISE_STOP
            verdict["new_stop"] = round(trail, 2)
            verdict["reason"] = (f"trail stop up ₹{stop:.2f} → ₹{trail:.2f} "
                                 f"(locks in gains)")
            # don't return — score decay could still override to EXIT below

    # 4. SCORE / THESIS DECAY
    if factor_row is not None:
        score = factor_row.get("final_score", np.nan)
        below_ema20 = False
        if "dist_ema20" in factor_row and not pd.isna(factor_row["dist_ema20"]):
            below_ema20 = factor_row["dist_ema20"] < 0
        if not np.isnan(score):
            if score <= score_exit_threshold:
                verdict["action"] = EXIT
                verdict["reason"] = (f"thesis broken (score {score:.2f}) — "
                                     f"momentum/trend deteriorated")
                return verdict
            elif score <= score_trim_threshold and below_ema20:
                if verdict["action"] in (HOLD, RAISE_STOP):
                    verdict["action"] = TRIM
                    verdict["reason"] = (f"weakening (score {score:.2f}, "
                                         f"below 20-EMA) — consider trimming")

    # 5. TIME STOP
    if max_days and "entry_date" in pos:
        try:
            held = (pd.Timestamp.now().normalize()
                    - pd.Timestamp(pos["entry_date"])).days
            if held >= max_days and pnl_pct < 2:
                if verdict["action"] in (HOLD, RAISE_STOP):
                    verdict["action"] = TRIM
                    verdict["reason"] = (f"time stop: {held}d held, going nowhere "
                                         f"({pnl_pct:+.1f}%)")
        except Exception:
            pass

    return verdict


def _atr_last(df: pd.DataFrame, period: int = 14) -> float | None:
    a = F.atr(df, period).dropna()
    return float(a.iloc[-1]) if len(a) else None


def evaluate_all(
    positions: list[dict],
    price_data: dict,
    scored: pd.DataFrame | None = None,
    **kwargs,
) -> pd.DataFrame:
    """Evaluate every open position. Returns a DataFrame of verdicts."""
    rows = []
    for pos in positions:
        sym = pos["symbol"]
        df = price_data.get(sym)
        frow = None
        if scored is not None and sym in scored.index:
            frow = scored.loc[sym]
        v = evaluate_position(pos, df, factor_row=frow, **kwargs)
        v["id"] = pos["id"]
        v["shares"] = pos["shares"]
        rows.append(v)
    if not rows:
        return pd.DataFrame()
    cols = ["symbol", "action", "reason", "price", "entry", "stop",
            "target", "new_stop", "pnl_pct", "pnl_abs", "shares", "id"]
    df = pd.DataFrame(rows)
    return df[[c for c in cols if c in df.columns]]
