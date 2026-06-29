"""
groww_import.py — Import holdings from Groww MCP via Claude.ai.

Why this design: Groww MCP is hosted by Groww and authenticates through your
claude.ai Pro session — not via a public REST API your local app can call. The
practical bridge: ask Claude (in claude.ai) to dump your holdings as JSON, then
paste it here. Tolerant parser — accepts several common shapes Claude might
return (the raw Groww API shape, simplified arrays, or Claude's prose-wrapped
JSON).

Usage in the app: a textarea where the user pastes Claude's output, then a
button that calls parse_paste(text) → list[dict] of holdings ready to go into
the store.
"""

from __future__ import annotations
import json
import re
from datetime import datetime, date


# Common Groww symbol prefixes we strip / normalize
def _clean_symbol(s: str) -> str:
    if not s:
        return ""
    s = str(s).strip().upper()
    # remove exchange suffixes
    for suf in (".NS", ".BO", "-EQ", "-BE"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s.strip()


def _to_float(v, default=0.0) -> float:
    if v is None:
        return default
    try:
        return float(str(v).replace(",", "").replace("₹", "").strip())
    except (ValueError, TypeError):
        return default


def _to_int(v, default=0) -> int:
    return int(round(_to_float(v, default)))


def _to_date(v) -> str | None:
    """Try several common date formats. Returns ISO date string or None."""
    if v is None or not str(v).strip():
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d",
                "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    # ISO with time
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _normalize_one(raw: dict) -> dict | None:
    """Map any one holding dict from MCP-ish output to our internal shape."""
    if not isinstance(raw, dict):
        return None

    sym = (raw.get("trading_symbol") or raw.get("symbol")
           or raw.get("tradingsymbol") or raw.get("ticker") or raw.get("name"))
    qty = (raw.get("quantity") or raw.get("qty")
           or raw.get("shares") or raw.get("holdings"))
    avg = (raw.get("average_price") or raw.get("avg_price")
           or raw.get("avg_cost") or raw.get("buy_price") or raw.get("price"))
    bdate = (raw.get("buy_date") or raw.get("purchase_date")
             or raw.get("entry_date") or raw.get("date"))

    sym = _clean_symbol(sym)
    if not sym:
        return None
    qty = _to_int(qty)
    avg = _to_float(avg)
    if qty <= 0 or avg <= 0:
        return None

    out = {
        "symbol": sym,
        "shares": qty,
        "entry_price": round(avg, 2),
        "stop": round(avg * 0.9, 2),  # default 10% below entry; user can edit
        "entry_date": _to_date(bdate),
    }
    return out


def _extract_json_blocks(text: str) -> list:
    """Find one or more JSON blocks in free-form text (Claude often wraps in ```json fences)."""
    blocks = []
    # 1) fenced ```json ... ```
    fenced = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    for f in fenced:
        try:
            blocks.append(json.loads(f))
        except json.JSONDecodeError:
            pass
    if blocks:
        return blocks
    # 2) try the whole text
    try:
        blocks.append(json.loads(text.strip()))
        return blocks
    except json.JSONDecodeError:
        pass
    # 3) try to grab the first {...} or [...] substring
    for pat in (r"\[.*\]", r"\{.*\}"):
        m = re.search(pat, text, re.DOTALL)
        if m:
            try:
                blocks.append(json.loads(m.group(0)))
                return blocks
            except json.JSONDecodeError:
                continue
    return blocks


def parse_paste(text: str) -> dict:
    """
    Parse pasted text from Claude's MCP output.
    Returns {"holdings": [...], "skipped": [...], "raw_count": N, "warnings": [...]}
    """
    result = {"holdings": [], "skipped": [], "raw_count": 0, "warnings": []}
    if not text or not text.strip():
        result["warnings"].append("Empty input.")
        return result

    blocks = _extract_json_blocks(text)
    if not blocks:
        result["warnings"].append(
            "Couldn't find JSON in the paste. Ask Claude to return holdings as a "
            "JSON array (e.g. `[{symbol, quantity, average_price, buy_date}]`)."
        )
        return result

    # collect candidate dicts from any reasonable nesting
    candidates = []
    for blk in blocks:
        if isinstance(blk, list):
            candidates.extend(blk)
        elif isinstance(blk, dict):
            # common Groww shape: {"holdings": [...]} or {"data": [...]}
            for key in ("holdings", "data", "positions", "results"):
                if key in blk and isinstance(blk[key], list):
                    candidates.extend(blk[key])
                    break
            else:
                # might be a single holding dict
                candidates.append(blk)

    result["raw_count"] = len(candidates)
    for raw in candidates:
        norm = _normalize_one(raw)
        if norm:
            result["holdings"].append(norm)
        else:
            result["skipped"].append(raw)
    return result


# convenience: the prompt the user should send to Claude
SUGGESTED_PROMPT = (
    "Using the Groww MCP connector, get my current holdings and return them as a "
    "JSON array only — no prose. For each holding include: trading_symbol, "
    "quantity, average_price, and buy_date if available. Use this exact shape:\n\n"
    "```json\n"
    "[\n"
    "  {\"trading_symbol\": \"EDELWEISS\", \"quantity\": 300, "
    "\"average_price\": 69.00, \"buy_date\": \"2023-01-15\"}\n"
    "]\n"
    "```"
)
