"""
scoring.py — Turns raw factors into a ranked, explainable trade score.

Philosophy:
  1. Filter the universe HARD first (liquidity, regime) — most "opportunities"
     in the full NSE list are untradeable noise. We kill them before scoring.
  2. Z-score each factor cross-sectionally (within the surviving universe),
     winsorized to kill outliers.
  3. Combine into TACTICAL and STRUCTURAL composite scores, then a blended
     FINAL score whose weighting depends on the chosen horizon.
  4. Every score carries a human-readable reason string. No black boxes.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


# Direction: +1 means higher-is-better, -1 means lower-is-better.
FACTOR_DIRECTION = {
    # tactical
    "ret_5d": +1, "ret_21d": +1, "vol_thrust": +1,
    "rsi": +1, "dist_ema20": +1, "atr_pct": -1, "breakout_gap": -1,
    # structural
    "ret_63d": +1, "ret_126d": +1, "adx": +1,
    "dist_ema200": +1, "rel_strength_63d": +1, "max_dd_126d": +1,
}

TACTICAL_FACTORS = ["ret_5d", "ret_21d", "vol_thrust", "rsi",
                    "dist_ema20", "atr_pct", "breakout_gap"]
STRUCTURAL_FACTORS = ["ret_63d", "ret_126d", "adx",
                      "dist_ema200", "rel_strength_63d", "max_dd_126d"]


def winsorize(s: pd.Series, limits=(0.02, 0.98)) -> pd.Series:
    lo, hi = s.quantile(limits[0]), s.quantile(limits[1])
    return s.clip(lower=lo, upper=hi)


def zscore(s: pd.Series) -> pd.Series:
    s = winsorize(s)
    mu, sd = s.mean(), s.std(ddof=0)
    if sd == 0 or np.isnan(sd):
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sd


def zscore_by_group(s: pd.Series, groups: pd.Series, min_group: int = 3) -> pd.Series:
    """
    Sector-neutral z-score: standardize each value WITHIN its own group (sector).
    Groups too small to standardize reliably fall back to the global z-score so
    a lone stock in a sector isn't auto-awarded a 0.
    """
    s = s.astype(float)
    out = pd.Series(index=s.index, dtype=float)
    global_z = zscore(s)
    for g, idx in groups.groupby(groups).groups.items():
        idx = list(idx)
        if len(idx) >= min_group:
            out.loc[idx] = zscore(s.loc[idx])
        else:
            out.loc[idx] = global_z.loc[idx]
    return out


# --------------------------------------------------------------------------
# Hard universe filters — applied BEFORE scoring
# --------------------------------------------------------------------------
def apply_hard_filters(
    df: pd.DataFrame,
    min_turnover_cr: float = 2.0,        # ₹2 cr avg daily turnover minimum
    require_above_ema200: bool = False,  # regime filter for longer horizon
) -> pd.DataFrame:
    out = df.copy()
    flags = pd.Series(True, index=out.index)

    if "avg_turnover_20d" in out:
        flags &= out["avg_turnover_20d"] >= (min_turnover_cr * 1e7)

    if require_above_ema200 and "above_ema200" in out:
        flags &= out["above_ema200"] == 1.0

    out = out[flags].copy()
    return out


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def score_universe(
    df: pd.DataFrame,
    horizon: str = "blend",   # "tactical" | "structural" | "blend"
    sector_neutral: bool = False,
    sector_col: str = "sector",
) -> pd.DataFrame:
    """
    df: one row per stock, columns = factor names (from factors.compute_all).
    sector_neutral: if True, z-score each factor WITHIN its sector so you find
                    the best name per sector rather than just the hottest sector.
    Returns df with z-scored factors, composite scores, and rank.
    """
    df = df.copy()
    use_sectors = sector_neutral and sector_col in df.columns
    groups = df[sector_col] if use_sectors else None

    # z-score each factor with correct direction
    for f, direction in FACTOR_DIRECTION.items():
        if f in df:
            series = df[f].astype(float)
            if use_sectors:
                z = zscore_by_group(series, groups)
            else:
                z = zscore(series)
            df[f"z_{f}"] = z * direction

    tac_cols = [f"z_{f}" for f in TACTICAL_FACTORS if f"z_{f}" in df]
    str_cols = [f"z_{f}" for f in STRUCTURAL_FACTORS if f"z_{f}" in df]

    df["tactical_score"] = df[tac_cols].mean(axis=1) if tac_cols else 0.0
    df["structural_score"] = df[str_cols].mean(axis=1) if str_cols else 0.0

    # blend weights by horizon
    weights = {
        "tactical":   (0.80, 0.20),
        "structural": (0.20, 0.80),
        "blend":      (0.50, 0.50),
    }[horizon]
    df["final_score"] = (weights[0] * df["tactical_score"]
                         + weights[1] * df["structural_score"])

    df["rank"] = df["final_score"].rank(ascending=False, method="min")
    df = df.sort_values("final_score", ascending=False)
    return df


def apply_sector_cap(
    scored: pd.DataFrame,
    top_n: int,
    max_per_sector: int = 2,
    sector_col: str = "sector",
) -> pd.DataFrame:
    """
    Build the final top-N list with a hard limit of `max_per_sector` names from
    any one sector. Prevents the list from becoming an accidental sector bet
    (e.g. 8 PSU banks). Walks down the ranked list and skips a name once its
    sector is full.
    """
    if sector_col not in scored.columns:
        return scored.head(top_n)
    chosen, counts = [], {}
    for sym, row in scored.iterrows():
        sec = row[sector_col]
        if counts.get(sec, 0) >= max_per_sector:
            continue
        chosen.append(sym)
        counts[sec] = counts.get(sec, 0) + 1
        if len(chosen) >= top_n:
            break
    return scored.loc[chosen]


# --------------------------------------------------------------------------
# Explainability
# --------------------------------------------------------------------------
def build_reason(row: pd.Series) -> str:
    """Plain-English why-this-stock string from the strongest contributing z-factors."""
    contribs = {}
    for f in FACTOR_DIRECTION:
        zc = f"z_{f}"
        if zc in row and not pd.isna(row[zc]):
            contribs[f] = row[zc]
    if not contribs:
        return "Insufficient data."

    top = sorted(contribs.items(), key=lambda kv: abs(kv[1]), reverse=True)[:3]
    labels = {
        "ret_5d": "strong 5-day momentum", "ret_21d": "strong 21-day momentum",
        "vol_thrust": "volume surge", "rsi": "healthy RSI",
        "dist_ema20": "above 20-EMA", "atr_pct": "calm volatility",
        "breakout_gap": "near 20-day breakout",
        "ret_63d": "strong 3-month trend", "ret_126d": "strong 6-month trend",
        "adx": "strong directional trend", "dist_ema200": "well above 200-EMA",
        "rel_strength_63d": "outperforming Nifty", "max_dd_126d": "shallow drawdowns",
    }
    parts = []
    for f, z in top:
        tag = labels.get(f, f)
        sign = "+" if z > 0 else "-"
        parts.append(f"{tag} ({sign})")
    return ", ".join(parts)
