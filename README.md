# NSE Dual-Horizon Screener

A professional-grade, explainable stock-screening and backtesting system for the
Indian market (NSE), built for a **mixed horizon**: active trading (days–weeks)
*and* positional holds (a few months).

It does not promise returns. It systematically tilts the odds using factors with
documented edge, kills untradeable names before scoring, explains every pick, and
— most importantly — lets you **backtest** before risking a rupee.

## Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │              DATA LAYER (data/)             │
                    │  yfinance (free)  →  swap for Zerodha/Upstox │
                    │  OHLCV + Nifty benchmark + (news provider)   │
                    └───────────────────────┬─────────────────────┘
                                            │
                    ┌───────────────────────▼─────────────────────┐
                    │           FACTOR LAYER (core/factors.py)     │
                    │  Tactical:  5d/21d mom, vol thrust, RSI,      │
                    │             ATR%, EMA20 dist, breakout gap    │
                    │  Structural: 63d/126d mom, ADX, EMA200,       │
                    │             rel-strength vs Nifty, drawdown   │
                    │  Liquidity:  20d turnover, volume             │
                    └───────────────────────┬─────────────────────┘
                                            │
                    ┌───────────────────────▼─────────────────────┐
                    │           NEWS LAYER (core/news.py)          │
                    │  Event flags · headline sentiment · buzz     │
                    │  (pluggable: NewsAPI/Trendlyne/RavenPack...)  │
                    └───────────────────────┬─────────────────────┘
                                            │
                    ┌───────────────────────▼─────────────────────┐
                    │         SCORING LAYER (core/scoring.py)      │
                    │  1. Hard filters (liquidity, regime)         │
                    │  2. Winsorize + cross-sectional z-score      │
                    │  3. Tactical & structural composites         │
                    │  4. Horizon-weighted FINAL score + reasons   │
                    └───────────────────────┬─────────────────────┘
                                            │
              ┌─────────────────────────────┼─────────────────────────────┐
              ▼                             ▼                             ▼
   ┌──────────────────┐        ┌──────────────────────┐      ┌────────────────────┐
   │  pipeline.py     │        │  core/backtest.py    │      │  app.py (Streamlit)│
   │  CLI ranked list │        │  walk-forward, costs │      │  full dashboard    │
   └──────────────────┘        └──────────────────────┘      └────────────────────┘
```

## Setup

```bash
pip install -r requirements.txt
```

## Run

**Dashboard (recommended):**
```bash
streamlit run app.py
```

**CLI screener:**
```bash
python pipeline.py --horizon blend --top 20 --min-turnover 2
python pipeline.py --horizon tactical --regime      # only above 200-EMA
```

## Wiring in your PAID data feed

You said you'll pay for data — that's the right call for the full NSE universe.
Two hooks to replace:

1. **Price/volume** → `data/data.py :: fetch_ohlcv()`
   Replace the yfinance call with Zerodha Kite / Upstox / TrueData. Return a
   DataFrame with columns `Open, High, Low, Close, Volume` indexed by date.
   Then expand `UNIVERSE` to the full NSE list (or load it from your broker).

2. **News** → `core/news.py :: fetch_headlines()`
   Return `list[Headline]` for a symbol. Plug in NewsAPI, Trendlyne, Tickertape,
   or RavenPack. The sentiment + event-flag logic already works on top of it.

Nothing else needs to change — the factor, scoring, and backtest layers are
data-source agnostic.

## The discipline that actually matters

- **Backtest every change.** A screener that looks great on history usually
  overfits. Use the Backtest tab; check it beats the Nifty *after costs*.
- **Respect costs & taxes.** STT, brokerage, slippage, and short-term capital
  gains tax eat short-horizon returns. The backtester models round-trip cost —
  tune `cost_bps` to your reality.
- **Position-size for risk.** Never let one name sink the book.
- **The watchlist is candidates, not commands.** Do your own final check.

## Sector-neutral ranking (core/sectors.py)

A naive screen buys whatever sector is hot — all PSU banks, all defence — which
is a concentrated sector bet in disguise. Sector-neutral mode z-scores each
factor *within* a stock's own sector, so you surface the best name per sector,
then `apply_sector_cap` limits how many names any one sector contributes.
Toggle it in the sidebar; set max names per sector. Replace `SECTOR_MAP` with
your provider's full classification when you wire in paid data.

## Position sizing & stops (core/risk.py)

Turns the watchlist into a real trade plan:
- Risk a **fixed fraction** of capital per trade (default 1%), never fixed shares.
- Stop = `N × ATR` below entry, so it sits outside that stock's normal noise.
- Shares are derived so loss-at-stop equals the risk budget → **every position
  contributes equal risk** to the book.
- Targets at an R-multiple (default 2:1). Portfolio-level **heat limit** stops
  adding once aggregate open risk hits a ceiling (default 6%).

> Note: each position is also capped at `max_position_pct` (default 20%) of
> capital. If you request more concurrent positions than 100% ÷ cap allows,
> total deployment can exceed 100% (i.e. would need leverage). Either run fewer
> concurrent names or lower the per-position cap. The **heat limit** is the real
> risk guardrail — keep it where you can stomach the drawdown.

## The discipline, restated

Stops are mechanical. If you don't honor them, the position-sizing math is
meaningless and the whole risk framework collapses. The system can rank and
size; only you can be disciplined.

## Positions & Exit Monitor (core/monitor.py + core/store.py)

The sell side. Log what you hold in the **📍 Positions** tab; the monitor
fetches live prices and flags each position:

- **EXIT** — stop hit, or the thesis broke (score collapsed / trend reversed).
- **TRIM** — target reached, or the name is weakening below its 20-EMA.
- **RAISE_STOP** — price advanced; ratchet the stop up (ATR trailing) to lock
  in gains without exiting early.
- **HOLD** — still within plan.

Positions persist to `portfolio.json` (survives restarts). Closing a trade
records realized P&L and builds a track record with win rate. The system never
places orders — it surfaces the decision; you execute in your broker.

## Roadmap (what's built vs. next)

**✅ Phase 1 — Close the loop (DONE).** Position monitor, persistence, exit
logic (stops, targets, trailing, score-decay, time-stop). The system is now
buy *and* sell.

**✅ Phase 2 — Validation & protection (DONE).**
- *Market regime filter* (core/regime.py): Nifty trend/drawdown/volatility/breadth
  → RISK_ON / CAUTION / RISK_OFF posture that throttles position count. Shown as
  a banner atop the Screener. Protection FROM THE MARKET.
- *Behavioral guardrails* (core/guardrails.py): blocks no-stop and oversized
  trades; warns on overtrading, revenge trades, averaging down, sector
  concentration, and risk-budget breaches; daily-loss circuit breaker.
  Protection FROM YOURSELF.
- *Walk-forward validation* (core/walkforward.py): rolling out-of-sample testing
  with an overfit flag and plain-English verdict. In the Backtest tab.
- *Survivorship-bias awareness* (core/universe_pit.py): point-in-time universe
  interface + loud warnings when running on current members only.

**Phase 3 — Convenience & rigor.**
- *Disk price cache*: stop re-fetching every run; faster and easier on your
  paid feed's rate limits.
- *Daily alert summary*: end-of-day digest of exits, targets, new triggers.
- *Entry triggers*: flag WHEN a top-ranked name is actually entry-ready
  (pullback-to-EMA, breakout confirmation, RSI reset) vs. extended.

**Phase 4 — Polish.**
- *Sector rotation view*: which sectors lead, to bias the watchlist.
- *Tax/transaction log*: STT, brokerage, STCG for true net P&L.

## Honest base rates (why the protection layer exists)

SEBI's studies are blunt: ~70% of intraday traders and ~91% of F&O traders in
India lose money, and most documented profits accrue to algorithmic players. The
regime filter, guardrails, and walk-forward validation exist because the
difference between the winners and losers is discipline and honest validation —
not better tips. The system is built to enforce the former and force the latter.

## Not investment advice

This is an engineering tool for informed decisions. Markets carry real risk of
loss. Validate everything independently.
