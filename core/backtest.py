"""
backtest.py — Walk-forward backtest for the ranking system.

THIS IS THE MOST IMPORTANT FILE. A screener that isn't backtested is just an
opinion generator. This harness answers: "If I had bought the top-N ranked
stocks each rebalance and held to the next, would I have made money AFTER
realistic costs?"

Key realism features (the things that make most retail backtests lie):
  - Costs: brokerage + STT + slippage modeled per round-trip.
  - No look-ahead: factors at time t use only data up to t; returns measured t→t+h.
  - Out-of-sample by construction (point-in-time rebalances).
  - Benchmark comparison (did we beat just buying the Nifty?).
  - Reports CAGR, hit rate, max drawdown, Sharpe — not just total return.

Costs default to a realistic Indian intraday-ish/short-swing round trip.
Tune `cost_bps` to your broker + holding style.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core import factors as F
from core import scoring as S


def _factors_asof(df: pd.DataFrame, bench: pd.Series, end_idx: int) -> dict:
    """Compute factors using ONLY data up to end_idx (no look-ahead)."""
    sub = df.iloc[: end_idx + 1]
    bsub = bench.iloc[: end_idx + 1] if bench is not None else None
    if len(sub) < 60:
        return {}
    return F.compute_all(sub, bench_close=bsub)


def backtest(
    price_data: dict,            # {symbol: ohlcv_df} aligned on dates
    bench: pd.Series,
    horizon: str = "blend",
    hold_days: int = 10,         # rebalance every N trading days
    top_n: int = 5,              # hold top-N ranked names
    min_turnover_cr: float = 2.0,
    cost_bps: float = 35.0,      # round-trip cost in basis points (0.35%)
    start_after: int = 200,      # warmup bars before first trade
) -> dict:
    # align all on a common date index
    common = None
    for df in price_data.values():
        idx = df.index
        common = idx if common is None else common.intersection(idx)
    if common is None or len(common) < start_after + hold_days + 5:
        return {"error": "insufficient overlapping data"}
    common = common.sort_values()

    closes = {s: df["Close"].reindex(common) for s, df in price_data.items()}
    bench_al = bench.reindex(common) if bench is not None else None

    equity = [1.0]
    bench_equity = [1.0]
    trade_returns = []
    dates_used = []

    t = start_after
    while t + hold_days < len(common):
        # rank as of time t
        rows = {}
        for s, df in price_data.items():
            feats = _factors_asof(df.reindex(common).ffill(), bench_al, t)
            if feats:
                rows[s] = feats
        if not rows:
            t += hold_days
            continue

        raw = pd.DataFrame.from_dict(rows, orient="index")
        filt = S.apply_hard_filters(raw, min_turnover_cr=min_turnover_cr)
        if filt.empty:
            t += hold_days
            continue
        scored = S.score_universe(filt, horizon=horizon)
        picks = scored.head(top_n).index.tolist()

        # realize return t → t+hold_days
        rets = []
        for s in picks:
            c = closes[s]
            p0, p1 = c.iloc[t], c.iloc[t + hold_days]
            if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                rets.append(p1 / p0 - 1.0)
        if rets:
            gross = np.mean(rets)
            net = gross - cost_bps / 1e4           # subtract round-trip cost
            trade_returns.append(net)
            equity.append(equity[-1] * (1 + net))
            # benchmark over same window
            if bench_al is not None:
                b0, b1 = bench_al.iloc[t], bench_al.iloc[t + hold_days]
                bret = (b1 / b0 - 1.0) if pd.notna(b0) and pd.notna(b1) else 0.0
            else:
                bret = 0.0
            bench_equity.append(bench_equity[-1] * (1 + bret))
            dates_used.append(common[t + hold_days])
        t += hold_days

    if len(trade_returns) < 3:
        return {"error": "too few trades to evaluate"}

    tr = np.array(trade_returns)
    periods_per_year = 252 / hold_days
    total_ret = equity[-1] - 1
    n_years = len(tr) / periods_per_year
    cagr = equity[-1] ** (1 / n_years) - 1 if n_years > 0 else np.nan
    sharpe = (tr.mean() / tr.std(ddof=0) * np.sqrt(periods_per_year)
              if tr.std(ddof=0) > 0 else np.nan)
    eq = np.array(equity)
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    hit = (tr > 0).mean()
    bench_total = bench_equity[-1] - 1

    return {
        "trades": len(tr),
        "total_return_pct": round(total_ret * 100, 2),
        "cagr_pct": round(cagr * 100, 2) if not np.isnan(cagr) else None,
        "sharpe": round(sharpe, 2) if not np.isnan(sharpe) else None,
        "hit_rate_pct": round(hit * 100, 1),
        "max_drawdown_pct": round(dd * 100, 2),
        "avg_trade_pct": round(tr.mean() * 100, 3),
        "benchmark_return_pct": round(bench_total * 100, 2),
        "alpha_vs_bench_pct": round((total_ret - bench_total) * 100, 2),
        "equity_curve": equity,
        "bench_curve": bench_equity,
        "dates": [str(d.date()) for d in dates_used],
    }
