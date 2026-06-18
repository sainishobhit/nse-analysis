"""
walkforward.py — Walk-forward validation: the overfitting lie-detector.

A normal backtest optimizes on the SAME data it reports results for, so a
strategy that merely memorized the past looks brilliant. Walk-forward splits
history into rolling IN-SAMPLE (train) and OUT-OF-SAMPLE (test) windows:

   [---- train 1 ----][test 1]
            [---- train 2 ----][test 2]
                     [---- train 3 ----][test 3] ...

You only ever judge the strategy on the TEST windows it never saw during tuning.
If out-of-sample results collapse vs in-sample, the edge was overfit — better to
learn that here than with real money.

This harness runs the existing backtester across rolling OOS windows and
reports the gap between in-sample and out-of-sample performance. A large gap is
the red flag practitioners warn about ("looks great on history, dies live").
"""

from __future__ import annotations
import numpy as np
import pandas as pd

from . import backtest as BT


def walk_forward(
    price_data: dict,
    bench: pd.Series,
    horizon: str = "blend",
    train_days: int = 252,       # ~1 year in-sample
    test_days: int = 63,         # ~1 quarter out-of-sample
    step_days: int = 63,         # advance by a quarter each fold
    hold_days: int = 10,
    top_n: int = 5,
    cost_bps: float = 35.0,
    min_turnover_cr: float = 2.0,
) -> dict:
    """
    Runs rolling in-sample vs out-of-sample backtests.
    Returns per-fold OOS results + aggregate, and the IS/OOS degradation.

    NOTE: this ranking system has fixed factor logic (no fitted parameters per
    fold), so "training" here measures in-sample performance of the SAME rules
    on the train window; the key output is whether OOS holds up vs IS. If you
    later add fitted weights, fit them on train and apply on test inside this loop.
    """
    # common date index
    common = None
    for df in price_data.values():
        common = df.index if common is None else common.intersection(df.index)
    if common is None or len(common) < train_days + test_days + hold_days:
        return {"error": "insufficient overlapping history for walk-forward"}
    common = common.sort_values()
    n = len(common)

    folds = []
    start = 0
    # factors need history; give every test window a lookback buffer so factors
    # can be computed, while returns are still only measured inside the test span.
    lookback_buffer = 210  # enough for 200-EMA + warmup
    while start + train_days + test_days <= n:
        train_idx = common[start: start + train_days]
        test_start_pos = start + train_days
        # test slice INCLUDES preceding buffer bars for factor calc
        buf_start = max(0, test_start_pos - lookback_buffer)
        test_with_buffer_idx = common[buf_start: test_start_pos + test_days]
        n_buffer = test_start_pos - buf_start  # bars before the real test span

        def _slice(idx):
            return {s: df.reindex(common).loc[idx].dropna()
                    for s, df in price_data.items()}

        train_data = _slice(train_idx)
        test_data = _slice(test_with_buffer_idx)
        train_data = {s: d for s, d in train_data.items() if len(d) > 60}
        test_data = {s: d for s, d in test_data.items() if len(d) > n_buffer + hold_days}

        is_res = BT.backtest(train_data, bench.reindex(train_idx),
                             horizon=horizon, hold_days=hold_days, top_n=top_n,
                             min_turnover_cr=min_turnover_cr, cost_bps=cost_bps,
                             start_after=min(200, max(60, train_days // 2)))
        # start trading right at the test span (after the buffer)
        oos_res = BT.backtest(test_data, bench.reindex(test_with_buffer_idx),
                              horizon=horizon, hold_days=hold_days, top_n=top_n,
                              min_turnover_cr=min_turnover_cr, cost_bps=cost_bps,
                              start_after=max(60, n_buffer))

        if "error" not in oos_res:
            folds.append({
                "train_start": str(train_idx[0].date()),
                "test_start": str(common[test_start_pos].date()),
                "test_end": str(common[min(test_start_pos + test_days, n) - 1].date()),
                "is_total": is_res.get("total_return_pct") if "error" not in is_res else None,
                "is_sharpe": is_res.get("sharpe") if "error" not in is_res else None,
                "oos_total": oos_res["total_return_pct"],
                "oos_sharpe": oos_res["sharpe"],
                "oos_hit": oos_res["hit_rate_pct"],
                "oos_alpha": oos_res["alpha_vs_bench_pct"],
                "oos_trades": oos_res["trades"],
            })
        start += step_days

    if not folds:
        return {"error": "no valid folds produced"}

    fdf = pd.DataFrame(folds)
    oos_returns = fdf["oos_total"].dropna()
    is_returns = fdf["is_total"].dropna()

    # compounded OOS equity across folds
    oos_equity = float(np.prod([1 + r / 100 for r in oos_returns])) if len(oos_returns) else np.nan

    agg = {
        "folds": len(fdf),
        "oos_mean_return_pct": round(oos_returns.mean(), 2) if len(oos_returns) else None,
        "oos_median_return_pct": round(oos_returns.median(), 2) if len(oos_returns) else None,
        "oos_positive_folds": int((oos_returns > 0).sum()),
        "oos_win_rate_pct": round((oos_returns > 0).mean() * 100, 1) if len(oos_returns) else None,
        "oos_compounded_pct": round((oos_equity - 1) * 100, 2) if not np.isnan(oos_equity) else None,
        "oos_mean_sharpe": round(fdf["oos_sharpe"].dropna().mean(), 2) if fdf["oos_sharpe"].notna().any() else None,
        "oos_mean_alpha_pct": round(fdf["oos_alpha"].dropna().mean(), 2) if fdf["oos_alpha"].notna().any() else None,
        "is_mean_return_pct": round(is_returns.mean(), 2) if len(is_returns) else None,
    }
    # degradation: how much worse is OOS than IS?
    if agg["is_mean_return_pct"] and agg["oos_mean_return_pct"] is not None:
        agg["is_oos_gap_pct"] = round(agg["is_mean_return_pct"] - agg["oos_mean_return_pct"], 2)
        agg["overfit_flag"] = bool(
            agg["is_mean_return_pct"] > 0
            and agg["oos_mean_return_pct"] < 0.5 * agg["is_mean_return_pct"]
        )
    else:
        agg["is_oos_gap_pct"] = None
        agg["overfit_flag"] = None

    return {"aggregate": agg, "folds": folds}


def verdict_text(agg: dict) -> str:
    """Plain-English read on whether to trust the strategy."""
    if agg.get("overfit_flag"):
        return ("⚠️ OVERFITTING LIKELY: out-of-sample returns are far below "
                "in-sample. The edge may not survive live. Simplify factors / "
                "widen the universe / lengthen holding period before risking capital.")
    wr = agg.get("oos_win_rate_pct")
    if wr is None:
        return "Inconclusive — not enough folds."
    if wr >= 60 and (agg.get("oos_mean_alpha_pct") or 0) > 0:
        return ("✅ Holds up out-of-sample: majority of unseen windows positive "
                "with positive alpha. Cautiously tradeable — still start small.")
    if wr >= 50:
        return ("➖ Marginal: roughly coin-flip across unseen windows. Edge is "
                "thin; costs and discipline will decide whether it's worth it.")
    return ("❌ Weak out-of-sample: most unseen windows lost. Do not scale capital "
            "into this configuration.")
