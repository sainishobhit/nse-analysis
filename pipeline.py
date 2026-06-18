"""
pipeline.py — End-to-end run: fetch → compute factors → filter → score → rank.

Usage:
    python pipeline.py                 # blend horizon, default universe
    python pipeline.py --horizon tactical
    python pipeline.py --min-turnover 5 --top 20
"""

from __future__ import annotations
import argparse
import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from core import factors as F
from core import scoring as S
from core import sectors as SEC
from core import risk as R
from data import data as D


def run(horizon="blend", min_turnover_cr=2.0, top=25, period="1y",
        require_above_ema200=False, symbols=None,
        sector_neutral=False, max_per_sector=2,
        capital=None, risk_pct=1.0):
    print(f"Fetching benchmark (Nifty)...", file=sys.stderr)
    bench = D.fetch_benchmark(period=period)

    print(f"Fetching universe...", file=sys.stderr)
    universe = D.fetch_universe(symbols=symbols, period=period)
    print(f"  fetched {len(universe)} symbols", file=sys.stderr)

    rows = {}
    for sym, df in universe.items():
        feats = F.compute_all(df, bench_close=bench)
        if feats:
            rows[sym] = feats

    raw = pd.DataFrame.from_dict(rows, orient="index")
    if raw.empty:
        print("No data.", file=sys.stderr)
        return pd.DataFrame()

    raw = SEC.attach_sectors(raw)

    # Hard filters first
    filtered = S.apply_hard_filters(
        raw, min_turnover_cr=min_turnover_cr,
        require_above_ema200=require_above_ema200,
    )
    print(f"  {len(filtered)} survived hard filters", file=sys.stderr)

    if filtered.empty:
        return pd.DataFrame()

    scored = S.score_universe(filtered, horizon=horizon,
                              sector_neutral=sector_neutral)
    scored["reason"] = scored.apply(S.build_reason, axis=1)
    scored["turnover_cr"] = (scored["avg_turnover_20d"] / 1e7).round(2)

    if sector_neutral:
        final = S.apply_sector_cap(scored, top_n=top, max_per_sector=max_per_sector)
    else:
        final = scored.head(top)

    cols = ["rank", "final_score", "tactical_score", "structural_score",
            "sector", "turnover_cr", "reason"]
    result = final[cols].copy()
    for c in ["final_score", "tactical_score", "structural_score"]:
        result[c] = result[c].round(3)

    # Optional: attach a trade plan if capital provided
    if capital:
        plan = R.plan_portfolio(final.index.tolist(), universe,
                                capital=capital, risk_pct=risk_pct)
        if not plan.empty:
            print("\n=== TRADE PLAN ===", file=sys.stderr)
            print(plan.to_string())
            print(f"\nDeployed: ₹{plan.attrs['total_deployed']:,.0f} "
                  f"({plan.attrs['total_deployed_pct']}%) · "
                  f"Open risk: {plan.attrs['total_risk_pct']}% · "
                  f"{plan.attrs['positions']} positions")

    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", default="blend",
                    choices=["tactical", "structural", "blend"])
    ap.add_argument("--min-turnover", type=float, default=2.0)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--period", default="1y")
    ap.add_argument("--regime", action="store_true",
                    help="require price above 200-EMA")
    ap.add_argument("--sector-neutral", action="store_true",
                    help="z-score within sectors + cap names per sector")
    ap.add_argument("--max-per-sector", type=int, default=2)
    ap.add_argument("--capital", type=float, default=None,
                    help="if set, prints an ATR-based trade plan")
    ap.add_argument("--risk-pct", type=float, default=1.0)
    args = ap.parse_args()

    out = run(horizon=args.horizon, min_turnover_cr=args.min_turnover,
              top=args.top, period=args.period,
              require_above_ema200=args.regime,
              sector_neutral=args.sector_neutral,
              max_per_sector=args.max_per_sector,
              capital=args.capital, risk_pct=args.risk_pct)
    if not out.empty:
        pd.set_option("display.max_colwidth", 60)
        pd.set_option("display.width", 200)
        print("\n" + out.to_string(index=True))
