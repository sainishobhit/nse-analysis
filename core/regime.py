"""
regime.py — Market regime filter: protection FROM THE MARKET.

Short-horizon long strategies get slaughtered when the broad market rolls over
(documented as "poor performance during major market changes"). No amount of
good stock-picking saves you when everything falls together. This module reads
the Nifty's own health and outputs a risk posture that throttles the whole
system.

Signals used (all from the index itself, robust and lag-aware):
  - Trend: Nifty above/below its 50- and 200-DMA (golden/death structure).
  - Slope: is the 50-DMA rising or falling?
  - Drawdown: how far is Nifty below its recent peak?
  - Volatility: India VIX proxy via realized vol (or real VIX if wired in).
  - Breadth (optional): % of universe above its own 50-DMA.

Output posture drives position COUNT and SIZE elsewhere:
  RISK_ON     → full deployment
  CAUTION     → reduce number of positions, tighten new entries
  RISK_OFF    → no new longs; manage/exit existing; raise cash
"""

from __future__ import annotations
import numpy as np
import pandas as pd

RISK_ON = "RISK_ON"
CAUTION = "CAUTION"
RISK_OFF = "RISK_OFF"


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def assess_regime(
    bench_close: pd.Series,
    universe_closes: dict | None = None,
    vix: float | None = None,
) -> dict:
    """
    bench_close: Nifty close series.
    universe_closes: optional {sym: close_series} for breadth.
    vix: optional current India VIX value (if you wire in a feed).
    Returns posture + the evidence behind it + a suggested exposure multiplier.
    """
    if bench_close is None or len(bench_close) < 200:
        return {"posture": CAUTION, "reason": "insufficient index history",
                "exposure": 0.5, "evidence": {}}

    close = bench_close.dropna()
    price = float(close.iloc[-1])
    sma50 = _sma(close, 50)
    sma200 = _sma(close, 200)
    s50 = float(sma50.iloc[-1])
    s200 = float(sma200.iloc[-1])

    # trend structure
    above_50 = price > s50
    above_200 = price > s200
    slope_50 = float(sma50.iloc[-1] - sma50.iloc[-10]) if len(sma50.dropna()) > 10 else 0.0
    rising_50 = slope_50 > 0

    # drawdown from 6-month peak
    recent = close.tail(126)
    peak = float(recent.max())
    drawdown = price / peak - 1.0

    # realized volatility (annualized) as a VIX proxy if no real VIX given
    rets = close.pct_change().dropna()
    realized_vol = float(rets.tail(20).std() * np.sqrt(252)) if len(rets) > 20 else np.nan
    vol_signal = vix if vix is not None else realized_vol * 100  # comparable scale

    # breadth: % of universe above own 50-DMA
    breadth = None
    if universe_closes:
        above = 0; total = 0
        for s, c in universe_closes.items():
            c = c.dropna()
            if len(c) >= 50:
                total += 1
                if c.iloc[-1] > c.rolling(50).mean().iloc[-1]:
                    above += 1
        breadth = (above / total) if total else None

    # ---- scoring the posture ----
    score = 0
    score += 1 if above_200 else -2     # below 200-DMA is a strong risk-off tilt
    score += 1 if above_50 else -1
    score += 1 if rising_50 else -1
    if drawdown < -0.10:
        score -= 2                       # >10% off the peak = real trouble
    elif drawdown < -0.05:
        score -= 1
    if breadth is not None:
        if breadth < 0.35:
            score -= 1
        elif breadth > 0.60:
            score += 1
    # volatility penalty (high vol = de-risk)
    if not np.isnan(vol_signal):
        if vol_signal >= 22:
            score -= 1
        if vol_signal >= 30:
            score -= 1

    if score >= 2:
        posture, exposure = RISK_ON, 1.0
    elif score >= -1:
        posture, exposure = CAUTION, 0.5
    else:
        posture, exposure = RISK_OFF, 0.0

    reason_bits = []
    reason_bits.append("above 200-DMA" if above_200 else "BELOW 200-DMA")
    reason_bits.append("above 50-DMA" if above_50 else "below 50-DMA")
    reason_bits.append("50-DMA rising" if rising_50 else "50-DMA falling")
    reason_bits.append(f"{drawdown*100:.1f}% from peak")
    if breadth is not None:
        reason_bits.append(f"breadth {breadth*100:.0f}%")
    if not np.isnan(vol_signal):
        reason_bits.append(f"vol {vol_signal:.0f}")

    return {
        "posture": posture,
        "exposure": exposure,
        "reason": " · ".join(reason_bits),
        "evidence": {
            "price": round(price, 2),
            "sma50": round(s50, 2),
            "sma200": round(s200, 2),
            "above_50dma": above_50,
            "above_200dma": above_200,
            "slope_50_rising": rising_50,
            "drawdown_pct": round(drawdown * 100, 2),
            "realized_vol": round(realized_vol * 100, 1) if not np.isnan(realized_vol) else None,
            "vix": vix,
            "breadth_pct": round(breadth * 100, 1) if breadth is not None else None,
            "score": score,
        },
    }


def throttle_positions(base_top_n: int, posture_result: dict) -> int:
    """Scale how many positions the system will recommend by regime exposure."""
    exposure = posture_result.get("exposure", 0.5)
    return max(0, int(round(base_top_n * exposure)))
