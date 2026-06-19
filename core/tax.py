"""
tax.py — Indian equity capital-gains tax estimator.

Helps you see the tax consequence of selling BEFORE you sell. Distinguishes:
  - STCG (held < 12 months): taxed at a flat short-term rate.
  - LTCG (held >= 12 months): taxed only on gains above a yearly exemption.

IMPORTANT: tax law changes. The 2024 Union Budget revised these rates. The
defaults below are configurable for exactly that reason — confirm the current
rate and exemption with a CA / the Income Tax site and adjust if needed. This
is an ESTIMATE to inform decisions, not tax advice or a filing.

Default assumptions (override if rules have changed):
  - STCG rate: 20%   (post-Jul-2024 rate for listed equity STT-paid)
  - LTCG rate: 12.5%  (post-Jul-2024 rate)
  - LTCG annual exemption: ₹1,25,000  (post-Jul-2024)
You can switch to the older 15% / 10% / ₹1,00,000 set if a holding's sale
falls under prior rules — pass them explicitly.
"""

from __future__ import annotations
from datetime import date, datetime


# Post-Jul-2024 defaults (CONFIRM before relying on these)
STCG_RATE = 0.20
LTCG_RATE = 0.125
LTCG_EXEMPTION = 125000.0
LONG_TERM_DAYS = 365


def _to_date(d) -> date | None:
    if d is None:
        return None
    if isinstance(d, date):
        return d
    try:
        return datetime.fromisoformat(str(d)).date()
    except Exception:
        try:
            return datetime.strptime(str(d), "%Y-%m-%d").date()
        except Exception:
            return None


def classify_holding(buy_date, as_of=None) -> dict:
    """Return holding term (STCG/LTCG) and days held."""
    bd = _to_date(buy_date)
    asof = _to_date(as_of) or date.today()
    if bd is None:
        return {"term": "UNKNOWN", "days_held": None,
                "note": "No buy date — can't classify. Enter purchase date."}
    days = (asof - bd).days
    term = "LTCG" if days >= LONG_TERM_DAYS else "STCG"
    note = ""
    if term == "STCG":
        days_to_lt = LONG_TERM_DAYS - days
        note = f"{days_to_lt} more days to reach long-term (lower tax)."
    return {"term": term, "days_held": days, "note": note}


def estimate_gain_tax(gain: float, term: str,
                      ltcg_used_exemption: float = 0.0,
                      stcg_rate: float = STCG_RATE,
                      ltcg_rate: float = LTCG_RATE,
                      ltcg_exemption: float = LTCG_EXEMPTION) -> dict:
    """
    Estimate tax on a single realized gain.
    ltcg_used_exemption: how much of the yearly LTCG exemption is already used by
                         other sales this financial year (so we don't double-count).
    """
    if gain <= 0:
        return {"tax": 0.0, "taxable": 0.0, "rate": 0.0,
                "note": "No gain (or a loss) — no tax; a loss may offset other gains."}

    if term == "STCG":
        tax = gain * stcg_rate
        return {"tax": round(tax, 0), "taxable": round(gain, 0),
                "rate": stcg_rate,
                "note": f"Short-term: taxed at {stcg_rate*100:.0f}% on the full gain."}

    if term == "LTCG":
        remaining_exemption = max(0.0, ltcg_exemption - ltcg_used_exemption)
        taxable = max(0.0, gain - remaining_exemption)
        tax = taxable * ltcg_rate
        if taxable == 0:
            note = (f"Long-term: within the ₹{ltcg_exemption:,.0f} yearly exemption "
                    f"(₹{remaining_exemption:,.0f} left) — likely ZERO tax.")
        else:
            note = (f"Long-term: ₹{remaining_exemption:,.0f} exemption applied, "
                    f"₹{taxable:,.0f} taxed at {ltcg_rate*100:.1f}%.")
        return {"tax": round(tax, 0), "taxable": round(taxable, 0),
                "rate": ltcg_rate, "note": note}

    return {"tax": 0.0, "taxable": 0.0, "rate": 0.0,
            "note": "Unknown holding term — enter a buy date to estimate tax."}


def sale_tax_preview(entry, price, shares_to_sell, buy_date,
                     ltcg_used_exemption=0.0, as_of=None, **rates) -> dict:
    """
    Full preview for selling `shares_to_sell` of a holding: realized gain,
    classification, and estimated tax.
    """
    gain = (price - entry) * shares_to_sell
    cls = classify_holding(buy_date, as_of)
    tax = estimate_gain_tax(gain, cls["term"],
                            ltcg_used_exemption=ltcg_used_exemption, **rates)
    net = gain - tax["tax"]
    return {
        "shares_sold": shares_to_sell,
        "realized_gain": round(gain, 0),
        "term": cls["term"],
        "days_held": cls["days_held"],
        "est_tax": tax["tax"],
        "net_after_tax": round(net, 0),
        "note": tax["note"],
        "term_note": cls["note"],
    }
