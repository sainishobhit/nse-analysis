"""
data.py — Data ingestion for the NSE trading system.

Default path uses yfinance (free) with `.NS` tickers. Designed so you can
swap in a paid feed (Zerodha Kite / Upstox / TrueData) by replacing
`fetch_ohlcv` with your provider's call — the rest of the system is agnostic.

Includes a starter universe (Nifty 200 constituents) so you can run today.
Replace UNIVERSE with the full NSE list once your paid feed is wired in.
"""

from __future__ import annotations
import time
import pandas as pd
import yfinance as yf

BENCHMARK = "^NSEI"  # Nifty 50 index

# Starter universe — liquid large/mid caps. Expand freely.
UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "SBIN", "BHARTIARTL",
    "ITC", "LT", "KOTAKBANK", "AXISBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI",
    "SUNPHARMA", "TITAN", "ASIANPAINT", "NTPC", "ONGC", "TATAMOTORS",
    "POWERGRID", "ULTRACEMCO", "WIPRO", "ADANIENT", "ADANIPORTS", "COALINDIA",
    "BAJAJFINSV", "NESTLEIND", "TATASTEEL", "JSWSTEEL", "HCLTECH", "GRASIM",
    "HINDALCO", "TECHM", "DRREDDY", "CIPLA", "BPCL", "BRITANNIA", "EICHERMOT",
    "DIVISLAB", "HEROMOTOCO", "INDUSINDBK", "M&M", "APOLLOHOSP", "TATACONSUM",
    "BAJAJ-AUTO", "SBILIFE", "HDFCLIFE", "DLF", "VEDL", "GODREJCP", "DABUR",
    "HAVELLS", "PIDILITIND", "SIEMENS", "PNB", "BANKBARODA", "TRENT", "NAUKRI",
    "ZOMATO", "PAYTM", "IRCTC", "IDEA", "YESBANK", "BEL", "HAL", "MAZDOCK",
]


def to_yf(symbol: str) -> str:
    return f"{symbol}.NS"


def fetch_ohlcv(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame | None:
    """Fetch OHLCV for one symbol. Returns None on failure."""
    try:
        t = yf.Ticker(to_yf(symbol))
        df = t.history(period=period, interval=interval, auto_adjust=True)
        if df is None or df.empty:
            return None
        df = df.rename(columns=str.title)  # ensure Open/High/Low/Close/Volume
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception:
        return None


def fetch_benchmark(period: str = "1y") -> pd.Series | None:
    try:
        df = yf.Ticker(BENCHMARK).history(period=period, auto_adjust=True)
        return df["Close"].dropna() if df is not None and not df.empty else None
    except Exception:
        return None


def fetch_universe(symbols=None, period: str = "1y", pause: float = 0.0) -> dict:
    """Returns {symbol: ohlcv_df}. Skips failures silently."""
    symbols = symbols or UNIVERSE
    out = {}
    for s in symbols:
        df = fetch_ohlcv(s, period=period)
        if df is not None and len(df) >= 30:
            out[s] = df
        if pause:
            time.sleep(pause)
    return out
