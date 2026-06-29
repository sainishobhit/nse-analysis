"""
news_rss.py — Real news ingestion from free Indian financial RSS feeds.

No API key required. Pulls headlines from Moneycontrol, Economic Times, and
Business Standard, then filters per-symbol by matching company name / ticker
in the title. Caches results so we're not hammering RSS endpoints.

Limitations to be honest about:
  - RSS feeds carry mostly market news + the biggest stories, not deep coverage
    of every stock. Small/mid caps may have zero matches.
  - Title matching is fuzzy — we match company name AND ticker variants. A few
    false positives are possible but tolerable; we surface URLs so the AI (and
    you) can verify.
  - "Last 30 days" is best-effort — RSS feeds typically only carry the latest
    20-50 items, so older news isn't available without a paid archive.
"""

from __future__ import annotations
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Iterable

try:
    import feedparser
except ImportError:
    feedparser = None


# Curated RSS feeds — broad coverage of Indian markets.
RSS_FEEDS = [
    # Moneycontrol
    "https://www.moneycontrol.com/rss/marketreports.xml",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://www.moneycontrol.com/rss/results.xml",
    "https://www.moneycontrol.com/rss/buzzingstocks.xml",
    # Economic Times
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "https://economictimes.indiatimes.com/rssfeedsdefault.cms",
    # Business Standard
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.business-standard.com/rss/companies-101.rss",
    # LiveMint
    "https://www.livemint.com/rss/markets",
]


# Cache fetched feeds for 15 minutes so we don't re-hit them on every click.
_FEED_CACHE: dict = {}  # url -> (timestamp, parsed_entries)
_FEED_TTL = 900   # 15 minutes


# Known symbol → display name mapping for better headline matching.
# Expand this as needed (or load from a CSV).
SYMBOL_TO_NAMES = {
    "RELIANCE": ["reliance industries", "reliance"],
    "TCS": ["tcs", "tata consultancy"],
    "INFY": ["infosys"],
    "HDFCBANK": ["hdfc bank"],
    "ICICIBANK": ["icici bank"],
    "SBIN": ["state bank of india", "sbi"],
    "BHARTIARTL": ["bharti airtel", "airtel"],
    "ITC": ["itc"],
    "LT": ["larsen", "l&t"],
    "WIPRO": ["wipro"],
    "ADANIENT": ["adani enterprises"],
    "ADANIPORTS": ["adani ports"],
    "MARUTI": ["maruti suzuki", "maruti"],
    "TATAMOTORS": ["tata motors"],
    "TATASTEEL": ["tata steel"],
    "EDELWEISS": ["edelweiss financial", "edelweiss"],
    "GRANULES": ["granules india", "granules"],
    "TALBROENG": ["talbros engineering", "talbros"],
    "ARROWGREEN": ["arrow greentech"],
    "WELSPUNENT": ["welspun enterprises", "welspun"],
    "DCMSRIND": ["dcm shriram industries", "dcm shriram"],
    "ZOMATO": ["zomato", "eternal"],
    "PAYTM": ["paytm", "one 97"],
    "IRCTC": ["irctc"],
    "NTPC": ["ntpc"],
    "ONGC": ["ongc", "oil and natural gas"],
    "SUNPHARMA": ["sun pharmaceutical", "sun pharma"],
    "BAJFINANCE": ["bajaj finance"],
    "BAJFINSV": ["bajaj finserv"],
    "EICHERMOT": ["eicher motors"],
    "HCLTECH": ["hcl technologies", "hcl tech"],
    "TECHM": ["tech mahindra"],
    "HINDUNILVR": ["hindustan unilever", "hul"],
    "ASIANPAINT": ["asian paints"],
    "NESTLEIND": ["nestle india"],
    "TITAN": ["titan company", "titan"],
    "ULTRACEMCO": ["ultratech cement"],
    "POWERGRID": ["power grid"],
    "AXISBANK": ["axis bank"],
    "KOTAKBANK": ["kotak mahindra bank", "kotak bank"],
    "BPCL": ["bharat petroleum", "bpcl"],
    "IOCL": ["indian oil"],
    "COALINDIA": ["coal india"],
}


def names_for(symbol: str) -> list[str]:
    """Return a list of name variants to search for in headlines for this symbol."""
    sym = symbol.upper().replace(".NS", "").strip()
    names = SYMBOL_TO_NAMES.get(sym, [])
    # Always include the ticker itself as a fallback
    out = list(names) + [sym]
    # Add a "spaced" version (e.g., RELIANCEIND -> reliance ind)
    if not names and len(sym) > 5:
        out.append(sym.lower())
    return out


def _fetch_one_feed(url: str) -> list[dict]:
    """Fetch and parse one feed, with simple TTL cache."""
    now = time.time()
    if url in _FEED_CACHE:
        ts, entries = _FEED_CACHE[url]
        if now - ts < _FEED_TTL:
            return entries
    if feedparser is None:
        return []
    try:
        parsed = feedparser.parse(url)
        entries = []
        for e in parsed.entries[:50]:
            title = (getattr(e, "title", "") or "").strip()
            link = (getattr(e, "link", "") or "").strip()
            summary = (getattr(e, "summary", "") or "").strip()
            # parse date — RSS uses several fields
            pub = (getattr(e, "published_parsed", None)
                   or getattr(e, "updated_parsed", None))
            if pub:
                try:
                    dt = datetime(*pub[:6], tzinfo=timezone.utc)
                except Exception:
                    dt = None
            else:
                dt = None
            entries.append({
                "title": title, "link": link,
                "summary": summary[:300],
                "published": dt.isoformat() if dt else None,
                "source": _domain(url),
            })
        _FEED_CACHE[url] = (now, entries)
        return entries
    except Exception:
        return []


def _domain(url: str) -> str:
    m = re.search(r"://(?:www\.)?([^/]+)/", url)
    return m.group(1) if m else url


def _matches(text: str, names: list[str]) -> bool:
    """Case-insensitive: does the text mention any of the name variants?"""
    if not text:
        return False
    low = text.lower()
    for n in names:
        if not n:
            continue
        n = n.lower().strip()
        if len(n) <= 3:
            # very short — require word boundary to avoid false positives
            if re.search(rf"\b{re.escape(n)}\b", low):
                return True
        else:
            if n in low:
                return True
    return False


def fetch_headlines(symbol: str, days_back: int = 30,
                    max_headlines: int = 8) -> list[dict]:
    """
    Fetch headlines mentioning the symbol from the last `days_back` days.
    Returns up to `max_headlines` items, newest first.
    Each item: {title, link, published, source, summary}
    """
    if feedparser is None:
        return []
    names = names_for(symbol)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    matches = []
    seen_titles = set()
    for url in RSS_FEEDS:
        for entry in _fetch_one_feed(url):
            title = entry.get("title", "")
            if not title or title in seen_titles:
                continue
            # match against title + summary
            text = title + " " + entry.get("summary", "")
            if not _matches(text, names):
                continue
            # date filter
            pub = entry.get("published")
            if pub:
                try:
                    dt = datetime.fromisoformat(pub)
                    if dt < cutoff:
                        continue
                except Exception:
                    pass
            matches.append(entry)
            seen_titles.add(title)
    # sort by published desc (None last)
    matches.sort(key=lambda e: e.get("published") or "", reverse=True)
    return matches[:max_headlines]


def summarize_for_ai(headlines: list[dict]) -> dict:
    """Compact representation for the AI payload."""
    if not headlines:
        return {"count": 0, "items": [], "note": "No matching headlines found in RSS feeds in the last 30 days."}
    return {
        "count": len(headlines),
        "window_days": 30,
        "items": [
            {
                "title": h["title"],
                "source": h["source"],
                "date": (h.get("published") or "")[:10],
                "url": h.get("link", ""),
            }
            for h in headlines
        ],
    }
