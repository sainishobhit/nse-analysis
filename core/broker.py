"""
broker.py — Broker integration stub (read-only holdings import).

You chose "connect broker API later" — this is the seam for that. Today it
returns nothing; wire in your broker to auto-import holdings so you don't type
them. The system NEVER places orders — it only READS holdings. You execute
trades yourself in your broker app. (This is also the SEBI-safe design: never
share your broker password with any tool; use official OAuth token flows only.)

To implement for Zerodha Kite (example):
    from kiteconnect import KiteConnect
    kite = KiteConnect(api_key=...)
    # user completes login → request_token → access_token (OAuth)
    holdings = kite.holdings()
    return [_normalize(h) for h in holdings]

Upstox / Angel One / Dhan all expose similar read-only holdings endpoints.
"""

from __future__ import annotations


def fetch_holdings_from_broker(provider: str = None, credentials: dict = None) -> list[dict]:
    """
    STUB. Returns []. Implement per-broker to return a list of holdings dicts:
        {"symbol": "EDELWEISS", "entry_price": 69.0, "shares": 300}
    Use the broker's OFFICIAL OAuth flow. Never accept raw passwords.
    """
    return []


def is_connected(provider: str = None) -> bool:
    return False


def normalize_holding(raw: dict) -> dict:
    """Map a broker's holding object to our internal shape. Customize per broker."""
    return {
        "symbol": str(raw.get("tradingsymbol", raw.get("symbol", ""))).upper(),
        "entry_price": float(raw.get("average_price", raw.get("avg_cost", 0)) or 0),
        "shares": int(raw.get("quantity", raw.get("qty", 0)) or 0),
    }
