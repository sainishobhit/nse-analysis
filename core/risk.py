"""
risk.py — ATR-based position sizing, stops, and targets.

This converts a ranked watchlist into an actual TRADE PLAN with risk control.
The core idea (volatility-based sizing) is how professionals size positions:

  - Risk a FIXED FRACTION of capital per trade (e.g. 1%), never a fixed rupee
    or fixed share count. A ₹3000 volatile stock and a ₹80 calm stock should
    NOT get the same number of shares.
  - The stop distance is a multiple of ATR (Average True Range), so the stop
    sits outside normal noise for THAT stock — wider for volatile names,
    tighter for calm ones.
  - Position size is then derived so that (entry − stop) × shares = risk budget.
  - Targets are set at R-multiples (e.g. 2R) so reward/risk is explicit.

Result: every name is sized to contribute the SAME risk to the book, which is
what keeps one bad trade from sinking you.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

from . import factors as F


def plan_trade(
    df: pd.DataFrame,
    capital: float,
    risk_pct: float = 1.0,        # % of capital risked on this trade
    atr_mult_stop: float = 2.0,   # stop = entry − atr_mult_stop × ATR
    reward_multiple: float = 2.0, # target = entry + reward_multiple × risk
    max_position_pct: float = 20.0,  # cap any single position at % of capital
    direction: str = "long",
) -> dict:
    """
    Build a full trade plan for ONE stock from its OHLCV.
    Returns entry, stop, target, shares, capital deployed, and risk in ₹.
    """
    if df is None or len(df) < 20:
        return {"error": "insufficient data"}

    close = df["Close"]
    entry = float(close.iloc[-1])
    atr_series = F.atr(df, 14)
    atr_val = float(atr_series.dropna().iloc[-1]) if atr_series.dropna().size else np.nan
    if np.isnan(atr_val) or atr_val <= 0:
        return {"error": "ATR unavailable"}

    risk_budget = capital * (risk_pct / 100.0)       # ₹ you're willing to lose
    stop_distance = atr_mult_stop * atr_val

    if direction == "long":
        stop = entry - stop_distance
        target = entry + reward_multiple * stop_distance
    else:  # short
        stop = entry + stop_distance
        target = entry - reward_multiple * stop_distance

    # shares such that loss-at-stop == risk_budget
    raw_shares = risk_budget / stop_distance
    shares = int(np.floor(raw_shares))

    # enforce max position size
    max_capital = capital * (max_position_pct / 100.0)
    if shares * entry > max_capital:
        shares = int(np.floor(max_capital / entry))

    if shares < 1:
        return {"error": "position rounds to zero — raise capital or risk_pct"}

    deployed = shares * entry
    risk_actual = shares * stop_distance
    reward_actual = shares * reward_multiple * stop_distance

    return {
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "atr": round(atr_val, 2),
        "atr_pct": round(atr_val / entry * 100, 2),
        "shares": shares,
        "capital_deployed": round(deployed, 0),
        "capital_pct": round(deployed / capital * 100, 1),
        "risk_rupees": round(risk_actual, 0),
        "risk_pct_actual": round(risk_actual / capital * 100, 2),
        "reward_rupees": round(reward_actual, 0),
        "reward_risk_ratio": reward_multiple,
        "direction": direction,
    }


def plan_portfolio(
    picks: list[str],
    price_data: dict,
    capital: float,
    risk_pct: float = 1.0,
    atr_mult_stop: float = 2.0,
    reward_multiple: float = 2.0,
    max_total_risk_pct: float = 6.0,  # cap aggregate open risk across book
    max_position_pct: float = 20.0,
) -> pd.DataFrame:
    """
    Build trade plans for a list of picks and assemble a portfolio-level view.
    Stops adding once aggregate risk hits max_total_risk_pct (heat limit).
    """
    rows = {}
    cumulative_risk_pct = 0.0
    for sym in picks:
        df = price_data.get(sym)
        plan = plan_trade(df, capital, risk_pct, atr_mult_stop,
                          reward_multiple, max_position_pct)
        if "error" in plan:
            continue
        if cumulative_risk_pct + plan["risk_pct_actual"] > max_total_risk_pct:
            break  # portfolio heat limit reached
        cumulative_risk_pct += plan["risk_pct_actual"]
        rows[sym] = plan

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index.name = "Symbol"
    cols = ["entry", "stop", "target", "shares", "capital_deployed",
            "capital_pct", "risk_rupees", "risk_pct_actual",
            "reward_rupees", "atr_pct"]
    out = out[cols]
    # portfolio summary as an attribute
    out.attrs["total_deployed"] = out["capital_deployed"].sum()
    out.attrs["total_deployed_pct"] = round(out["capital_deployed"].sum() / capital * 100, 1)
    out.attrs["total_risk_pct"] = round(out["risk_pct_actual"].sum(), 2)
    out.attrs["positions"] = len(out)
    return out


if __name__ == "__main__":
    # self-test with synthetic data
    np.random.seed(1)
    n = 60
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = 100 * np.exp(np.cumsum(np.random.normal(0.001, 0.02, n)))
    df = pd.DataFrame({
        "Open": close, "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": np.random.lognormal(13, 0.3, n),
    }, index=dates)
    plan = plan_trade(df, capital=500000, risk_pct=1.0)
    for k, v in plan.items():
        print(f"  {k:20s}: {v}")
