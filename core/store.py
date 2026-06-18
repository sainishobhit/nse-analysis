"""
store.py — Dead-simple local persistence (JSON).

The exit monitor is useless if the app forgets what you hold the moment you
close it. This module persists positions (and anything else) to a JSON file
next to the app. No database to install, human-readable, git-ignorable.

Swap to SQLite later if you outgrow it — the interface (load/save/add/remove)
stays the same so nothing downstream changes.
"""

from __future__ import annotations
import json
import os
import threading
from datetime import datetime, timezone

_LOCK = threading.Lock()
_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "portfolio.json")


def _path(path: str | None = None) -> str:
    return os.path.abspath(path or _DEFAULT_PATH)


def _empty_store() -> dict:
    return {"positions": [], "closed": [], "meta": {"updated": None}}


def load(path: str | None = None) -> dict:
    p = _path(path)
    if not os.path.exists(p):
        return _empty_store()
    try:
        with open(p, "r") as f:
            data = json.load(f)
        # ensure keys exist
        for k, v in _empty_store().items():
            data.setdefault(k, v)
        return data
    except (json.JSONDecodeError, OSError):
        return _empty_store()


def save(data: dict, path: str | None = None) -> None:
    p = _path(path)
    data.setdefault("meta", {})["updated"] = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, p)  # atomic write


# --------------------------------------------------------------------------
# Position helpers
# --------------------------------------------------------------------------
def add_position(symbol: str, entry_price: float, shares: int,
                 stop: float, target: float | None = None,
                 entry_date: str | None = None, note: str = "",
                 path: str | None = None) -> dict:
    data = load(path)
    pos = {
        "id": f"{symbol}-{int(datetime.now(timezone.utc).timestamp())}",
        "symbol": symbol.strip().upper().replace(".NS", ""),
        "entry_price": float(entry_price),
        "shares": int(shares),
        "stop": float(stop),
        "initial_stop": float(stop),
        "target": float(target) if target else None,
        "entry_date": entry_date or datetime.now(timezone.utc).date().isoformat(),
        "note": note,
    }
    data["positions"].append(pos)
    save(data, path)
    return pos


def remove_position(pos_id: str, path: str | None = None) -> None:
    data = load(path)
    data["positions"] = [p for p in data["positions"] if p["id"] != pos_id]
    save(data, path)


def close_position(pos_id: str, exit_price: float, reason: str = "",
                   path: str | None = None) -> None:
    """Move a position from open → closed with realized P&L."""
    data = load(path)
    keep, closed = [], None
    for p in data["positions"]:
        if p["id"] == pos_id:
            closed = dict(p)
        else:
            keep.append(p)
    if closed:
        closed["exit_price"] = float(exit_price)
        closed["exit_date"] = datetime.now(timezone.utc).date().isoformat()
        closed["exit_reason"] = reason
        closed["pnl"] = round((exit_price - closed["entry_price"]) * closed["shares"], 2)
        closed["pnl_pct"] = round((exit_price / closed["entry_price"] - 1) * 100, 2)
        data["closed"].append(closed)
    data["positions"] = keep
    save(data, path)


def update_stop(pos_id: str, new_stop: float, path: str | None = None) -> None:
    data = load(path)
    for p in data["positions"]:
        if p["id"] == pos_id:
            p["stop"] = float(new_stop)
    save(data, path)
