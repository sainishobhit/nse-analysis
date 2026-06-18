"""
factors.py — Factor computation for the dual-horizon NSE trading system.

Two factor families:
  TACTICAL (days-weeks): momentum, volume thrust, volatility regime, RSI,
                         distance from moving averages, breakout proximity.
  STRUCTURAL (multi-month): trend quality, relative strength vs Nifty,
                            drawdown recovery, liquidity, optional fundamentals.

All factors are computed from OHLCV. Everything returns NaN-safe values so the
ranking layer can z-score and combine them without blowing up on missing data.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _safe_last(series: pd.Series, default=np.nan):
    s = series.dropna()
    return s.iloc[-1] if len(s) else default


def _pct_return(close: pd.Series, lookback: int) -> float:
    if len(close) <= lookback:
        return np.nan
    return close.iloc[-1] / close.iloc[-1 - lookback] - 1.0


# --------------------------------------------------------------------------
# Technical indicators (no TA-Lib dependency — pure pandas/numpy)
# --------------------------------------------------------------------------
def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index — trend strength (not direction)."""
    high, low = df["High"], df["Low"]
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = atr(df, period) * period  # approximate smoothing base
    atr_s = atr(df, period)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / atr_s
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / atr_s
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


# --------------------------------------------------------------------------
# TACTICAL factors (days-weeks)
# --------------------------------------------------------------------------
def tactical_factors(df: pd.DataFrame) -> dict:
    close = df["Close"]
    vol = df["Volume"]
    out = {}

    # Short momentum: 5d & 21d return
    out["ret_5d"] = _pct_return(close, 5)
    out["ret_21d"] = _pct_return(close, 21)

    # Volume thrust: today's volume vs 20d average
    vol_avg = vol.rolling(20).mean()
    out["vol_thrust"] = _safe_last(vol / vol_avg)

    # RSI(14): we want strength but not blow-off (sweet spot 50-70)
    r = _safe_last(rsi(close, 14))
    out["rsi"] = r

    # Distance above 20-day EMA (positive = above, momentum confirmed)
    ema20 = close.ewm(span=20, adjust=False).mean()
    out["dist_ema20"] = _safe_last((close - ema20) / ema20)

    # Volatility regime: ATR% — lower is calmer/cleaner trends
    a = atr(df, 14)
    out["atr_pct"] = _safe_last(a / close)

    # Breakout proximity: how close to 20-day high (0 = at high)
    hh20 = close.rolling(20).max()
    out["breakout_gap"] = _safe_last((hh20 - close) / hh20)

    return out


# --------------------------------------------------------------------------
# STRUCTURAL factors (multi-month)
# --------------------------------------------------------------------------
def structural_factors(df: pd.DataFrame, bench_close: pd.Series | None = None) -> dict:
    close = df["Close"]
    out = {}

    # Medium momentum: 63d (~3mo) and 126d (~6mo), skip last 5d to avoid noise
    out["ret_63d"] = _pct_return(close.shift(5), 63)
    out["ret_126d"] = _pct_return(close.shift(5), 126)

    # Trend quality: ADX (strength of trend)
    out["adx"] = _safe_last(adx(df, 14))

    # Above 200-EMA? (regime filter, 1/0)
    if len(close) >= 200:
        ema200 = close.ewm(span=200, adjust=False).mean()
        out["above_ema200"] = float(close.iloc[-1] > ema200.iloc[-1])
        out["dist_ema200"] = _safe_last((close - ema200) / ema200)
    else:
        out["above_ema200"] = np.nan
        out["dist_ema200"] = np.nan

    # Relative strength vs benchmark (Nifty) over 63d
    if bench_close is not None and len(bench_close) > 63:
        stock_ret = _pct_return(close, 63)
        bench_ret = _pct_return(bench_close, 63)
        out["rel_strength_63d"] = (stock_ret - bench_ret) if not (
            np.isnan(stock_ret) or np.isnan(bench_ret)) else np.nan
    else:
        out["rel_strength_63d"] = np.nan

    # Max drawdown over last 126d (less negative = more resilient)
    window = close.tail(126)
    if len(window) > 20:
        roll_max = window.cummax()
        dd = (window / roll_max - 1.0).min()
        out["max_dd_126d"] = dd
    else:
        out["max_dd_126d"] = np.nan

    return out


# --------------------------------------------------------------------------
# Liquidity (universe gatekeeper)
# --------------------------------------------------------------------------
def liquidity_metrics(df: pd.DataFrame) -> dict:
    close = df["Close"]
    vol = df["Volume"]
    turnover = (close * vol).rolling(20).mean()  # avg daily traded value (INR)
    return {
        "avg_turnover_20d": _safe_last(turnover),
        "avg_volume_20d": _safe_last(vol.rolling(20).mean()),
    }


def compute_all(df: pd.DataFrame, bench_close: pd.Series | None = None) -> dict:
    """Master function: returns a flat dict of every factor for one stock."""
    if df is None or len(df) < 30:
        return {}
    feats = {}
    feats.update(tactical_factors(df))
    feats.update(structural_factors(df, bench_close))
    feats.update(liquidity_metrics(df))
    return feats
