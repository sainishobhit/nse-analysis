"""
guardrails.py — Protection FROM YOURSELF.

The SEBI data is blunt: most retail traders lose, and the losers trade MORE,
hold losers, oversize, and chase. A good system refuses to enable those
patterns. These guardrails inspect intended actions + recent behavior and raise
warnings or hard blocks BEFORE a mistake is made.

None of this restricts you from overriding in your broker — the system can't and
shouldn't place orders. It exists to make the bad decision LOUD instead of easy.

Checks:
  1. OVERTRADING        — too many trades in a short window.
  2. REVENGE TRADING    — sharp re-entry right after a stop-out / red day.
  3. CONCENTRATION      — too much capital / risk in one name or sector.
  4. RISK BUDGET        — aggregate open risk above the heat cap.
  5. STOP DISCIPLINE    — entering without a stop, or a stop too wide/narrow.
  6. AVERAGING DOWN     — adding to a losing position (classic account-killer).
  7. POSITION SIZE      — single position exceeds max % of capital.
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta


WARN = "WARN"
BLOCK = "BLOCK"
OK = "OK"


def _today():
    return datetime.now(timezone.utc).date()


def check_new_trade(
    intended: dict,          # {symbol, entry, shares, stop, sector}
    capital: float,
    open_positions: list[dict],
    closed_positions: list[dict],
    risk_pct_intended: float,
    *,
    max_positions: int = 8,
    max_position_pct: float = 20.0,
    max_sector_positions: int = 2,
    max_total_risk_pct: float = 6.0,
    max_trades_per_day: int = 3,
    min_stop_pct: float = 1.0,
    max_stop_pct: float = 15.0,
) -> list[dict]:
    """Return a list of guardrail findings for a NEW intended trade."""
    findings = []
    sym = intended.get("symbol", "?")
    entry = float(intended.get("entry", 0) or 0)
    shares = int(intended.get("shares", 0) or 0)
    stop = float(intended.get("stop", 0) or 0)
    sector = intended.get("sector", "Other")

    # 1. Overtrading (count today's closed entries + opens)
    today = _today()
    todays_closes = sum(
        1 for p in closed_positions
        if str(p.get("exit_date", "")) == str(today)
    )
    if todays_closes >= max_trades_per_day:
        findings.append({"level": WARN, "rule": "Overtrading",
            "msg": f"{todays_closes} trades already closed today. "
                   f"More than {max_trades_per_day}/day correlates with worse outcomes."})

    # 2. Revenge trading — re-entering the SAME name just stopped out today
    for p in closed_positions:
        if (p.get("symbol") == sym and str(p.get("exit_date", "")) == str(today)
                and "stop" in str(p.get("exit_reason", "")).lower()):
            findings.append({"level": WARN, "rule": "Revenge trade",
                "msg": f"You were stopped out of {sym} today. Re-entering same day "
                       f"is often emotional, not analytical. Sit on your hands."})

    # 3. Position-count cap
    if len(open_positions) >= max_positions:
        findings.append({"level": WARN, "rule": "Too many positions",
            "msg": f"Already holding {len(open_positions)}. Beyond {max_positions} "
                   f"you can't monitor them properly."})

    # 4. Sector concentration
    sec_count = sum(1 for p in open_positions if p.get("sector") == sector)
    if sec_count >= max_sector_positions:
        findings.append({"level": WARN, "rule": "Sector concentration",
            "msg": f"Already {sec_count} positions in {sector}. Adding more turns "
                   f"a stock bet into a sector bet."})

    # 5. Single-position size
    if entry > 0 and shares > 0:
        pos_pct = (entry * shares) / capital * 100
        if pos_pct > max_position_pct:
            findings.append({"level": BLOCK, "rule": "Position too large",
                "msg": f"{sym} would be {pos_pct:.0f}% of capital "
                       f"(max {max_position_pct:.0f}%). One position shouldn't sink you."})

    # 6. Stop discipline
    if stop <= 0:
        findings.append({"level": BLOCK, "rule": "No stop",
            "msg": f"No stop-loss set for {sym}. Entering without a stop is the "
                   f"single most expensive habit in retail trading."})
    elif entry > 0:
        stop_pct = abs(entry - stop) / entry * 100
        if stop_pct < min_stop_pct:
            findings.append({"level": WARN, "rule": "Stop too tight",
                "msg": f"Stop is {stop_pct:.1f}% away — inside normal noise, you'll "
                       f"get whipsawed out."})
        elif stop_pct > max_stop_pct:
            findings.append({"level": WARN, "rule": "Stop too wide",
                "msg": f"Stop is {stop_pct:.1f}% away — that's a big loss if hit. "
                       f"Size down or tighten."})

    # 7. Risk budget (aggregate heat)
    if entry > 0 and shares > 0 and stop > 0:
        trade_risk = abs(entry - stop) * shares
        trade_risk_pct = trade_risk / capital * 100
        existing_risk_pct = 0.0
        for p in open_positions:
            if p.get("stop") and p.get("entry_price") and p.get("shares"):
                existing_risk_pct += abs(p["entry_price"] - p["stop"]) * p["shares"] / capital * 100
        total = existing_risk_pct + trade_risk_pct
        if total > max_total_risk_pct:
            findings.append({"level": BLOCK, "rule": "Risk budget exceeded",
                "msg": f"This trade pushes open portfolio risk to {total:.1f}% "
                       f"(cap {max_total_risk_pct:.0f}%). Close something first or size down."})

    if not findings:
        findings.append({"level": OK, "rule": "Clear",
            "msg": "No guardrail flags. Trade fits your risk framework."})
    return findings


def check_add_to_position(intended_symbol: str, add_price: float,
                          open_positions: list[dict]) -> list[dict]:
    """Catch averaging DOWN — adding to a loser."""
    findings = []
    for p in open_positions:
        if p.get("symbol") == intended_symbol:
            if add_price < p.get("entry_price", add_price):
                findings.append({"level": WARN, "rule": "Averaging down",
                    "msg": f"Adding to {intended_symbol} below your entry "
                           f"(₹{add_price} < ₹{p['entry_price']}). Averaging down on "
                           f"losers is how small losses become account-enders. "
                           f"Add to WINNERS, not losers."})
    return findings


def daily_loss_circuit_breaker(closed_positions: list[dict], capital: float,
                               max_daily_loss_pct: float = 3.0) -> dict | None:
    """If today's realized losses exceed a threshold, tell the user to STOP."""
    today = str(_today())
    todays_pnl = sum(
        p.get("pnl", 0) for p in closed_positions
        if str(p.get("exit_date", "")) == today
    )
    loss_pct = todays_pnl / capital * 100
    if loss_pct <= -max_daily_loss_pct:
        return {"level": BLOCK, "rule": "Daily loss limit",
                "msg": f"Down {loss_pct:.1f}% today (₹{todays_pnl:,.0f}). "
                       f"You've hit your daily stop. Close the laptop. Trading "
                       f"through red days is how good systems get blown up by bad emotions."}
    return None
