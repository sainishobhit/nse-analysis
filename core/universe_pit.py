"""
universe_pit.py — Survivorship-bias-aware (point-in-time) universe.

THE PROBLEM (documented, and severe): backtesting on TODAY's index members
silently deletes every stock that was delisted, went bankrupt, or fell out of
the index. Research on the NIFTY Smallcap 250 showed this can exclude ~82% of
all names that ever appeared, inflating backtest Sharpe and returns massively.
A backtest built on current members is not just optimistic — it's measuring a
different, easier game than the one you'll actually play.

THE FIX: use point-in-time (PIT) membership — for any historical date, know
which stocks were ACTUALLY in your universe THEN, including ones now delisted.

This module defines the interface and a practical implementation path:
  - `PITUniverse` holds membership intervals: {symbol: [(start, end), ...]}.
  - `members_on(date)` returns who was tradeable on that date.
  - Includes a loader for a CSV of historical membership you can build/buy, plus
    a "best-effort" mode that at least WARNS you when you're running biased.

You cannot fully fix survivorship with free yfinance data (delisted tickers
vanish). Options, in order of rigor:
  1. Buy PIT constituent history (e.g. from your paid feed / NSE index factsheets).
  2. Reconstruct from NSE index change announcements (free but laborious).
  3. Accept the bias but QUANTIFY and DISCLOSE it (this module flags it loudly).
"""

from __future__ import annotations
import os
import pandas as pd
from datetime import date


class PITUniverse:
    def __init__(self, membership: dict | None = None, biased: bool = True):
        # membership: {symbol: [(start_date, end_date_or_None), ...]}
        self.membership = membership or {}
        self.biased = biased  # True = we're using current members (warn!)

    # ----- construction -----
    @classmethod
    def from_current(cls, symbols: list[str]):
        """Fallback: treat current symbols as always-present. BIASED — flagged."""
        today = date.today().isoformat()
        membership = {s: [("2000-01-01", None)] for s in symbols}
        return cls(membership, biased=True)

    @classmethod
    def from_csv(cls, path: str):
        """
        Load PIT membership from a CSV with columns:
            symbol, start_date, end_date
        end_date blank/empty = still a member. This is the UNBIASED path.
        """
        df = pd.read_csv(path)
        membership = {}
        for _, r in df.iterrows():
            sym = str(r["symbol"]).strip().upper()
            start = str(r["start_date"]).strip()
            end = str(r.get("end_date", "")).strip() or None
            membership.setdefault(sym, []).append((start, end))
        return cls(membership, biased=False)

    # ----- queries -----
    def members_on(self, d: str | date) -> list[str]:
        d = d.isoformat() if isinstance(d, date) else str(d)
        out = []
        for sym, intervals in self.membership.items():
            for start, end in intervals:
                if start <= d and (end is None or d <= end):
                    out.append(sym)
                    break
        return out

    def all_symbols_ever(self) -> list[str]:
        """Includes delisted/removed names — the whole point of PIT."""
        return sorted(self.membership.keys())

    def bias_warning(self) -> str | None:
        if self.biased:
            return ("⚠️ SURVIVORSHIP BIAS ACTIVE: backtest uses CURRENT universe "
                    "members only. Delisted/removed stocks are excluded, so results "
                    "are optimistic (often substantially). Load point-in-time "
                    "membership via PITUniverse.from_csv() for honest numbers.")
        return None


def build_membership_template(symbols: list[str], out_path: str) -> str:
    """
    Write a CSV template the user can fill in (or have their data vendor export)
    to create an unbiased PIT universe. One row per (symbol, membership window).
    """
    rows = [{"symbol": s, "start_date": "2018-01-01", "end_date": ""} for s in symbols]
    df = pd.DataFrame(rows)
    df.to_csv(out_path, index=False)
    return out_path
