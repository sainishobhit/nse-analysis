"""
screener_presets.py — Library of named Screener.in queries.

Each preset has:
  - name: short identifier
  - description: 1-line plain English of what it finds
  - query: the exact Screener.in query string to paste into their builder
  - category: grouping for the UI (Growth, Quality, Value, Momentum, Special)

Workflow stays the same: user picks a preset → copies the query → pastes into
Screener.in → exports CSV → uploads to our app. The app handles the rest.
"""

from __future__ import annotations

PRESETS = [
    {
        "name": "Tod Fod Growth",
        "category": "Growth",
        "description": "50%+ profit growth, close to 52W high, low debt — explosive growth stocks.",
        "query": """Profit after tax latest quarter > 50% AND
Sales growth > 20% AND
From 52w high < 15% AND
Debt to equity < 0.7""",
    },
    {
        "name": "Improving OPMs",
        "category": "Quality",
        "description": "Mid-caps (₹1k–15k cr) with rising operating margins, healthy ROCE.",
        "query": """OPM > OPM last year AND
Return on capital employed preceding year > Average return on capital employed 3Years AND
Return on equity > 15% AND
Pledged percentage = 0% AND
Market Capitalization > 1000 AND
Market Capitalization < 15000""",
    },
    {
        "name": "Piotroski",
        "category": "Quality",
        "description": "High Piotroski score (>7) with ROCE >15% and consistent sales growth.",
        "query": """Piotroski score > 7 AND
Return on capital employed > 15% AND
Sales growth 3Years > 15% AND
Market Capitalization > 1000 AND
Market Capitalization < 15000""",
    },
    {
        "name": "Debt Reduction + ROCE Expansion",
        "category": "Quality",
        "description": "PE <30, reducing debt while improving ROCE — quiet improvers.",
        "query": """Debt 3Years back > Debt AND
Profit growth 3Years > 15 AND
Return on capital employed > Return on capital employed preceding year AND
Market Capitalization > 1000 AND
Market Capitalization < 15000 AND
Price to Earning < 30""",
    },
    {
        "name": "Variant Perception",
        "category": "Quality",
        "description": "PEG <1.5 with broad-based improvement — undervalued compounders.",
        "query": """Profit growth > 15% AND
Sales growth > 15% AND
Debt < Debt preceding year AND
Return on capital employed > Return on capital employed preceding year AND
OPM > OPM 5Year AND
Promoter holding > 50% AND
PEG Ratio < 1.5""",
    },
    {
        "name": "OPM 20%+",
        "category": "Quality",
        "description": "Sustained high operating margins (5-year), strong growth.",
        "query": """OPM 5Year > 20% AND
Sales growth 3Years > 15% AND
Profit growth 3Years > 15% AND
Market Capitalization > 1000 AND
Market Capitalization < 15000""",
    },
    {
        "name": "50% Gross Block Growth",
        "category": "Growth",
        "description": "Heavy capex — gross block grew 50%+ this year, ROCE >15%.",
        "query": """Gross block > 1.5 * Gross block preceding year AND
Market Capitalization > 1000 AND
Return on capital employed > 15%""",
    },
    {
        "name": "CANSLIM",
        "category": "Momentum",
        "description": "High-growth stocks before institutions fully load up.",
        "query": """YOY Quarterly sales growth > 15 AND
YOY Quarterly profit growth > 20 AND
Return on capital employed > 15% AND
Market Capitalization > 1000""",
    },
    {
        "name": "Capex Companies",
        "category": "Growth",
        "description": "CWIP exceeds current net block — companies in major build-out.",
        "query": """Capital work in progress > Net block""",
    },
    {
        "name": "Dividend Companies",
        "category": "Quality",
        "description": "Returning capital — buybacks (fewer shares) plus 20%+ payout.",
        "query": """Number of equity shares < Number of equity shares 10years back AND
Dividend Payout > 20%""",
    },
    {
        "name": "FII + Momentum",
        "category": "Momentum",
        "description": "FII buying steadily for 3 years, stock near 52w high.",
        "query": """Change in FII holding 3Years > 10% AND
From 52w high < 15% AND
Market Capitalization > 1000""",
    },
    {
        "name": "FII + DII Lapping (3Y)",
        "category": "Momentum",
        "description": "Combined institutional buying of 10%+ over 3 years.",
        "query": """Change in DII holding 3Years > 5% AND
Change in FII holding 3Years > 5%""",
    },
    {
        "name": "FII + DII Lapping (1Y)",
        "category": "Momentum",
        "description": "Combined institutional buying of 6%+ in just 1 year.",
        "query": """Change in FII holding > 3% AND
Change in DII holding > 3%""",
    },
    {
        "name": "Promoter + FII + DII Buying",
        "category": "Momentum",
        "description": "Early signs — incremental promoter, FII, and DII buying.",
        "query": """Promoter holding > 0.1% AND
Change in FII holding 3Years > 1% AND
Change in DII holding 3Years > 1%""",
    },
    {
        "name": "Turnaround Candidates (17-condition)",
        "category": "Special",
        "description": "The classic value + quality + momentum combo — recent turnarounds.",
        "query": """Price to Earning > 0 AND
Price to book value < 5 AND
Debt to equity < 1 AND
Dividend yield > 0 AND
Unpledged promoter holding > 45 AND
Price to Earning < 25 AND
Market Capitalization < 10000 AND
Profit growth 3Years < 10 AND
Profit growth > 15 AND
Net Profit latest quarter > 0 AND
Volume 1month average > Volume 1year average AND
YOY Quarterly sales growth > 15 AND
YOY Quarterly profit growth > 20 AND
Return on capital employed > 15 AND
Market Capitalization > 1000 AND
Price to Earning < 30 AND
OPM > OPM preceding year""",
    },
    {
        "name": "Capacity Expansion",
        "category": "Growth",
        "description": "Fixed assets doubled in 3 years or grew 50%+ this year.",
        "query": """((Sales growth 3Years > 12% AND
Net block > Net block 3Years back * 2)
OR
(Net block + Capital work in progress > 1.5 * (Net block preceding year + Capital work in progress preceding year)))
AND
Sales last year > 25 AND
Debt to equity < 3 AND
Market Capitalization > 25""",
    },
]


def by_name(name: str) -> dict | None:
    for p in PRESETS:
        if p["name"] == name:
            return p
    return None


def categories() -> list[str]:
    seen = []
    for p in PRESETS:
        if p["category"] not in seen:
            seen.append(p["category"])
    return seen


def by_category(cat: str) -> list[dict]:
    return [p for p in PRESETS if p["category"] == cat]


def all_names() -> list[str]:
    return [p["name"] for p in PRESETS]
