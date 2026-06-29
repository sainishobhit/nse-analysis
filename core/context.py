"""
context.py — Build a rich, plain-language technical context object for AI consumption.

The thin payload was making AI Reads vague. This module computes concrete,
specific observations from OHLCV — recent multi-period returns, volume regime,
trend structure, key technical events (golden/death cross, breakouts, gap
moves) — and packages them so Claude can cite specifics.

Everything here is calculated from the price data the app already has. No
external calls, no fundamental data. The whole point: give Claude MORE of the
evidence the system already has, so its writeups can be specific and grounded.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from . import factors as F


def _pct(a, b):
    if b is None or b == 0 or pd.isna(a) or pd.isna(b):
        return None
    return round((a / b - 1) * 100, 2)


def build_context(df: pd.DataFrame) -> dict:
    """
    Given an OHLCV DataFrame, return a rich dict of observations.
    Used to enrich the AI payload alongside factor scores.
    """
    if df is None or len(df) < 20:
        return {"error": "insufficient history"}

    close = df["Close"]
    vol = df["Volume"]
    high = df["High"]
    low = df["Low"]
    n = len(close)
    ltp = float(close.iloc[-1])

    # multi-period returns
    rets = {}
    for label, periods in [("1d", 1), ("5d", 5), ("21d", 21),
                           ("63d", 63), ("126d", 126), ("252d", 252)]:
        if n > periods:
            rets[label] = _pct(close.iloc[-1], close.iloc[-1 - periods])

    # 52w high/low + distance
    window_52w = close.tail(min(252, n))
    hi_52w = float(window_52w.max())
    lo_52w = float(window_52w.min())

    # EMAs
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean() if n >= 200 else None

    trend = {
        "above_ema20": bool(ltp > float(ema20.iloc[-1])),
        "above_ema50": bool(ltp > float(ema50.iloc[-1])),
    }
    if ema200 is not None:
        trend["above_ema200"] = bool(ltp > float(ema200.iloc[-1]))
        # golden / death cross in last 60 days
        try:
            cross = (ema50 > ema200).astype(int).diff().tail(60)
            if (cross == 1).any():
                idx = cross[cross == 1].index[-1]
                trend["recent_golden_cross"] = str(idx.date()) if hasattr(idx, "date") else str(idx)
            if (cross == -1).any():
                idx = cross[cross == -1].index[-1]
                trend["recent_death_cross"] = str(idx.date()) if hasattr(idx, "date") else str(idx)
        except Exception:
            pass

    # volume regime: recent vs 60-day average
    vol_60_mean = float(vol.tail(60).mean()) if n >= 60 else float(vol.mean())
    vol_5_mean = float(vol.tail(5).mean())
    vol_thrust = round(vol_5_mean / vol_60_mean, 2) if vol_60_mean > 0 else None
    vol_note = None
    if vol_thrust:
        if vol_thrust >= 1.5:
            vol_note = f"volume spike — last 5d avg is {vol_thrust}x the 60d avg"
        elif vol_thrust <= 0.6:
            vol_note = f"volume drying up — last 5d avg is {vol_thrust}x the 60d avg"
        else:
            vol_note = f"volume normal ({vol_thrust}x 60d avg)"

    # max drawdown over last 126d
    window_126 = close.tail(min(126, n))
    if len(window_126) > 20:
        roll_max = window_126.cummax()
        dd_pct = float((window_126 / roll_max - 1).min()) * 100
        dd_pct = round(dd_pct, 2)
    else:
        dd_pct = None

    # RSI and ATR
    try:
        rsi_val = float(F.rsi(close, 14).dropna().iloc[-1])
    except Exception:
        rsi_val = None
    try:
        atr_val = float(F.atr(df, 14).dropna().iloc[-1])
        atr_pct = round(atr_val / ltp * 100, 2)
    except Exception:
        atr_val = None
        atr_pct = None

    # gap detection — last day vs prior close
    gap = None
    if n >= 2:
        prev_close = float(close.iloc[-2])
        today_open = float(df["Open"].iloc[-1])
        gap_pct = _pct(today_open, prev_close)
        if gap_pct is not None and abs(gap_pct) >= 2.0:
            gap = {"type": "gap_up" if gap_pct > 0 else "gap_down",
                   "pct": gap_pct}

    # breakout / breakdown detection — vs 20-day extremes
    if n >= 20:
        hh20 = float(close.tail(20).max())
        ll20 = float(close.tail(20).min())
        breakout = None
        if ltp >= hh20:
            breakout = "at 20-day high"
        elif ltp <= ll20:
            breakout = "at 20-day low"
    else:
        breakout = None

    # plain-English headline: a couple of summary sentences
    plain = []
    if rets.get("21d") is not None:
        d = "up" if rets["21d"] > 0 else "down"
        plain.append(f"{d} {abs(rets['21d']):.1f}% over the last month")
    if rets.get("252d") is not None:
        d = "up" if rets["252d"] > 0 else "down"
        plain.append(f"{d} {abs(rets['252d']):.1f}% over the last year")
    if dd_pct is not None and dd_pct <= -15:
        plain.append(f"max drawdown over the last 6 months: {dd_pct}%")
    if trend.get("above_ema200") is False:
        plain.append("below its 200-day trend line (long-term downtrend)")
    elif trend.get("above_ema200") is True:
        plain.append("above its 200-day trend line (long-term uptrend intact)")
    if vol_note:
        plain.append(vol_note)
    if breakout:
        plain.append(breakout)
    if gap:
        plain.append(f"{gap['type'].replace('_',' ')} of {gap['pct']}% today")

    return {
        "ltp": round(ltp, 2),
        "returns": rets,
        "52w_high": round(hi_52w, 2),
        "52w_low": round(lo_52w, 2),
        "pct_from_52w_high": _pct(ltp, hi_52w),
        "pct_from_52w_low": _pct(ltp, lo_52w),
        "trend": trend,
        "volume": {
            "thrust_5d_vs_60d": vol_thrust,
            "note": vol_note,
        },
        "max_drawdown_126d_pct": dd_pct,
        "rsi_14": round(rsi_val, 1) if rsi_val is not None else None,
        "atr_pct": atr_pct,
        "gap_today": gap,
        "breakout_breakdown": breakout,
        "plain_summary": "; ".join(plain) if plain else None,
        "data_window": {"bars": n, "first_date": str(df.index[0].date()),
                        "last_date": str(df.index[-1].date())},
    }
