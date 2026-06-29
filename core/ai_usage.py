"""
ai_usage.py — Local Claude API usage tracker.

Logs every call made via ai_analyst.analyze_stock() to a JSON file in the
project root. Keeps it simple: append-only log with timestamp, symbol, tokens,
cost. Privacy-first — never leaves your machine, gitignored alongside
portfolio.json. The AI Usage tab in the app reads from this log.
"""

from __future__ import annotations
import json
import os
import threading
from datetime import datetime, timezone, timedelta

_LOCK = threading.Lock()
_PATH = os.path.join(os.path.dirname(__file__), "..", "ai_usage.json")
MAX_RECORDS = 5000   # keep the log bounded


def _path() -> str:
    return os.path.abspath(_PATH)


def _empty() -> dict:
    return {"calls": []}


def load() -> dict:
    p = _path()
    if not os.path.exists(p):
        return _empty()
    try:
        with open(p, "r") as f:
            data = json.load(f)
        data.setdefault("calls", [])
        return data
    except (json.JSONDecodeError, OSError):
        return _empty()


def _save(data: dict) -> None:
    p = _path()
    # trim if too long
    if len(data.get("calls", [])) > MAX_RECORDS:
        data["calls"] = data["calls"][-MAX_RECORDS:]
    with _LOCK:
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, p)


def log_call(symbol: str, model: str, input_tokens: int, output_tokens: int,
             cost_inr: float, cached: bool = False, error: str | None = None) -> None:
    """Append one call record. Safe to call from anywhere; never raises."""
    try:
        data = load()
        data["calls"].append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": str(symbol).upper(),
            "model": model,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "cost_inr": float(cost_inr or 0.0),
            "cached": bool(cached),
            "error": error,
        })
        _save(data)
    except Exception:
        # never let logging crash the app
        pass


def _parse_ts(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def summary(window_hours: int = 24) -> dict:
    """Aggregate stats over the last `window_hours`."""
    data = load()
    calls = data.get("calls", [])
    if not calls:
        return {"calls": 0, "billable_calls": 0, "cached_calls": 0,
                "input_tokens": 0, "output_tokens": 0, "cost_inr": 0.0,
                "by_symbol": {}, "errors": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    recent = []
    for c in calls:
        ts = _parse_ts(c.get("ts"))
        if ts and ts >= cutoff:
            recent.append(c)

    billable = [c for c in recent if not c.get("cached") and not c.get("error")]
    cached = [c for c in recent if c.get("cached")]
    errors = [c for c in recent if c.get("error")]

    by_symbol = {}
    for c in billable:
        s = c.get("symbol", "?")
        by_symbol.setdefault(s, {"calls": 0, "cost_inr": 0.0, "tokens": 0})
        by_symbol[s]["calls"] += 1
        by_symbol[s]["cost_inr"] += float(c.get("cost_inr") or 0)
        by_symbol[s]["tokens"] += int(c.get("input_tokens", 0)) + int(c.get("output_tokens", 0))

    return {
        "calls": len(recent),
        "billable_calls": len(billable),
        "cached_calls": len(cached),
        "input_tokens": sum(int(c.get("input_tokens", 0)) for c in billable),
        "output_tokens": sum(int(c.get("output_tokens", 0)) for c in billable),
        "cost_inr": round(sum(float(c.get("cost_inr") or 0) for c in billable), 3),
        "by_symbol": by_symbol,
        "errors": len(errors),
    }


def daily_breakdown(days: int = 7) -> list[dict]:
    """Returns per-day stats for the last N days (oldest to newest)."""
    data = load()
    calls = data.get("calls", [])
    today = datetime.now(timezone.utc).date()
    buckets = {}
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        buckets[d.isoformat()] = {"date": d.isoformat(), "calls": 0,
                                  "cost_inr": 0.0, "tokens": 0}

    for c in calls:
        ts = _parse_ts(c.get("ts"))
        if ts is None:
            continue
        d = ts.date().isoformat()
        if d in buckets and not c.get("cached") and not c.get("error"):
            buckets[d]["calls"] += 1
            buckets[d]["cost_inr"] += float(c.get("cost_inr") or 0)
            buckets[d]["tokens"] += int(c.get("input_tokens", 0)) + int(c.get("output_tokens", 0))

    return list(buckets.values())


def recent_calls(n: int = 50) -> list[dict]:
    data = load()
    return list(reversed(data.get("calls", [])[-n:]))


def clear() -> None:
    """Wipe all usage history."""
    _save(_empty())
