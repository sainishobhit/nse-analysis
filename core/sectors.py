"""
sectors.py — NSE symbol → sector map + sector-neutral utilities.

Why sector-neutral matters: a naive screen just buys whatever sector is hot
(all PSU banks, all defence, all realty). That's a concentrated sector bet
wearing a stock-picker's costume. Sector-neutral ranking compares each stock
to its OWN sector's peers, so you surface the best name WITHIN each sector and
control sector concentration deliberately instead of by accident.

The map below covers the starter universe. When you wire in your paid feed,
load the full sector classification from your provider (Zerodha/Upstox expose
it, or use NSE's industry index constituents) and replace SECTOR_MAP.
"""

from __future__ import annotations
import pandas as pd

# Starter sector map (NIFTY-style sector buckets).
SECTOR_MAP = {
    # Financials — Banks
    "HDFCBANK": "Bank", "ICICIBANK": "Bank", "SBIN": "Bank", "KOTAKBANK": "Bank",
    "AXISBANK": "Bank", "INDUSINDBK": "Bank", "PNB": "Bank", "BANKBARODA": "Bank",
    "YESBANK": "Bank",
    # Financials — NBFC/Insurance
    "BAJFINANCE": "Financial Services", "BAJAJFINSV": "Financial Services",
    "SBILIFE": "Financial Services", "HDFCLIFE": "Financial Services",
    "PAYTM": "Financial Services",
    # IT
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
    # FMCG
    "ITC": "FMCG", "HINDUNILVR": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG",
    "TATACONSUM": "FMCG", "GODREJCP": "FMCG", "DABUR": "FMCG",
    # Auto
    "MARUTI": "Auto", "TATAMOTORS": "Auto", "EICHERMOT": "Auto",
    "HEROMOTOCO": "Auto", "M&M": "Auto", "BAJAJ-AUTO": "Auto",
    # Pharma/Healthcare
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma",
    "DIVISLAB": "Pharma", "APOLLOHOSP": "Pharma",
    # Energy / Oil & Gas
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy", "COALINDIA": "Energy",
    "NTPC": "Power", "POWERGRID": "Power",
    # Metals
    "TATASTEEL": "Metals", "JSWSTEEL": "Metals", "HINDALCO": "Metals", "VEDL": "Metals",
    # Materials / Cement / Chemicals
    "ULTRACEMCO": "Cement", "GRASIM": "Cement", "ASIANPAINT": "Materials",
    "PIDILITIND": "Materials",
    # Telecom
    "BHARTIARTL": "Telecom", "IDEA": "Telecom",
    # Capital Goods / Defence / Infra
    "LT": "Capital Goods", "SIEMENS": "Capital Goods", "HAVELLS": "Capital Goods",
    "BEL": "Defence", "HAL": "Defence", "MAZDOCK": "Defence",
    # Consumer / Retail / Misc
    "TITAN": "Consumer Durables", "TRENT": "Retail", "DLF": "Realty",
    "ADANIENT": "Conglomerate", "ADANIPORTS": "Infrastructure",
    "ZOMATO": "Internet", "NAUKRI": "Internet", "IRCTC": "Services",
}

DEFAULT_SECTOR = "Other"


def sector_of(symbol: str) -> str:
    return SECTOR_MAP.get(symbol, DEFAULT_SECTOR)


def attach_sectors(df: pd.DataFrame) -> pd.DataFrame:
    """Add a 'sector' column based on the index (symbol)."""
    df = df.copy()
    df["sector"] = [sector_of(s) for s in df.index]
    return df
