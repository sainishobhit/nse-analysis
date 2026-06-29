"""
screener_import.py — Import Screener.in fundamental-screen CSV exports.

Workflow:
  1. User runs their fundamental query on Screener.in.
  2. Clicks Export -> CSV.
  3. Uploads the file in the app.
  4. This module normalises it to a list of {symbol, name, fundamentals_dict}.

Screener's CSVs vary depending on which columns the user picked. Common ones
we try to recognise (case-insensitive, flexible):
  - Name (company name)
  - NSE Code / BSE Code / Symbol  → ticker
  - Current Price
  - Market Capitalization / Market Cap
  - Price to Earning / P/E
  - Price to Book / P/B
  - Debt to equity
  - Dividend yield
  - Return on capital employed / ROCE
  - Profit growth, Sales growth (YoY/3Y)
  - OPM, OPM preceding year
  - Promoter holding / Unpledged promoter holding

If a column isn't present, that field is just left blank — the AI Read and any
display gracefully degrade. The ticker is the only HARD requirement.
"""

from __future__ import annotations
import io
import re
import pandas as pd


# A registry of common Screener column names → our canonical keys.
# Each canonical key maps to a list of likely header strings (lowercased).
COLUMN_ALIASES = {
    "symbol":        ["nse code", "bse code", "symbol", "ticker", "scrip"],
    "name":          ["name", "company", "company name"],
    "price":         ["current price", "cmp", "price"],
    "market_cap":    ["market capitalization", "market cap", "mcap"],
    "pe":            ["price to earning", "price to earnings", "p/e", "pe"],
    "pb":            ["price to book value", "price to book", "p/b", "pb"],
    "de":            ["debt to equity", "d/e", "debt/equity"],
    "div_yield":     ["dividend yield", "div yield"],
    "promoter_holding":  ["promoter holding"],
    "unpledged_promoter": ["unpledged promoter holding"],
    "roce":          ["return on capital employed", "roce"],
    "roe":           ["return on equity", "roe"],
    "profit_growth_3y": ["profit growth 3 years", "profit growth 3years",
                         "3 year profit growth", "profit growth 3y"],
    "profit_growth":     ["profit growth"],
    "sales_growth_qoq":  ["yoy quarterly sales growth", "qoq sales growth",
                          "sales growth yoy"],
    "profit_growth_qoq": ["yoy quarterly profit growth", "qoq profit growth",
                          "profit growth yoy"],
    "net_profit_latest": ["net profit latest quarter", "net profit"],
    "opm":           ["opm", "operating profit margin"],
    "opm_preceding": ["opm preceding year", "opm last year"],
    "volume_1m":     ["volume 1month average", "volume 1m", "1m volume"],
    "volume_1y":     ["volume 1year average", "volume 1y", "1y volume"],
    "industry":      ["industry", "sector"],
}


def _normalise_col(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _to_num(v):
    """Convert Screener's mixed numeric strings (₹1,234.5 / 12.3% / -- ) to float."""
    if v is None or pd.isna(v):
        return None
    s = str(v).strip().replace(",", "").replace("₹", "").replace("%", "")
    if s in ("", "--", "-", "NA", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _clean_symbol(s) -> str:
    if s is None or pd.isna(s):
        return ""
    s = str(s).strip().upper()
    for suf in (".NS", ".BO", "-EQ", "-BE"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s.strip()


def parse_csv(file_like_or_text) -> dict:
    """
    Parse a Screener.in export.
    Accepts a file path, file-like object, raw CSV string, or pandas DataFrame.
    Returns: {
        "stocks": [{symbol, name, fundamentals: {...}}],
        "raw_count": int,           # rows read
        "kept_count": int,          # rows with usable symbol
        "warnings": [str],
        "columns_recognised": {canonical: original_column_name, ...},
    }
    """
    out = {"stocks": [], "raw_count": 0, "kept_count": 0,
           "warnings": [], "columns_recognised": {}}

    # Load into a DataFrame
    try:
        if isinstance(file_like_or_text, pd.DataFrame):
            df = file_like_or_text.copy()
        elif isinstance(file_like_or_text, str) and not file_like_or_text.startswith(("/", ".", "C:")):
            # treat as raw CSV text
            df = pd.read_csv(io.StringIO(file_like_or_text))
        else:
            df = pd.read_csv(file_like_or_text)
    except Exception as e:
        out["warnings"].append(f"Couldn't read CSV: {e}")
        return out

    if df.empty:
        out["warnings"].append("CSV is empty.")
        return out

    # Map each actual column header to a canonical key, if we can
    col_map = {}  # canonical -> original column
    available = {_normalise_col(c): c for c in df.columns}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in available:
                col_map[canonical] = available[alias]
                break
    out["columns_recognised"] = {k: v for k, v in col_map.items()}
    out["raw_count"] = len(df)

    if "symbol" not in col_map and "name" not in col_map:
        out["warnings"].append(
            "Couldn't find a symbol/ticker or name column. "
            "Make sure your Screener export includes 'NSE Code' or 'Name'."
        )
        return out

    sym_col = col_map.get("symbol")
    name_col = col_map.get("name")

    for _, row in df.iterrows():
        sym = _clean_symbol(row[sym_col]) if sym_col else ""
        name = str(row[name_col]).strip() if name_col else ""
        if not sym and name:
            # last resort: try to derive symbol from name (rarely works perfectly)
            sym = re.sub(r"[^A-Z0-9]", "", name.upper())[:15]
        if not sym:
            continue

        fundamentals = {}
        for canonical, col in col_map.items():
            if canonical in ("symbol", "name"):
                continue
            val = row[col]
            if canonical in ("industry",):
                fundamentals[canonical] = str(val).strip() if val and not pd.isna(val) else None
            else:
                fundamentals[canonical] = _to_num(val)

        out["stocks"].append({
            "symbol": sym,
            "name": name,
            "fundamentals": fundamentals,
        })
    out["kept_count"] = len(out["stocks"])
    return out


def to_dataframe(parsed: dict) -> pd.DataFrame:
    """Flatten the parsed output to a single DataFrame for display."""
    rows = []
    for s in parsed.get("stocks", []):
        row = {"symbol": s["symbol"], "name": s.get("name", "")}
        row.update(s.get("fundamentals", {}))
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("symbol")
    return df


# The 17 conditions you specified — for documentation and an explainer in the UI.
DEFAULT_QUERY_SUGGESTION = """\
Paste this into Screener.in's Query Builder and click "Run This Query":

  Price to Earning > 0 AND
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
  OPM > OPM preceding year

When you have results, click "Export to Excel" → save as CSV → upload below.
"""
