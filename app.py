"""
app.py — Streamlit dashboard for the dual-horizon NSE trading system.

Run locally:
    pip install streamlit yfinance pandas numpy
    streamlit run app.py

Tabs:
  1. Screener   — ranked watchlist with scores, reasons, news, filters
  2. Stock      — drill into one name: price, indicators, factor breakdown
  3. Backtest   — validate the strategy before trusting it
  4. About      — methodology + honest caveats
"""

from __future__ import annotations
import sys, os
import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))
from core import factors as F
from core import scoring as S
from core import sectors as SEC
from core import risk as R
from core import news as N
from core import backtest as BT
from core import store as ST
from core import monitor as MON
from core import regime as RG
from core import guardrails as G
from core import walkforward as WF
from core import glossary as GL
from core import horizons as HZ
from core import advisor as ADV
from core import broker as BRK
from data import data as D

st.set_page_config(page_title="NSE Dual-Horizon Screener", layout="wide",
                   initial_sidebar_state="expanded")

# ---- light styling ----
st.markdown("""
<style>
  .stApp { background: #0d1117; }
  h1, h2, h3 { color: #e6edf3; font-family: 'Georgia', serif; }
  .metric-good { color: #3fb950; } .metric-bad { color: #f85149; }
  .reason { color: #8b949e; font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=1800, show_spinner=False)
def load_universe(period="1y"):
    bench = D.fetch_benchmark(period=period)
    uni = D.fetch_universe(period=period)
    return uni, bench


@st.cache_data(ttl=1800, show_spinner=False)
def analyze_single(symbol, period, horizon, use_news, _universe_raw=None):
    """
    Fetch & analyze ANY symbol on demand. Scores it relative to the current
    universe so its z-scores/percentiles are meaningful, not standalone.
    Returns (ohlcv_df, factor_row_series) or (None, None) if unavailable.
    """
    symbol = symbol.strip().upper().replace(".NS", "")
    if not symbol:
        return None, None
    df = D.fetch_ohlcv(symbol, period=period)
    if df is None or len(df) < 30:
        return None, None

    uni, bench = load_universe(period)
    feats = F.compute_all(df, bench_close=bench)
    if use_news:
        feats.update(N.analyze(symbol).to_dict())

    # Build a universe table that INCLUDES this symbol, so z-scores are
    # computed against real peers (the symbol may or may not already be in uni).
    rows = {}
    for s, d in uni.items():
        f = F.compute_all(d, bench_close=bench)
        if f:
            rows[s] = f
    rows[symbol] = feats
    raw = pd.DataFrame.from_dict(rows, orient="index")
    raw = SEC.attach_sectors(raw)
    scored = S.score_universe(raw, horizon=horizon, sector_neutral=False)
    if symbol not in scored.index:
        return df, None
    return df, scored.loc[symbol]


@st.cache_data(ttl=1800, show_spinner=False)
def build_scores(period, horizon, min_turnover, use_news, sector_neutral,
                 require_above_ema200=False):
    uni, bench = load_universe(period)
    rows = {}
    for sym, df in uni.items():
        feats = F.compute_all(df, bench_close=bench)
        if not feats:
            continue
        if use_news:
            feats.update(N.analyze(sym).to_dict())
        rows[sym] = feats
    raw = pd.DataFrame.from_dict(rows, orient="index")
    if raw.empty:
        return raw, uni, bench
    raw = SEC.attach_sectors(raw)
    filt = S.apply_hard_filters(raw, min_turnover_cr=min_turnover,
                                require_above_ema200=require_above_ema200)
    if filt.empty:
        return filt, uni, bench
    scored = S.score_universe(filt, horizon=horizon, sector_neutral=sector_neutral)
    scored["reason"] = scored.apply(S.build_reason, axis=1)
    scored["turnover_cr"] = (scored["avg_turnover_20d"] / 1e7).round(2)
    return scored, uni, bench


# ===================== SIDEBAR =====================
st.sidebar.title("⚙️ Controls")
horizon = st.sidebar.radio("Horizon", ["blend", "tactical", "structural"],
    help="tactical = days-weeks · structural = months · blend = both")
period = st.sidebar.selectbox("History window", ["6mo", "1y", "2y"], index=1,
    help="How far back to pull price data for the analysis.")
min_turnover = st.sidebar.slider("Min daily turnover (₹ cr)", 0.5, 20.0, 2.0, 0.5,
    help="Skip stocks that trade less than this much money per day — you want "
         "names you can actually buy and sell easily (liquidity).")
top_n = st.sidebar.slider("Show top N", 5, 50, 20, 5,
    help="How many of the highest-ranked stocks to display.")
sector_neutral = st.sidebar.checkbox("Sector-neutral ranking", value=True,
    help="Compare each stock to others in its OWN industry, and limit how many "
         "from one industry make the list — so you don't accidentally bet "
         "everything on one sector.")
max_per_sector = st.sidebar.slider("Max names per sector", 1, 5, 2,
    disabled=not sector_neutral,
    help="The most stocks allowed from any single industry.")
use_news = st.sidebar.checkbox("Include news/sentiment layer", value=False,
    help="Factor in recent headlines. Needs a news provider wired in; off by default.")

st.sidebar.markdown("---")
st.sidebar.subheader("💰 Risk settings")
capital = st.sidebar.number_input("Capital (₹)", 50000, 100000000, 500000, 50000,
    help="Total money you're trading with. Used to size positions.")
risk_pct = st.sidebar.slider("Risk per trade (%)", 0.25, 3.0, 1.0, 0.25,
    help=GL.tip("Risk per trade"))
atr_mult = st.sidebar.slider("Stop = N × ATR", 1.0, 4.0, 2.0, 0.5,
    help="How far below your entry to place the stop, measured in the stock's "
         "average daily swing (ATR). Bigger = more breathing room, bigger loss if hit.")
reward_mult = st.sidebar.slider("Reward : Risk", 1.0, 4.0, 2.0, 0.5,
    help=GL.tip("Reward:risk"))

tab1, tab7, tab2, tab3, tab6, tab8, tab4, tab5 = st.tabs(
    ["📊 Screener", "🎯 Horizon View", "🔍 Stock", "💰 Trade Plan",
     "📍 Positions", "📁 My Portfolio", "🧪 Backtest", "ℹ️ About"])

# ===================== TAB 1: SCREENER =====================
with tab1:
    st.title("Dual-Horizon NSE Screener")
    st.caption("Ranked watchlist · decision-support, not advice")
    with st.expander("📖 New here? Plain-English glossary for this tab"):
        st.markdown(GL.render_glossary_md([
            "Final score", "Tactical score", "Structural score", "Z-score",
            "Rank", "Reason", "Sector", "Regime", "RISK-ON", "CAUTION", "RISK-OFF",
            "Drawdown", "Breadth"]))
    with st.spinner("Fetching & scoring universe..."):
        scored, uni, bench = build_scores(period, horizon, min_turnover,
                                          use_news, sector_neutral)

    if scored.empty:
        st.warning("No data fetched. If running in a restricted network, "
                   "yfinance/Yahoo may be blocked. Wire in your paid feed in data/data.py.")
    else:
        # ---- MARKET REGIME BANNER (protection from the market) ----
        regime = RG.assess_regime(bench, universe_closes={s: d["Close"] for s, d in uni.items()})
        posture = regime["posture"]
        banner = {
            RG.RISK_ON: ("🟢", "RISK-ON", "Market healthy — full deployment OK."),
            RG.CAUTION: ("🟡", "CAUTION", "Mixed market — fewer positions, tighter entries."),
            RG.RISK_OFF: ("🔴", "RISK-OFF", "Market weak — avoid new longs, protect capital."),
        }[posture]
        if posture == RG.RISK_ON:
            st.success(f"{banner[0]} **{banner[1]}** — {banner[2]}  \n_{regime['reason']}_")
        elif posture == RG.CAUTION:
            st.warning(f"{banner[0]} **{banner[1]}** — {banner[2]}  \n_{regime['reason']}_")
        else:
            st.error(f"{banner[0]} **{banner[1]}** — {banner[2]}  \n_{regime['reason']}_")

        regime_top_n = RG.throttle_positions(top_n, regime)
        if regime_top_n < top_n:
            st.caption(f"⚠️ Regime throttle: showing your top {top_n}, but the market "
                       f"posture suggests holding **{regime_top_n} or fewer** new positions.")

        if sector_neutral:
            view_full = S.apply_sector_cap(scored, top_n=top_n,
                                           max_per_sector=max_per_sector)
        else:
            view_full = scored.head(top_n)

        c1, c2, c3 = st.columns(3)
        c1.metric("Universe scored", len(scored),
                  help="How many stocks passed the liquidity filter and got scored.")
        c2.metric("Sectors represented", view_full["sector"].nunique()
                  if "sector" in view_full else "—",
                  help=GL.tip("Sector"))
        c3.metric("Horizon", horizon,
                  help="tactical = days-weeks · structural = months · blend = both")

        show_cols = ["rank", "final_score", "tactical_score",
                     "structural_score", "sector", "turnover_cr", "reason"]
        if use_news and "news_sentiment" in scored:
            show_cols.insert(6, "news_sentiment")
        view = view_full[[c for c in show_cols if c in view_full.columns]].copy()
        view.index.name = "Symbol"
        try:
            styled = view.style.background_gradient(subset=["final_score"], cmap="RdYlGn")
        except ImportError:
            styled = view
        st.dataframe(styled, use_container_width=True, height=600)
        st.caption("**Columns:** rank = today's pecking order (#1 best) · "
                   "final_score = overall pick quality (ranking number, not a price) · "
                   "tactical = hot now · structural = strong for months · "
                   "turnover_cr = ₹ crore traded daily (liquidity) · "
                   "reason = why it ranks here. Hover the (?) icons anywhere for more.")
        st.download_button("⬇️ Download watchlist (CSV)",
                           view.to_csv().encode(), "watchlist.csv")

# ===================== TAB 7: HORIZON VIEW =====================
with tab7:
    st.title("Horizon View")
    st.caption("Pick how long you plan to hold — the analysis re-tunes itself for "
               "that timeframe (what matters, stops, targets, and tax).")
    with st.expander("📖 Plain-English glossary for this tab"):
        st.markdown(GL.render_glossary_md([
            "Short-term", "Medium-term", "Long-term", "Rebalance",
            "STCG", "LTCG", "Stop", "Target"]))

    # horizon picker
    choice = st.radio(
        "Your holding horizon",
        options=HZ.ORDER,
        format_func=lambda k: f"{HZ.PROFILES[k]['label']} ({HZ.PROFILES[k]['window']})",
        horizontal=True,
    )
    prof = HZ.get(choice)

    # explain the profile
    pcol = st.columns(4)
    pcol[0].metric("Timeframe", prof["window"])
    pcol[1].metric("Scoring style", prof["scoring_horizon"],
                   help="tactical = momentum-led · structural = trend-led · blend = both")
    pcol[2].metric("Typical hold", f"~{prof['hold_days']} trading days")
    pcol[3].metric("Stop width", f"{prof['atr_stop_mult']}× ATR",
                   help="Wider for longer horizons so normal swings don't shake you out.")

    st.markdown(f"**✅ What good looks like for {prof['label'].lower()}:** "
                f"{prof['what_good_looks_like']}")
    st.markdown(f"**⚠️ Watch out:** {prof['watch_out']}")
    st.info(f"🧾 **Tax:** {prof['tax_note']}")
    st.caption(f"Suggested rebalance cadence: **{prof['rebalance']}**.")

    st.markdown("---")
    st.subheader(f"Top picks for a {prof['label'].lower()} horizon")

    with st.spinner(f"Scoring the universe for a {prof['label'].lower()} horizon..."):
        hz_scored, hz_uni, hz_bench = build_scores(
            period, prof["scoring_horizon"], prof["min_turnover_cr"],
            use_news, sector_neutral,
            require_above_ema200=prof["require_above_ema200"])

    if hz_scored.empty:
        st.warning("No stocks passed this horizon's filters (or no data fetched). "
                   "Longer horizons require price above the 200-day trend, so fewer "
                   "names qualify in a weak market — that's by design.")
    else:
        if sector_neutral:
            hz_view = S.apply_sector_cap(hz_scored, top_n=top_n,
                                         max_per_sector=max_per_sector)
        else:
            hz_view = hz_scored.head(top_n)

        cols = ["rank", "final_score", "tactical_score", "structural_score",
                "sector", "turnover_cr", "reason"]
        hz_tbl = hz_view[[c for c in cols if c in hz_view.columns]].copy()
        hz_tbl.index.name = "Symbol"
        try:
            hz_styled = hz_tbl.style.background_gradient(subset=["final_score"], cmap="RdYlGn")
        except ImportError:
            hz_styled = hz_tbl
        st.dataframe(hz_styled, use_container_width=True, height=440)
        st.caption(f"Filtered & ranked for {prof['label'].lower()} holding. "
                   f"{'Only stocks above their 200-day trend are shown.' if prof['require_above_ema200'] else 'Momentum-led: includes names that are hot now.'}")

        # quick trade-plan preview for the top name at THIS horizon's stop/target style
        st.markdown("##### Example trade plan (top pick, tuned to this horizon)")
        top_sym = hz_view.index[0]
        top_df = hz_uni.get(top_sym)
        if top_df is not None:
            hz_plan = R.plan_trade(top_df, capital=capital, risk_pct=risk_pct,
                                   atr_mult_stop=prof["atr_stop_mult"],
                                   reward_multiple=prof["reward_mult"])
            if "error" not in hz_plan:
                tc = st.columns(5)
                tc[0].metric("Stock", top_sym)
                tc[1].metric("Entry", f"₹{hz_plan['entry']:,.2f}", help=GL.tip("Entry"))
                tc[2].metric("Stop", f"₹{hz_plan['stop']:,.2f}",
                             help=f"{prof['atr_stop_mult']}× ATR — {GL.tip('Stop')}")
                tc[3].metric("Target", f"₹{hz_plan['target']:,.2f}", help=GL.tip("Target"))
                tc[4].metric("Shares", f"{hz_plan['shares']:,}",
                             help=GL.tip("Position sizing"))
                st.caption(f"Stop and target use this horizon's wider/tighter style "
                           f"({prof['atr_stop_mult']}× ATR stop, "
                           f"{prof['reward_mult']}:1 reward:risk). Mechanical levels, not advice.")
        st.download_button("⬇️ Download these picks (CSV)",
                           hz_tbl.to_csv().encode(),
                           f"horizon_{choice}_picks.csv")


    st.title("Stock Search & Analysis")
    st.caption("Type any NSE symbol (e.g. RELIANCE, IRCTC, ZOMATO) — analyzed live, "
               "even if it's not in the default universe.")

    sc1, sc2 = st.columns([3, 1])
    typed = sc1.text_input("NSE symbol", value="", placeholder="e.g. TATAPOWER",
                           label_visibility="collapsed").strip().upper()
    universe_pick = None
    if scored is not None and not scored.empty:
        universe_pick = sc2.selectbox("…or pick from watchlist",
                                      [""] + scored.index.tolist(),
                                      label_visibility="collapsed")

    sym = typed or universe_pick
    if not sym:
        st.info("Enter a symbol above to analyze it.")
    else:
        with st.spinner(f"Fetching & analyzing {sym}..."):
            df, row = analyze_single(sym, period, horizon, use_news)

        if df is None:
            st.error(f"Couldn't fetch data for '{sym}'. Check the symbol spelling "
                     f"(use the NSE ticker without .NS), or it may be illiquid/"
                     f"delisted. If your network blocks Yahoo, wire in your paid feed.")
        else:
            close = df["Close"]
            ema20 = close.ewm(span=20, adjust=False).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()
            ema200 = close.ewm(span=200, adjust=False).mean() if len(close) >= 200 else None
            chart_cols = {"Close": close, "EMA20": ema20, "EMA50": ema50}
            if ema200 is not None:
                chart_cols["EMA200"] = ema200
            st.line_chart(pd.DataFrame(chart_cols), height=340)

            ltp = float(close.iloc[-1])
            chg = (close.iloc[-1] / close.iloc[-2] - 1) * 100 if len(close) > 1 else 0
            sec = SEC.sector_of(sym)

            top = st.columns(4)
            top[0].metric("Last price", f"₹{ltp:,.2f}", f"{chg:+.2f}%",
                          help="Most recent price and today's % change.")
            top[1].metric("Sector", sec, help=GL.tip("Sector"))
            if row is not None:
                top[2].metric("Final score", f"{row['final_score']:.2f}",
                              help=GL.tip("Final score"))
                top[3].metric("Rank in universe", f"#{int(row['rank'])}",
                              help=GL.tip("Rank"))

            if row is not None:
                cc = st.columns(4)
                cc[0].metric("Tactical", f"{row['tactical_score']:.2f}",
                             help=GL.tip("Tactical score"))
                cc[1].metric("Structural", f"{row['structural_score']:.2f}",
                             help=GL.tip("Structural score"))
                cc[2].metric("RSI(14)", f"{row.get('rsi', float('nan')):.0f}",
                             help=GL.tip("RSI"))
                cc[3].metric("ATR %", f"{row.get('atr_pct', float('nan'))*100:.1f}%",
                             help=GL.tip("ATR %"))
                st.markdown(f"**Read:** {S.build_reason(row)}")

                if use_news and row.get("news_top"):
                    st.markdown(f"📰 *{row['news_top']}*")

                zcols = [c for c in row.index if c.startswith("z_")]
                if zcols:
                    zrow = row[zcols].dropna().sort_values()
                    zrow.index = [c[2:] for c in zrow.index]  # strip "z_"
                    st.bar_chart(zrow, height=340)
                    st.caption("Factor contributions (z-scores vs universe, "
                               "direction-adjusted). Positive = favorable.")
            else:
                st.warning("Fetched price data, but not enough history to score "
                           "all factors. Chart shown above.")

            # quick trade plan for this one name
            st.markdown("##### Quick trade plan")
            plan = R.plan_trade(df, capital=capital, risk_pct=risk_pct,
                                atr_mult_stop=atr_mult, reward_multiple=reward_mult)
            if "error" not in plan:
                pc = st.columns(4)
                pc[0].metric("Entry", f"₹{plan['entry']:,.2f}", help=GL.tip("Entry"))
                pc[1].metric("Stop", f"₹{plan['stop']:,.2f}", help=GL.tip("Stop"))
                pc[2].metric("Target", f"₹{plan['target']:,.2f}", help=GL.tip("Target"))
                pc[3].metric("Shares", f"{plan['shares']:,}",
                             help=GL.tip("Position sizing"))
                st.caption(f"Risking ₹{plan['risk_rupees']:,.0f} "
                           f"({plan['risk_pct_actual']}% of capital) · "
                           f"deploys ₹{plan['capital_deployed']:,.0f} "
                           f"({plan['capital_pct']}%) · {reward_mult}:1 reward:risk. "
                           f"Mechanical levels, not advice.")
            else:
                st.caption(f"Trade plan unavailable: {plan['error']}")

# ===================== TAB 3: TRADE PLAN =====================
with tab3:
    st.title("Trade Plan")
    st.caption("ATR-based position sizing · equal risk per name · portfolio heat limit")
    with st.expander("📖 Plain-English glossary for this tab"):
        st.markdown(GL.render_glossary_md([
            "Entry", "Stop", "Target", "ATR", "Position sizing", "Risk per trade",
            "Reward:risk", "Portfolio heat", "Capital deployed"]))
    if scored is None or scored.empty:
        st.info("Run the Screener tab first.")
    else:
        if sector_neutral:
            picks_df = S.apply_sector_cap(scored, top_n=top_n,
                                          max_per_sector=max_per_sector)
        else:
            picks_df = scored.head(top_n)

        max_heat = st.slider("Max total portfolio risk (%)", 2.0, 15.0, 6.0, 0.5,
            help=GL.tip("Portfolio heat"))
        picks = picks_df.index.tolist()
        plan = R.plan_portfolio(
            picks, uni, capital=capital, risk_pct=risk_pct,
            atr_mult_stop=atr_mult, reward_multiple=reward_mult,
            max_total_risk_pct=max_heat,
        )
        if plan.empty:
            st.warning("No tradeable plan — raise capital, risk %, or loosen filters.")
        else:
            pm = st.columns(4)
            pm[0].metric("Positions", plan.attrs["positions"],
                         help="How many trades this plan would open.")
            pm[1].metric("Deployed", f"₹{plan.attrs['total_deployed']:,.0f}",
                         help=GL.tip("Capital deployed"))
            pm[2].metric("Deployed %", f"{plan.attrs['total_deployed_pct']}%",
                         help="What % of your capital is put to work.")
            pm[3].metric("Total open risk", f"{plan.attrs['total_risk_pct']}%",
                         help=GL.tip("Portfolio heat"))
            disp = plan.copy()
            disp["entry"] = disp["entry"].map(lambda x: f"₹{x:,.2f}")
            disp["stop"] = disp["stop"].map(lambda x: f"₹{x:,.2f}")
            disp["target"] = disp["target"].map(lambda x: f"₹{x:,.2f}")
            disp["capital_deployed"] = disp["capital_deployed"].map(lambda x: f"₹{x:,.0f}")
            disp["risk_rupees"] = disp["risk_rupees"].map(lambda x: f"₹{x:,.0f}")
            disp["reward_rupees"] = disp["reward_rupees"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(disp, use_container_width=True, height=460)
            st.download_button("⬇️ Download trade plan (CSV)",
                               plan.to_csv().encode(), "trade_plan.csv")
            st.caption("Stops/targets are mechanical, not advice. Honor them or "
                       "the sizing math is meaningless.")

# ===================== TAB 6: POSITIONS / EXIT MONITOR =====================
with tab6:
    st.title("Positions & Exit Monitor")
    st.caption("Log what you hold → the system tells you HOLD / TRIM / EXIT. "
               "Levels are mechanical; you place orders in your broker.")
    with st.expander("📖 Plain-English glossary for this tab"):
        st.markdown(GL.render_glossary_md([
            "HOLD", "TRIM", "EXIT", "RAISE_STOP", "Stop", "Target",
            "Trailing stop", "Open P&L", "Realized P&L"]))

    portfolio = ST.load()
    open_positions = portfolio.get("positions", [])

    # --- Add a position ---
    with st.expander("➕ Add a position you hold", expanded=not open_positions):
        ac = st.columns(5)
        a_sym = ac[0].text_input("Symbol").strip().upper()
        a_entry = ac[1].number_input("Entry ₹", min_value=0.0, value=0.0, step=1.0)
        a_shares = ac[2].number_input("Shares", min_value=0, value=0, step=1)
        a_stop = ac[3].number_input("Stop ₹", min_value=0.0, value=0.0, step=1.0)
        a_target = ac[4].number_input("Target ₹ (optional)", min_value=0.0, value=0.0, step=1.0)

        # --- Behavioral guardrails: check BEFORE adding (protection from yourself) ---
        gb1, gb2 = st.columns(2)
        if gb1.button("🛡️ Check trade against guardrails"):
            intended = {"symbol": a_sym, "entry": a_entry, "shares": int(a_shares),
                        "stop": a_stop, "sector": SEC.sector_of(a_sym)}
            findings = G.check_new_trade(
                intended, capital, open_positions,
                portfolio.get("closed", []), risk_pct_intended=risk_pct,
                max_positions=max(1, top_n))
            blocks = [f for f in findings if f["level"] == G.BLOCK]
            warns = [f for f in findings if f["level"] == G.WARN]
            if blocks:
                for f in blocks:
                    st.error(f"🚫 **{f['rule']}** — {f['msg']}")
            if warns:
                for f in warns:
                    st.warning(f"⚠️ **{f['rule']}** — {f['msg']}")
            if not blocks and not warns:
                st.success("✅ No guardrail flags. This trade fits your risk framework.")
            # also averaging-down check
            for f in G.check_add_to_position(a_sym, a_entry, open_positions):
                st.warning(f"⚠️ **{f['rule']}** — {f['msg']}")

        if gb2.button("Add position"):
            intended = {"symbol": a_sym, "entry": a_entry, "shares": int(a_shares),
                        "stop": a_stop, "sector": SEC.sector_of(a_sym)}
            findings = G.check_new_trade(
                intended, capital, open_positions,
                portfolio.get("closed", []), risk_pct_intended=risk_pct,
                max_positions=max(1, top_n))
            hard_blocks = [f for f in findings if f["level"] == G.BLOCK]
            if a_sym and a_entry > 0 and a_shares > 0 and a_stop > 0:
                if hard_blocks:
                    for f in hard_blocks:
                        st.error(f"🚫 BLOCKED: **{f['rule']}** — {f['msg']}")
                    st.caption("Fix the blocking issue, or override in your broker "
                               "if you truly disagree — but the system won't log a "
                               "trade that breaks a hard risk rule.")
                else:
                    ST.add_position(a_sym, a_entry, int(a_shares), a_stop,
                                    a_target if a_target > 0 else None)
                    st.success(f"Added {a_sym}. Refresh / rerun to see it evaluated.")
                    st.rerun()
            else:
                st.warning("Fill symbol, entry, shares, and stop at minimum.")

    # daily loss circuit breaker (protection from yourself)
    breaker = G.daily_loss_circuit_breaker(portfolio.get("closed", []), capital)
    if breaker:
        st.error(f"🛑 **{breaker['rule']}** — {breaker['msg']}")

    if not open_positions:
        st.info("No open positions logged yet. Add one above to start monitoring.")
    else:
        # --- Evaluate all positions ---
        ec = st.columns(3)
        trail_mult = ec[0].slider("Trailing stop × ATR", 1.0, 5.0, 3.0, 0.5)
        exit_thresh = ec[1].slider("Score EXIT below", -2.0, 0.0, -0.5, 0.1)
        max_days = ec[2].number_input("Time stop (days, 0=off)", 0, 200, 0)

        # fetch fresh prices for held symbols + reuse universe scores if present
        held_syms = [p["symbol"] for p in open_positions]
        with st.spinner("Fetching live prices for your holdings..."):
            price_data = {}
            for s in held_syms:
                d = D.fetch_ohlcv(s, period=period)
                if d is not None:
                    price_data[s] = d

        verdicts = MON.evaluate_all(
            open_positions, price_data,
            scored=scored if (scored is not None and not scored.empty) else None,
            atr_trail_mult=trail_mult,
            score_exit_threshold=exit_thresh,
            max_days=int(max_days) if max_days > 0 else None,
        )

        if verdicts.empty:
            st.warning("Couldn't fetch prices for your holdings (network/feed). "
                       "Try again or wire in your paid feed.")
        else:
            # portfolio P&L summary (defensive: tolerate missing columns)
            total_pnl = verdicts["pnl_abs"].sum() if "pnl_abs" in verdicts else 0
            action_col = verdicts["action"] if "action" in verdicts else pd.Series([], dtype=str)
            exits = (action_col == MON.EXIT).sum()
            trims = (action_col == MON.TRIM).sum()
            raises = (action_col == MON.RAISE_STOP).sum()
            no_data = (verdicts["price"].isna().sum()
                       if "price" in verdicts else 0)
            sm = st.columns(4)
            sm[0].metric("Open P&L", f"₹{total_pnl:,.0f}", help=GL.tip("Open P&L"))
            sm[1].metric("🔴 EXIT signals", int(exits), help=GL.tip("EXIT"))
            sm[2].metric("🟡 TRIM signals", int(trims), help=GL.tip("TRIM"))
            sm[3].metric("🟢 Stop raises", int(raises), help=GL.tip("RAISE_STOP"))
            if no_data:
                st.caption(f"⚠️ {int(no_data)} position(s) couldn't be priced "
                           f"(network/feed) and show as HOLD with no P&L. "
                           f"Their numbers aren't included above.")

            # color-coded action display
            def color_action(val):
                colors = {MON.EXIT: "#f85149", MON.TRIM: "#d29922",
                          MON.RAISE_STOP: "#3fb950", MON.HOLD: "#8b949e"}
                return f"color: {colors.get(val, '#e6edf3')}; font-weight: 700;"

            disp = verdicts.drop(columns=["id"]).copy()
            try:
                styled = disp.style.map(color_action, subset=["action"])
            except Exception:
                styled = disp
            st.dataframe(styled, use_container_width=True, height=320)

            # actionable buttons per position
            st.markdown("##### Act on signals")
            for _, v in verdicts.iterrows():
                if v["action"] in (MON.EXIT, MON.TRIM, MON.RAISE_STOP):
                    cols = st.columns([3, 2, 2, 2])
                    icon = {"EXIT": "🔴", "TRIM": "🟡", "RAISE_STOP": "🟢"}[v["action"]]
                    cols[0].markdown(f"{icon} **{v['symbol']}** — {v['reason']}")
                    if v["action"] == MON.RAISE_STOP and v["new_stop"]:
                        if cols[1].button(f"Raise stop → ₹{v['new_stop']}", key=f"rs_{v['id']}"):
                            ST.update_stop(v["id"], v["new_stop"])
                            st.rerun()
                    if v["action"] in (MON.EXIT, MON.TRIM):
                        if cols[2].button(f"Mark closed @ ₹{v['price']}", key=f"cl_{v['id']}"):
                            ST.close_position(v["id"], v["price"], v["reason"])
                            st.rerun()
                    if cols[3].button("Remove", key=f"rm_{v['id']}"):
                        ST.remove_position(v["id"])
                        st.rerun()

        # --- Closed positions / track record ---
        closed = portfolio.get("closed", [])
        if closed:
            with st.expander(f"📒 Closed trades ({len(closed)})"):
                cdf = pd.DataFrame(closed)
                show = [c for c in ["symbol", "entry_price", "exit_price",
                        "pnl", "pnl_pct", "exit_reason", "exit_date"] if c in cdf.columns]
                st.dataframe(cdf[show], use_container_width=True)
                if "pnl" in cdf:
                    wins = (cdf["pnl"] > 0).sum()
                    st.caption(f"Realized: ₹{cdf['pnl'].sum():,.0f} · "
                               f"win rate {wins}/{len(cdf)} ({wins/len(cdf)*100:.0f}%)")

# ===================== TAB 8: MY PORTFOLIO =====================
with tab8:
    st.title("My Portfolio")
    st.caption("Your private holdings, saved only on your computer. For each one, "
               "the system tells you HOLD or exactly how many shares to SELL.")
    with st.expander("📖 Plain-English glossary for this tab"):
        st.markdown(GL.render_glossary_md([
            "HOLD", "TRIM", "EXIT", "Stop", "Risk per trade", "Open P&L",
            "Realized P&L", "STCG", "LTCG"]))

    st.info("🔒 **Private:** holdings are stored in `portfolio.json` on your machine "
            "only — never uploaded, never in the GitHub repo. Broker auto-import "
            "is coming; for now, add them below.", icon="🔒")

    pf = ST.load()
    holdings = pf.get("positions", [])

    # --- broker connect (stub) ---
    bcol1, bcol2 = st.columns([1, 3])
    if bcol1.button("🔗 Connect broker"):
        if BRK.is_connected():
            imported = BRK.fetch_holdings_from_broker()
            st.success(f"Imported {len(imported)} holdings.")
        else:
            bcol2.warning("Broker API not wired in yet — this is the seam for "
                          "Zerodha/Upstox later. Add holdings manually for now.")

    # --- add holding ---
    with st.expander("➕ Add a holding", expanded=not holdings):
        hc = st.columns(4)
        h_sym = hc[0].text_input("Symbol", key="pf_sym").strip().upper()
        h_entry = hc[1].number_input("Avg buy price ₹", min_value=0.0, value=0.0, step=1.0, key="pf_entry")
        h_shares = hc[2].number_input("Shares", min_value=0, value=0, step=1, key="pf_shares")
        h_stop = hc[3].number_input("Stop ₹ (optional)", min_value=0.0, value=0.0, step=1.0, key="pf_stop")
        if st.button("Add to portfolio"):
            if h_sym and h_entry > 0 and h_shares > 0:
                # default stop = 10% below entry if not given
                stop = h_stop if h_stop > 0 else round(h_entry * 0.9, 2)
                ST.add_position(h_sym, h_entry, int(h_shares), stop, None)
                st.success(f"Added {h_sym}.")
                st.rerun()
            else:
                st.warning("Need symbol, buy price, and shares.")

    if not holdings:
        st.info("No holdings yet. Add one above to get sell/hold guidance.")
    else:
        # risk knob for the advice
        rc = st.columns(3)
        adv_risk = rc[0].slider("Max risk per position (%)", 0.5, 5.0, 2.0, 0.5,
            help="Used by the risk-based trim suggestion.")
        adv_trail = rc[1].slider("Trailing stop × ATR", 1.0, 5.0, 3.0, 0.5,
            help=GL.tip("Trailing stop"))

        with st.spinner("Fetching live prices & generating advice..."):
            price_data = {}
            for p in holdings:
                d = D.fetch_ohlcv(p["symbol"], period=period)
                if d is not None:
                    price_data[p["symbol"]] = d

        # portfolio summary
        total_value = 0
        total_cost = 0
        priced = 0
        advisories = []
        for p in holdings:
            df = price_data.get(p["symbol"])
            frow = scored.loc[p["symbol"]] if (scored is not None and not scored.empty
                                               and p["symbol"] in scored.index) else None
            adv = ADV.advise_position(p, df, capital, factor_row=frow,
                                      atr_trail_mult=adv_trail, max_risk_pct=adv_risk)
            advisories.append((p, adv))
            if "error" not in adv:
                total_value += adv["price"] * p["shares"]
                total_cost += adv["entry"] * p["shares"]
                priced += 1

        sm = st.columns(4)
        sm[0].metric("Holdings", len(holdings))
        sm[1].metric("Current value", f"₹{total_value:,.0f}")
        sm[2].metric("Total P&L", f"₹{total_value - total_cost:,.0f}",
                     f"{((total_value/total_cost - 1)*100) if total_cost else 0:+.1f}%")
        sm[3].metric("Priced", f"{priced}/{len(holdings)}")

        st.markdown("---")

        # per-holding advice cards
        for p, adv in advisories:
            if "error" in adv:
                st.warning(f"**{p['symbol']}** — couldn't fetch price "
                           f"({adv['error']}). Held: {p['shares']} @ ₹{p['entry_price']}.")
                continue

            vcolor = {"SELL ALL": "🔴", "TRIM (winner)": "🟡",
                      "HOLD": "🟢"}.get(adv["verdict"], "⚪")
            with st.container(border=True):
                hh = st.columns([3, 1, 1, 1])
                hh[0].markdown(f"### {vcolor} {adv['symbol']} — **{adv['verdict']}**")
                hh[1].metric("Price", f"₹{adv['price']:,.2f}")
                hh[2].metric("Gain", f"{adv['gain_pct']:+.0f}%")
                hh[3].metric("P&L", f"₹{adv['pnl_abs']:,.0f}")
                st.markdown(f"_{adv['headline']}_")

                if adv["verdict"] in ("TRIM (winner)", "SELL ALL"):
                    st.markdown("**Your selling options — pick one:**")
                    s = adv["strategies"]
                    order = ["scale_out", "recover_capital", "risk_trim", "trail_only"]
                    for key in order:
                        plan = s.get(key)
                        if not plan:
                            continue
                        sell = plan["sell_shares"]
                        keep = plan["keep_shares"]
                        if sell > 0:
                            badge = f"**SELL {sell}** shares · keep {keep}"
                        else:
                            badge = f"**HOLD all {keep}**"
                        st.markdown(f"- _{plan['strategy']}:_ {badge}  \n"
                                    f"  <span style='color:#8b949e;font-size:0.85rem'>"
                                    f"{plan['rationale']}</span>", unsafe_allow_html=True)

                # manage buttons
                mc = st.columns(4)
                if mc[0].button("Mark sold (all)", key=f"sold_{p['id']}"):
                    ST.close_position(p["id"], adv["price"], "manual sell all")
                    st.rerun()
                if mc[1].button("Remove", key=f"del_{p['id']}"):
                    ST.remove_position(p["id"])
                    st.rerun()

        # closed/realized
        closed = pf.get("closed", [])
        if closed:
            with st.expander(f"📒 Sold / closed ({len(closed)})"):
                cdf = pd.DataFrame(closed)
                show = [c for c in ["symbol", "entry_price", "exit_price", "pnl",
                        "pnl_pct", "exit_reason", "exit_date"] if c in cdf.columns]
                st.dataframe(cdf[show], use_container_width=True)
                if "pnl" in cdf:
                    st.caption(f"Realized total: ₹{cdf['pnl'].sum():,.0f}")

    st.caption("⚠️ Mechanical suggestions based on price/risk math, **not financial "
               "advice**. You decide and place orders in your broker. Consider taxes "
               "(STCG/LTCG) before selling.")

# ===================== TAB 4: BACKTEST =====================
with tab4:
    st.title("Backtest the Strategy")
    st.caption("The only honest way to know if the ranking has edge.")
    with st.expander("📖 Plain-English glossary for this tab"):
        st.markdown(GL.render_glossary_md([
            "Backtest", "Walk-forward", "Overfitting", "Survivorship bias",
            "Sharpe", "Alpha", "Hit rate", "Drawdown",
            "In-sample vs out-of-sample"]))
    bc1, bc2, bc3 = st.columns(3)
    hold_days = bc1.slider("Hold / rebalance (days)", 5, 30, 10)
    bt_top = bc2.slider("Portfolio size (top N)", 3, 15, 5)
    cost_bps = bc3.slider("Round-trip cost (bps)", 10, 100, 35)

    if st.button("▶️ Run backtest"):
        with st.spinner("Walk-forward backtesting (no look-ahead)..."):
            res = BT.backtest(uni, bench, horizon=horizon, hold_days=hold_days,
                              top_n=bt_top, min_turnover_cr=min_turnover,
                              cost_bps=cost_bps)
        if "error" in res:
            st.error(res["error"])
        else:
            m = st.columns(4)
            m[0].metric("CAGR", f"{res['cagr_pct']}%",
                        help="Average yearly return the strategy would have made.")
            m[1].metric("Sharpe", res["sharpe"], help=GL.tip("Sharpe"))
            m[2].metric("Hit rate", f"{res['hit_rate_pct']}%", help=GL.tip("Hit rate"))
            m[3].metric("Max DD", f"{res['max_drawdown_pct']}%", help=GL.tip("Drawdown"))
            m2 = st.columns(3)
            m2[0].metric("Strategy total", f"{res['total_return_pct']}%",
                         help="Total return over the whole test period.")
            m2[1].metric("Benchmark", f"{res['benchmark_return_pct']}%",
                         help="What you'd have made just buying the Nifty index instead.")
            m2[2].metric("Alpha", f"{res['alpha_vs_bench_pct']}%",
                         delta=res["alpha_vs_bench_pct"], help=GL.tip("Alpha"))
            curve = pd.DataFrame({
                "Strategy": res["equity_curve"][1:],
                "Benchmark": res["bench_curve"][1:],
            }, index=res["dates"])
            st.line_chart(curve, height=380)
            st.caption(f"{res['trades']} rebalances · net of {cost_bps}bps round-trip costs.")

    # ---- survivorship bias warning (always shown) ----
    st.info("⚠️ **Survivorship bias:** this backtest uses the *current* universe, "
            "so delisted/removed stocks are excluded and results are optimistic. "
            "For honest numbers, load point-in-time membership (see core/universe_pit.py). "
            "Treat the figures above as a ceiling, not an expectation.")

    # ---- WALK-FORWARD VALIDATION ----
    st.markdown("---")
    st.subheader("🔬 Walk-Forward Validation")
    st.caption("The overfitting lie-detector: judges the strategy only on data it "
               "never saw during the in-sample window. Out-of-sample is what counts.")
    wc1, wc2, wc3 = st.columns(3)
    train_d = wc1.slider("Train window (days)", 126, 504, 252, 21)
    test_d = wc2.slider("Test window (days)", 21, 126, 63, 21)
    wf_top = wc3.slider("Portfolio size (WF)", 3, 10, 5)

    if st.button("🔬 Run walk-forward"):
        with st.spinner("Running rolling out-of-sample folds... (this takes a bit)"):
            wf = WF.walk_forward(uni, bench, horizon=horizon,
                                 train_days=train_d, test_days=test_d,
                                 step_days=test_d, hold_days=hold_days,
                                 top_n=wf_top, cost_bps=cost_bps,
                                 min_turnover_cr=min_turnover)
        if "error" in wf:
            st.error(wf["error"] + " — try a longer history window (sidebar) or "
                     "shorter train/test windows.")
        else:
            agg = wf["aggregate"]
            verdict = WF.verdict_text(agg)
            if agg.get("overfit_flag"):
                st.error(verdict)
            elif "✅" in verdict:
                st.success(verdict)
            else:
                st.warning(verdict)

            wm = st.columns(4)
            wm[0].metric("Folds (OOS)", agg["folds"],
                         help="How many separate 'unseen data' tests were run.")
            wm[1].metric("OOS win rate", f"{agg['oos_win_rate_pct']}%",
                         help="% of unseen test windows that made money. Higher = more trustworthy.")
            wm[2].metric("OOS mean return", f"{agg['oos_mean_return_pct']}%",
                         help="Average return across the unseen test windows.")
            wm[3].metric("OOS compounded", f"{agg['oos_compounded_pct']}%",
                         help="Returns from all unseen windows chained together.")
            wm2 = st.columns(3)
            wm2[0].metric("In-sample mean", f"{agg['is_mean_return_pct']}%"
                          if agg["is_mean_return_pct"] is not None else "—")
            wm2[1].metric("IS→OOS gap", f"{agg['is_oos_gap_pct']}%"
                          if agg["is_oos_gap_pct"] is not None else "—",
                          help="Big positive gap = strategy overfit to history.")
            wm2[2].metric("OOS mean alpha", f"{agg['oos_mean_alpha_pct']}%"
                          if agg["oos_mean_alpha_pct"] is not None else "—")

            folds_df = pd.DataFrame(wf["folds"])
            if not folds_df.empty:
                chart = folds_df.set_index("test_start")[["is_total", "oos_total"]]
                chart.columns = ["In-sample", "Out-of-sample"]
                st.bar_chart(chart, height=300)
                st.caption("Per-fold in-sample vs out-of-sample returns. If the blue "
                           "(OOS) bars are consistently far below the others, the edge "
                           "doesn't generalize — don't scale capital into it.")

# ===================== TAB 5: ABOUT =====================
with tab5:
    st.title("Methodology & Honest Caveats")
    st.markdown("""
**What this is.** A decision-support engine that ranks NSE stocks by combining
*tactical* (days–weeks) and *structural* (multi-month) factors, filters out
illiquid/untradeable names first, explains every pick, manages exits, and
protects you from both the market and your own impulses.

**What it is not.** A profit guarantee or financial advice. SEBI's own data
shows ~70% of intraday traders and ~91% of F&O traders lose money. The edge in
Indian short-horizon trading accrues to disciplined systematic players — which
is what this tries to make you — but the base rate is brutal. Treat year one as
tuition and size capital you can afford to lose.

**Protection built in.**
- *Market regime filter* throttles exposure when the Nifty is weak (risk-off).
- *Behavioral guardrails* block oversized/no-stop trades and warn on overtrading,
  revenge trades, averaging down, and concentration.
- *Daily loss circuit-breaker* tells you to stop on a bad day.

**Validation built in.**
- *Walk-forward* tests the strategy only on unseen data, exposing overfitting.
- *Survivorship-bias* is flagged loudly; load point-in-time data for honest backtests.

**Use it the right way.**
- Treat the watchlist as *candidates to research*, not buy signals.
- Honor your stops — the whole risk framework depends on it.
- Respect costs, STT, and STCG taxes; they flip many gross-positive strategies negative.
- Validate out-of-sample before scaling. Beware overfitting.

*Not investment advice. Validate independently. Markets carry real risk of loss.*
""")
