"""
glossary.py — Plain-English definitions for every term the dashboard shows.

Single source of truth so tooltips (help=...) and the in-app glossary panels
stay consistent. Keep each definition short, concrete, and jargon-free.
"""

GLOSSARY = {
    # --- Scores ---
    "Tactical score": "Is this stock hot RIGHT NOW? Based on the last few days to "
                      "weeks. Higher = moving up with energy.",
    "Structural score": "Has this stock been strong for MONTHS? Based on the slower, "
                        "bigger trend. Higher = healthy long-term climb.",
    "Final score": "The tactical and structural scores blended together. Higher = "
                   "the system likes it more. It ranks stocks against each other — "
                   "it is NOT a price prediction.",
    "Z-score": "A fair way to compare stocks: how far above or below average "
               "something is. +1 = above average, -1 = below average.",
    "Rank": "Where this stock sits in the list. #1 = the system's top pick today.",
    "Reason": "Plain words on WHY a stock ranks where it does.",
    "RSI": "A 0-100 'is it overbought or oversold' gauge. Very high (>70) can mean "
           "it ran up fast; very low (<30) can mean it's beaten down.",
    "ATR %": "How much the stock swings in a normal day, as a % of price. Bigger = "
             "jumpier stock.",
    "Sector": "The industry group (Bank, IT, Pharma...). Used to avoid accidentally "
              "betting everything on one industry.",

    # --- Market regime ---
    "Regime": "The overall mood/weather of the market. Like checking if it's sunny "
              "before planning a picnic.",
    "RISK-ON": "Market looks healthy — a reasonable time to be buying.",
    "CAUTION": "Mixed market — buy fewer things, be choosier.",
    "RISK-OFF": "Market is weak/falling — protect your money, avoid new buys.",
    "Drawdown": "How far something has fallen from its recent high. '-10%' means it "
                "dropped 10% from its peak.",
    "Breadth": "Are MOST stocks rising, or just a few? Wide breadth = healthier market.",
    "Exposure": "How much of your money the market mood suggests putting to work "
                "right now (100% = full, 0% = sit in cash).",

    # --- Trade plan / risk ---
    "Entry": "The price you buy at.",
    "Stop": "Your 'get out' price if the trade goes wrong. Caps your loss so a bad "
            "trade stays small.",
    "Target": "The price where you'd take your profit.",
    "ATR": "The stock's average daily price swing. Used to place your stop far "
           "enough away that normal wiggles don't kick you out.",
    "Position sizing": "How many shares to buy so that IF your stop is hit, you only "
                       "lose a small, fixed slice of your money.",
    "Risk per trade": "The slice of your total money you'd lose if this one trade "
                      "hits its stop (e.g. 1%).",
    "Reward:risk": "How much you aim to make vs lose. 2:1 = aiming for ₹2 gain for "
                   "every ₹1 you risk.",
    "Portfolio heat": "Your TOTAL risk across all open trades added up. A cap stops "
                      "you from betting too much at once.",
    "Capital deployed": "How much money is actually tied up in the trade.",

    # --- Positions / selling ---
    "HOLD": "Keep the position — it's doing fine.",
    "TRIM": "Sell PART of it — lock in some gains or reduce risk.",
    "EXIT": "Sell ALL of it — the reason to own it is gone, or your stop was hit.",
    "RAISE_STOP": "Move your stop UP to lock in profit as the stock rises.",
    "Trailing stop": "A stop that climbs up as the stock rises, protecting your "
                     "profit without selling too early.",
    "Open P&L": "Profit or loss on trades you still hold, if you sold right now.",
    "Realized P&L": "Profit or loss you've actually banked on closed trades.",

    # --- Testing ---
    "Backtest": "A practice run on past data: 'If I'd used this system before, would "
                "it have made money?'",
    "Walk-forward": "A stricter test: checks the system on data it never saw, to "
                    "catch strategies that only looked good by luck.",
    "Overfitting": "When a strategy secretly just memorized the past instead of "
                   "finding a real edge. Looks great on paper, fails with real money.",
    "Survivorship bias": "Testing only on stocks that survived and ignoring ones "
                         "that went bust — which makes results look better than reality.",
    "Sharpe": "A return-for-the-risk quality score. Higher = better returns without "
              "as many gut-wrenching swings.",
    "Alpha": "How much you beat the market (Nifty) by. Positive = you did better "
             "than just buying the index.",
    "Hit rate": "Out of all trades, what % made money.",
    "In-sample vs out-of-sample": "In-sample = data the system learned on. "
                                  "Out-of-sample = fresh data it was then tested on. "
                                  "Out-of-sample is the honest measure.",
}


def tip(term: str) -> str:
    """Return the plain-English definition for a term (for help= tooltips)."""
    return GLOSSARY.get(term, "")


def render_glossary_md(terms: list[str] | None = None) -> str:
    """Return a markdown bullet list of definitions, for an in-app expander."""
    items = terms if terms else list(GLOSSARY.keys())
    lines = []
    for t in items:
        if t in GLOSSARY:
            lines.append(f"- **{t}** — {GLOSSARY[t]}")
    return "\n".join(lines)
