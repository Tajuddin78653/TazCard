"""
TazCard — NSE F&O Stock Scanner
================================
BUY + SELL signals with market trend, Advance/Decline ratio,
EMA + Bollinger Band + MACD + ATR Trailing Stop conditions.

Built for Tajuddin's trading setup — matches exact Chartink scanner conditions.
"""

import os
import time
import logging
import concurrent.futures
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from scanner.stock_list import get_fno_symbols
from scanner.market_trend import get_market_pulse
from scanner.buy_scanner import scan_buy
from scanner.sell_scanner import scan_sell

logging.basicConfig(level=logging.WARNING)
IST = ZoneInfo("Asia/Kolkata")

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TazCard — NSE Scanner",
    page_icon="🃏",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""<style>
[data-testid="stAppViewContainer"] { background: #0a0f1e; }
[data-testid="stSidebar"] { background: #0d1220; }
* { color: #e2e8f0; }
h1, h2, h3 { color: #f0b429 !important; }
.stTabs [data-baseweb="tab"] { background: #111827; border: 1px solid #1e2d5a; border-radius: 8px; margin-right: 6px; color: #94a3b8; }
.stTabs [aria-selected="true"] { background: #1e3a5f; color: #f0b429 !important; border-color: #f0b429; }
.stButton > button { background: linear-gradient(135deg,#1d4ed8,#7c3aed) !important; color: #fff !important; font-weight: 700 !important; border: none !important; border-radius: 8px !important; }
[data-testid="stMetric"] { background: #111827; border: 1px solid #1e2d5a; border-radius: 10px; padding: 12px; }
</style>""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (
        now.replace(hour=9, minute=15, second=0, microsecond=0).time()
        <= t <=
        now.replace(hour=15, minute=30, second=0, microsecond=0).time()
    )


def fmt_price(v):
    try:
        return f"₹{float(v):,.2f}"
    except Exception:
        return "—"


def fmt_pct(v):
    if v is None:
        return "—"
    color = "#34d399" if v >= 0 else "#f87171"
    arrow = "▲" if v >= 0 else "▼"
    return f'<span style="color:{color};font-weight:700">{arrow} {abs(v):.2f}%</span>'


def signal_badge(sig: str) -> str:
    colors = {
        "STRONG BUY":  ("#34d399", "#052e16"),
        "BUY":         ("#86efac", "#064e3b"),
        "STRONG SELL": ("#f87171", "#450a0a"),
        "SELL":        ("#fca5a5", "#3b0505"),
        "WATCH":       ("#fbbf24", "#451a03"),
        "SKIP":        ("#6b7280", "#1f2937"),
    }
    fc, bg = colors.get(sig, ("#6b7280", "#1f2937"))
    return (f'<span style="background:{bg};color:{fc};border:1px solid {fc}44;'
            f'border-radius:20px;padding:3px 12px;font-size:12px;font-weight:700">{sig}</span>')


def cond_icon(v: bool) -> str:
    return "✅" if v else "❌"


def score_color(score: int) -> str:
    if score >= 90:
        return "#34d399"
    if score >= 70:
        return "#86efac"
    if score >= 50:
        return "#fbbf24"
    return "#f87171"


# ── Signal card renderer ──────────────────────────────────────────────────────
def render_card(r: dict, mode: str = "BUY"):
    sig   = r.get("signal", "SKIP")
    score = r.get("score", 0)
    sym   = r.get("symbol", "")
    close = r.get("close")
    chg   = r.get("change_pct")
    conds = r.get("conditions", {})
    inds  = r.get("indicators", {})

    sc = score_color(score)
    tv = f"https://in.tradingview.com/chart/?symbol=NSE:{sym}"

    # Condition rows
    if mode == "BUY":
        cond_html = (
            f"<div style='font-size:11px;margin-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:2px'>"
            f"<span>{cond_icon(conds.get('5m_ema5_gt_ema200',False))} 5m EMA5>EMA200</span>"
            f"<span>{cond_icon(conds.get('30m_close_gt_ema20',False))} 30m &gt; EMA20</span>"
            f"<span>{cond_icon(conds.get('30m_close_gt_upper_bb',False))} 30m &gt; Upper BB</span>"
            f"<span>{cond_icon(conds.get('2h_close_gt_upper_bb',False))} 2h &gt; Upper BB</span>"
            f"<span>{cond_icon(conds.get('30m_macd_bullish',False))} MACD Bullish</span>"
            f"<span>{cond_icon(conds.get('30m_atr_buy',False))} ATR Buy Signal</span>"
            f"</div>"
        )
    else:
        cond_html = (
            f"<div style='font-size:11px;margin-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:2px'>"
            f"<span>{cond_icon(conds.get('5m_ema5_lt_ema200',False))} 5m EMA5&lt;EMA200</span>"
            f"<span>{cond_icon(conds.get('30m_close_lt_ema20',False))} 30m &lt; EMA20</span>"
            f"<span>{cond_icon(conds.get('30m_close_lt_lower_bb',False))} 30m &lt; Lower BB</span>"
            f"<span>{cond_icon(conds.get('2h_close_lt_lower_bb',False))} 2h &lt; Lower BB</span>"
            f"<span>{cond_icon(conds.get('30m_macd_bearish',False))} MACD Bearish</span>"
            f"<span>{cond_icon(conds.get('30m_atr_sell',False))} ATR Sell Signal</span>"
            f"</div>"
        )

    # Entry/SL/Target
    trade_html = ""
    if sig in ("STRONG BUY", "BUY", "STRONG SELL", "SELL"):
        sl_label = "SL" if mode == "BUY" else "SL (above)"
        trade_html = (
            f"<div style='margin-top:10px;padding:8px;background:#0d1220;border-radius:6px;font-size:11px'>"
            f"<span style='color:#94a3b8'>Entry: </span><span style='color:#fff;font-weight:700'>{fmt_price(r.get('entry'))}</span>&nbsp;&nbsp;"
            f"<span style='color:#f87171'>{sl_label}: {fmt_price(r.get('sl'))}</span>&nbsp;&nbsp;"
            f"<span style='color:#34d399'>T1: {fmt_price(r.get('target1'))}</span>&nbsp;&nbsp;"
            f"<span style='color:#4ade80'>T2: {fmt_price(r.get('target2'))}</span>"
            f"</div>"
        )

    html = f"""
<div style="background:#111827;border:1px solid #1e2d5a;border-radius:12px;padding:16px;margin-bottom:10px">
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
    <div>
      <span style="font-size:18px;font-weight:800;color:#f3f4f6">{sym}</span>
      <span style="font-size:11px;color:#6b7280;margin-left:6px">NSE F&amp;O</span>
    </div>
    <div style="display:flex;align-items:center;gap:10px">
      <span style="font-size:16px;font-weight:700;color:#f3f4f6">{fmt_price(close)}</span>
      {fmt_pct(chg)}
      {signal_badge(sig)}
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:6px;margin-top:8px">
    <span style="font-size:11px;color:#94a3b8">Score:</span>
    <span style="font-size:16px;font-weight:800;color:{sc}">{score}/100</span>
    <div style="flex:1;height:6px;background:#1f2937;border-radius:3px;overflow:hidden;margin-left:4px">
      <div style="width:{score}%;height:100%;background:{sc};border-radius:3px"></div>
    </div>
    <a href="{tv}" target="_blank" style="font-size:10px;color:#60a5fa;text-decoration:none;margin-left:8px">📈 Chart</a>
  </div>
  {cond_html}
  {trade_html}
</div>"""
    st.markdown(html, unsafe_allow_html=True)


# ── Market Pulse Banner ───────────────────────────────────────────────────────
def render_market_pulse(pulse: dict):
    overall  = pulse.get("overall", "SIDEWAYS")
    nifty    = pulse.get("nifty", {})
    ad       = pulse.get("ad", {})

    direction_color = {"BULLISH": "#34d399", "BEARISH": "#f87171", "SIDEWAYS": "#fbbf24"}
    direction_bg    = {"BULLISH": "#052e16", "BEARISH": "#450a0a", "SIDEWAYS": "#451a03"}
    dc = direction_color.get(overall, "#fbbf24")
    db = direction_bg.get(overall, "#451a03")

    adv  = ad.get("advancing", "—")
    dec  = ad.get("declining", "—")
    unch = ad.get("unchanged", "—")
    ratio = ad.get("ratio", "—")
    total = ad.get("total", 0)
    adv_pct = round(adv / total * 100) if total > 0 else 0
    dec_pct = round(dec / total * 100) if total > 0 else 0

    nifty_close = nifty.get("close", "—")
    ema20       = nifty.get("ema20", "—")
    macd_val    = nifty.get("macd", "—")

    bull_count  = nifty.get("bull_count", 0)
    checks = [
        ("30m Close > EMA 20", nifty.get("above_ema20", False)),
        ("30m MACD Bullish",   nifty.get("macd_bull",   False)),
        ("30m ATR Buy Signal", nifty.get("atr_bull",    False)),
    ]
    checks_html = "".join(
        f'<span style="font-size:11px;margin-right:12px">{cond_icon(v)} {label}</span>'
        for label, v in checks
    )

    html = f"""
<div style="background:{db};border:2px solid {dc};border-radius:12px;padding:16px;margin-bottom:20px">
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
    <div>
      <span style="font-size:13px;color:#94a3b8;font-weight:600">MARKET TREND</span>
      <div style="font-size:22px;font-weight:900;color:{dc};margin-top:2px">{overall}</div>
      <div style="margin-top:6px">{checks_html}</div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;text-align:center">
      <div><div style="font-size:20px;font-weight:800;color:#34d399">{adv}</div><div style="font-size:10px;color:#94a3b8">Advancing</div></div>
      <div><div style="font-size:20px;font-weight:800;color:#f87171">{dec}</div><div style="font-size:10px;color:#94a3b8">Declining</div></div>
      <div><div style="font-size:20px;font-weight:800;color:#fbbf24">{unch}</div><div style="font-size:10px;color:#94a3b8">Unchanged</div></div>
      <div><div style="font-size:20px;font-weight:800;color:#60a5fa">{ratio}</div><div style="font-size:10px;color:#94a3b8">A/D Ratio</div></div>
    </div>
    <div style="text-align:right">
      <div style="font-size:11px;color:#94a3b8">Nifty 50</div>
      <div style="font-size:18px;font-weight:700;color:#fff">{fmt_price(nifty_close)}</div>
      <div style="font-size:11px;color:#94a3b8">EMA20: {fmt_price(ema20)} | MACD: {macd_val}</div>
    </div>
  </div>
  <div style="margin-top:10px">
    <div style="display:flex;gap:4px;height:8px;border-radius:4px;overflow:hidden">
      <div style="width:{adv_pct}%;background:#34d399"></div>
      <div style="width:{dec_pct}%;background:#f87171"></div>
      <div style="width:{max(0,100-adv_pct-dec_pct)}%;background:#fbbf24"></div>
    </div>
    <div style="display:flex;gap:16px;margin-top:4px;font-size:10px;color:#64748b">
      <span>■ Advancing {adv_pct}%</span>
      <span>■ Declining {dec_pct}%</span>
      <span>■ Unchanged</span>
    </div>
  </div>
</div>"""
    st.markdown(html, unsafe_allow_html=True)


# ── Run scan (parallel) ───────────────────────────────────────────────────────
def run_scan(symbols: list, mode: str, progress_bar) -> list:
    scanner = scan_buy if mode == "BUY" else scan_sell
    results = []
    total   = len(symbols)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(scanner, sym): sym for sym in symbols}
        done    = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            progress_bar.progress(done / total, text=f"Scanning {done}/{total} stocks...")
            try:
                r = future.result()
                if r.get("signal") not in ("SKIP", None) or r.get("score", 0) >= 50:
                    results.append(r)
            except Exception:
                pass

    return sorted(results, key=lambda x: x.get("score", 0), reverse=True)


# ── Main App ──────────────────────────────────────────────────────────────────
def main():
    now_ist = datetime.now(IST)
    market_open = is_market_open()

    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("# 🃏 TazCard — NSE F&O Scanner")
        st.caption("BUY & SELL signals · EMA + Bollinger Band + MACD + ATR · Market Trend & A/D Ratio")
    with col2:
        status_color = "#34d399" if market_open else "#ef4444"
        status_label = "🟢 Market Open" if market_open else "🔴 Market Closed"
        st.markdown(
            f'<div style="text-align:right;padding-top:20px">'
            f'<span style="background:rgba(0,0,0,0.3);color:{status_color};'
            f'border:1px solid {status_color}44;border-radius:20px;padding:6px 14px;'
            f'font-size:13px;font-weight:600">{status_label}</span><br>'
            f'<span style="font-size:11px;color:#64748b">{now_ist.strftime("%d %b %Y %H:%M IST")}</span>'
            f'</div>', unsafe_allow_html=True
        )

    st.divider()

    # Sidebar controls
    with st.sidebar:
        st.markdown("### ⚙️ Scanner Controls")
        st.caption("Configure and run your scan")
        st.divider()

        scan_mode = st.radio(
            "Scan Mode",
            ["Auto (follow market)", "BUY only", "SELL only", "Both"],
            index=0,
        )

        max_stocks = st.slider("Stocks to scan", 20, 180, 60, 10,
                               help="More stocks = slower but more comprehensive")

        min_score = st.slider("Minimum score to show", 0, 100, 50, 5)

        st.divider()
        st.markdown("**Conditions used:**")
        st.markdown("- 5m EMA(5) vs EMA(200)")
        st.markdown("- 30m Close vs EMA(20)")
        st.markdown("- 30m Close vs Upper/Lower BB(20,2)")
        st.markdown("- 2h Close vs Upper/Lower BB(20,2)")
        st.markdown("- 30m MACD (12,26,9)")
        st.markdown("- 30m ATR Trailing Stop")

        st.divider()
        st.caption("⚠️ Data: yfinance (~15-min delayed). For reference only. Not financial advice.")

    # Run button
    run_clicked = st.button("🚀 Run Scanner", use_container_width=True, type="primary")

    # ── Execute scan ──────────────────────────────────────────────────────────
    if run_clicked:
        symbols_all = get_fno_symbols()[:max_stocks]

        ph = st.empty()

        # Step 1: Market pulse
        ph.info("📡 Checking market trend & A/D ratio...")
        pulse = get_market_pulse()
        overall = pulse.get("overall", "SIDEWAYS")
        st.session_state["pulse"] = pulse

        # Step 2: Determine which scans to run
        if scan_mode == "Auto (follow market)":
            run_buy  = overall in ("BULLISH", "SIDEWAYS")
            run_sell = overall in ("BEARISH", "SIDEWAYS")
        elif scan_mode == "BUY only":
            run_buy, run_sell = True, False
        elif scan_mode == "SELL only":
            run_buy, run_sell = False, True
        else:
            run_buy, run_sell = True, True

        buy_results  = []
        sell_results = []

        # Step 3: Run BUY scan
        if run_buy:
            ph.info(f"🟢 Running BUY scanner on {len(symbols_all)} stocks...")
            prog = st.progress(0)
            buy_results = run_scan(symbols_all, "BUY", prog)
            buy_results = [r for r in buy_results if r.get("score", 0) >= min_score]
            prog.empty()

        # Step 4: Run SELL scan
        if run_sell:
            ph.info(f"🔴 Running SELL scanner on {len(symbols_all)} stocks...")
            prog2 = st.progress(0)
            sell_results = run_scan(symbols_all, "SELL", prog2)
            sell_results = [r for r in sell_results if r.get("score", 0) >= min_score]
            prog2.empty()

        ph.empty()
        st.session_state["buy_results"]  = buy_results
        st.session_state["sell_results"] = sell_results
        st.session_state["scan_time"]    = now_ist.strftime("%H:%M:%S IST")
        st.session_state["scan_mode"]    = scan_mode
        st.success(f"✅ Scan complete — {len(buy_results)} BUY + {len(sell_results)} SELL signals found · {now_ist.strftime('%H:%M:%S IST')}")

    # ── Display results ───────────────────────────────────────────────────────
    if "pulse" not in st.session_state:
        st.markdown(
            '<div style="background:#111827;border:2px dashed #1e2d5a;border-radius:14px;'
            'padding:80px 24px;text-align:center">'
            '<div style="font-size:56px">🃏</div>'
            '<div style="font-size:22px;font-weight:800;color:#f3f4f6;margin:16px 0 10px">TazCard Ready</div>'
            '<div style="font-size:14px;color:#6b7280">Click "Run Scanner" to scan F&O stocks</div>'
            '</div>', unsafe_allow_html=True
        )
        return

    # Market pulse
    render_market_pulse(st.session_state["pulse"])

    # Summary metrics
    buy_r  = st.session_state.get("buy_results",  [])
    sell_r = st.session_state.get("sell_results", [])
    strong_buy  = [r for r in buy_r  if r["signal"] == "STRONG BUY"]
    strong_sell = [r for r in sell_r if r["signal"] == "STRONG SELL"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🟢 BUY Signals",    len([r for r in buy_r  if r["signal"] in ("BUY","STRONG BUY")]))
    m2.metric("⭐ Strong BUY",     len(strong_buy))
    m3.metric("🔴 SELL Signals",   len([r for r in sell_r if r["signal"] in ("SELL","STRONG SELL")]))
    m4.metric("⭐ Strong SELL",    len(strong_sell))

    if st.session_state.get("scan_time"):
        st.caption(f"Last scan: {st.session_state['scan_time']} · Mode: {st.session_state.get('scan_mode','')}")

    # Tabs
    tabs = st.tabs(["🟢 BUY Signals", "🔴 SELL Signals", "👀 Watch List"])

    with tabs[0]:
        buy_show = [r for r in buy_r if r["signal"] in ("STRONG BUY", "BUY")]
        if not buy_show:
            st.info("No BUY signals found in this scan. Market may be bearish — check SELL tab.")
        else:
            st.markdown(f"**{len(buy_show)} BUY signals** (sorted by score)")
            for r in buy_show:
                render_card(r, "BUY")

    with tabs[1]:
        sell_show = [r for r in sell_r if r["signal"] in ("STRONG SELL", "SELL")]
        if not sell_show:
            st.info("No SELL signals found in this scan. Market may be bullish — check BUY tab.")
        else:
            st.markdown(f"**{len(sell_show)} SELL signals** (sorted by score)")
            for r in sell_show:
                render_card(r, "SELL")

    with tabs[2]:
        watch = [r for r in buy_r + sell_r if r["signal"] == "WATCH"]
        if not watch:
            st.info("No stocks in watch zone (score 50–69). Rerun scan or lower minimum score.")
        else:
            st.markdown(f"**{len(watch)} stocks to watch** — partially meeting conditions")
            for r in watch:
                mode = "BUY" if r in buy_r else "SELL"
                render_card(r, mode)


if __name__ == "__main__":
    main()
