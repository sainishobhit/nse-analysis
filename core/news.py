"""
news.py — News & sentiment layer.

Short-horizon trading lives and dies on news flow, so this is a first-class
module, not an afterthought. It is provider-pluggable: wire in whichever feed
you pay for. Three tiers of signal, in order of value:

  1. EVENT FLAGS (highest value): results dates, corporate actions, block deals,
     bulk deals, surveillance flags (ASM/GSM), credit-rating changes, pledge
     changes. These are FACTS, not opinions — they move stocks hard.
  2. HEADLINE SENTIMENT: classify recent headlines per stock as +/0/-.
  3. ATTENTION / BUZZ: count of headlines in last 48h vs baseline (spikes
     often precede or accompany moves).

This file ships with a clean interface + a deterministic lexicon sentiment
fallback so the system runs with zero paid keys. Swap `fetch_headlines` for
your provider (e.g. NewsAPI, Tickertape, Trendlyne, RavenPack, Bloomberg).
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


# --------------------------------------------------------------------------
# Lightweight finance-tuned lexicon (fallback when no NLP model is wired in)
# --------------------------------------------------------------------------
POS = {
    "beats", "beat", "surge", "surges", "record", "profit", "growth", "upgrade",
    "upgraded", "wins", "won", "order", "orders", "expansion", "strong", "rally",
    "outperform", "buyback", "dividend", "bonus", "approval", "approved",
    "acquire", "acquisition", "partnership", "high", "jumps", "soars", "raises",
}
NEG = {
    "miss", "misses", "fall", "falls", "plunge", "plunges", "loss", "losses",
    "downgrade", "downgraded", "probe", "fraud", "raid", "default", "fine",
    "penalty", "weak", "cut", "cuts", "resign", "resigns", "lawsuit", "ban",
    "delay", "slump", "warning", "pledge", "stake sale", "block deal", "low",
}

# Event keywords → flags (facts that move price)
EVENT_PATTERNS = {
    "results": r"\b(q[1-4]|results|earnings|profit|revenue)\b",
    "rating": r"\b(upgrade|downgrade|rating|target price|tp\b)",
    "corp_action": r"\b(dividend|bonus|split|buyback|rights issue)\b",
    "block_deal": r"\b(block deal|bulk deal|stake (sale|buy)|promoter (selling|buying))\b",
    "regulatory": r"\b(sebi|probe|raid|fraud|gsm|asm|surveillance)\b",
    "order_win": r"\b(order win|bags order|contract|deal worth)\b",
}


@dataclass
class Headline:
    title: str
    ts: datetime
    source: str = "unknown"
    url: str = ""


@dataclass
class NewsSignal:
    symbol: str
    sentiment: float = 0.0          # -1..+1
    buzz: int = 0                   # headline count in window
    events: list = field(default_factory=list)
    top_headline: str = ""

    def to_dict(self):
        return {
            "news_sentiment": round(self.sentiment, 3),
            "news_buzz": self.buzz,
            "news_events": ",".join(self.events) if self.events else "",
            "news_top": self.top_headline,
        }


def _score_text(text: str) -> int:
    words = set(re.findall(r"[a-z]+", text.lower()))
    return len(words & POS) - len(words & NEG)


def _detect_events(text: str) -> list:
    t = text.lower()
    return [name for name, pat in EVENT_PATTERNS.items() if re.search(pat, t)]


# --------------------------------------------------------------------------
# PROVIDER HOOK — replace this body with your paid feed's call.
# Must return a list[Headline] for the given symbol.
# --------------------------------------------------------------------------
def fetch_headlines(symbol: str, lookback_hours: int = 48) -> list[Headline]:
    """
    STUB. Returns []. Wire in your provider here. Example shape:

        resp = newsapi.get(q=company_name(symbol), from=...)
        return [Headline(a["title"], parse(a["publishedAt"]), a["source"]) ...]
    """
    return []


def analyze(symbol: str, lookback_hours: int = 48,
            headlines: list[Headline] | None = None) -> NewsSignal:
    """Compute a NewsSignal for one symbol from its recent headlines."""
    hs = headlines if headlines is not None else fetch_headlines(symbol, lookback_hours)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    hs = [h for h in hs if h.ts >= cutoff]

    if not hs:
        return NewsSignal(symbol=symbol)

    scores = [_score_text(h.title) for h in hs]
    raw = sum(scores)
    norm = max(-1.0, min(1.0, raw / (len(hs) * 2)))  # squash to -1..1

    events = sorted({e for h in hs for e in _detect_events(h.title)})
    top = max(hs, key=lambda h: abs(_score_text(h.title))).title

    return NewsSignal(symbol=symbol, sentiment=norm, buzz=len(hs),
                      events=events, top_headline=top)


# Demo / self-test
if __name__ == "__main__":
    demo = [
        Headline("Company X Q3 profit beats estimates, revenue at record high", datetime.now(timezone.utc)),
        Headline("Brokerage upgrades Company X, raises target price", datetime.now(timezone.utc)),
        Headline("Company X bags large order from government", datetime.now(timezone.utc)),
    ]
    sig = analyze("TESTCO", headlines=demo)
    print(sig.to_dict())
