"""
TazCard — NSE F&O Stock Scanner
================================
Single-page layout: Market Pulse + BUY + SELL + Watch all on one screen.
No tabs, no sidebar — everything visible at once.
"""

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
/* Hide sidebar toggle completely */
[data-testid="collapsedControl"] { display: none !important; }
[data-testid="stAppViewContainer"] { background: #0a0f1e; }
[data-testid="stSidebar"] { display: none !important; }
* { color: #e2e8f0; }
h1, h2, h3 { color: #f0b429 !important; }
.stButton > button {
    background: linear-gradient(135deg,#1d4ed8,#7c3aed) !important;
    color: #fff !important; font-weight: 700 !important;
    border: none !important; border-radius: 8px !important;
}
[data-testid="stMetric"] {
    background: #111827; border: 1px solid #1e2d5a;
    border-radius: 10px; padding: 12px;
}
.section-header {
    font-size: 15px; font-weight: 800; letter-spacing: 1px;
    padding: 6px 14px; border-radius: 6px; margin-bottom: 10px;
    display: inline-block;
}
.buy-header  { background: #052e16; color: #34d399; border: 1px solid #34d39944; }
.sell-header { background: #450a0a; color: #f87171; border: 1px solid #f8717144; }
.watch-header{ background: #451a03; color: #fbbf24; border: 1px solid #fbbf2444; }
</style>""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (
        now.replace(hour=9,  minute=15, second=0, microsecond=0).time()
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
    if score >= 90: return "#34d399"
    if score >= 70: return "#86efac"
    if score >= 50: return "#fbbf24"
    return "#f87171"


# ── Compact signal card ───────────────────────────────────────────────────────
def render_card(r: dict, mode: str = "BUY"):
    sig   = r.get("signal", "SKIP")
    score = r.get("score", 0)
    sym   = r.get("symbol", "")
    close = r.get("close")
    chg   = r.get("change_pct")
    conds = r.get("conditions", {})

    sc = score_color(score)
    tv = f"https://in.tradingview.com/chart/?symbol=NSE:{sym}"

    if mode == "BUY":
        c1 = cond_icon(conds.get("ema13_gt_ema50",        False))
        c2 = cond_icon(conds.get("close_gt_ema13",        False))
        c3 = cond_icon(conds.get("atr_stop_below",        False))
        c4 = cond_icon(conds.get("macd_line_gt_signal",   False))
        c5 = cond_icon(conds.get("macd_hist_positive",    False))
        c6 = ""   # only 5 conditions now
        lbl1, lbl2, lbl3, lbl4 = "EMA13>EMA50", "Close>EMA13", "ATR below", "MACD>"
    else:
        c1 = cond_icon(conds.get("ema13_lt_ema50",        False))
        c2 = cond_icon(conds.get("close_lt_ema13",        False))
        c3 = cond_icon(conds.get("atr_stop_above",        False))
        c4 = cond_icon(conds.get("macd_line_lt_signal",   False))
        c5 = cond_icon(conds.get("macd_hist_negative",    False))
        c6 = ""
        lbl1, lbl2, lbl3, lbl4 = "EMA13<EMA50", "Close<EMA13", "ATR above", "MACD<"

    trade_html = ""
    if sig in ("STRONG BUY", "BUY", "STRONG SELL", "SELL"):
        sl_lbl = "SL" if mode == "BUY" else "SL↑"
        trade_html = (
            f"<div style='margin-top:8px;padding:6px 10px;background:#0d1220;"
            f"border-radius:6px;font-size:11px;display:flex;gap:16px;flex-wrap:wrap'>"
            f"<span><span style='color:#94a3b8'>Entry </span>"
            f"<b style='color:#fff'>{fmt_price(r.get('entry'))}</b></span>"
            f"<span><span style='color:#f87171'>{sl_lbl} {fmt_price(r.get('sl'))}</span></span>"
            f"<span><span style='color:#34d399'>T1 {fmt_price(r.get('target1'))}</span></span>"
            f"<span><span style='color:#4ade80'>T2 {fmt_price(r.get('target2'))}</span></span>"
            f"</div>"
        )

    html = f"""
<div style="background:#111827;border:1px solid #1e2d5a;border-radius:10px;
            padding:12px 14px;margin-bottom:8px">
  <div style="display:flex;align-items:center;justify-content:space-between;
              flex-wrap:wrap;gap:6px">
    <div style="display:flex;align-items:center;gap:10px">
      <span style="font-size:16px;font-weight:800;color:#f3f4f6">{sym}</span>
      <span style="font-size:14px;font-weight:700;color:#e2e8f0">{fmt_price(close)}</span>
      {fmt_pct(chg)}
    </div>
    <div style="display:flex;align-items:center;gap:8px">
      <span style="font-size:14px;font-weight:800;color:{sc}">{score}/100</span>
      <div style="width:60px;height:5px;background:#1f2937;border-radius:3px;overflow:hidden">
        <div style="width:{score}%;height:100%;background:{sc};border-radius:3px"></div>
      </div>
      {signal_badge(sig)}
      <a href="{tv}" target="_blank"
         style="font-size:11px;color:#60a5fa;text-decoration:none">📈</a>
    </div>
  </div>
  <div style="font-size:11px;margin-top:6px;display:flex;flex-wrap:wrap;gap:10px;
              color:#94a3b8">
    <span>{c1} {lbl1}</span>
    <span>{c2} {lbl2}</span>
    <span>{c3} {lbl3}</span>
    <span>{c4} {lbl4}</span>
    <span>{c5} Histogram</span>
  </div>
  {trade_html}
</div>"""
    st.markdown(html, unsafe_allow_html=True)


# ── Market Pulse Banner ───────────────────────────────────────────────────────
def render_market_pulse(pulse: dict):
    overall = pulse.get("overall", "SIDEWAYS")
    nifty   = pulse.get("nifty", {})
    ad      = pulse.get("ad", {})

    dc = {"BULLISH": "#34d399", "BEARISH": "#f87171", "SIDEWAYS": "#fbbf24"}.get(overall, "#fbbf24")
    db = {"BULLISH": "#052e16", "BEARISH": "#450a0a", "SIDEWAYS": "#451a03"}.get(overall, "#451a03")

    adv   = ad.get("advancing", 0) or 0
    dec   = ad.get("declining", 0) or 0
    unch  = ad.get("unchanged", 0) or 0
    ratio = ad.get("ratio", "—")
    total = ad.get("total", 0) or 1
    adv_pct = round(adv / total * 100)
    dec_pct = round(dec / total * 100)

    ci = lambda v: cond_icon(v)
    checks_html = (
        f'{ci(nifty.get("ema_cross_bull", False))} EMA13>50 &nbsp;'
        f'{ci(nifty.get("atr_bull",       False))} ATR &nbsp;'
        f'{ci(nifty.get("macd_bull",      False))} MACD'
    )

    html = f"""
<div style="background:{db};border:2px solid {dc};border-radius:12px;
            padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;justify-content:space-between;
              flex-wrap:wrap;gap:10px">
    <div>
      <div style="font-size:11px;color:#94a3b8;font-weight:600;letter-spacing:1px">
        MARKET TREND (Nifty 5-min)</div>
      <div style="font-size:24px;font-weight:900;color:{dc}">{overall}</div>
      <div style="font-size:11px;margin-top:4px">{checks_html}</div>
    </div>
    <div style="display:flex;gap:20px;text-align:center">
      <div><div style="font-size:18px;font-weight:800;color:#34d399">{adv}</div>
           <div style="font-size:10px;color:#94a3b8">Advancing</div></div>
      <div><div style="font-size:18px;font-weight:800;color:#f87171">{dec}</div>
           <div style="font-size:10px;color:#94a3b8">Declining</div></div>
      <div><div style="font-size:18px;font-weight:800;color:#fbbf24">{unch}</div>
           <div style="font-size:10px;color:#94a3b8">Unchanged</div></div>
      <div><div style="font-size:18px;font-weight:800;color:#60a5fa">{ratio}</div>
           <div style="font-size:10px;color:#94a3b8">A/D Ratio</div></div>
    </div>
    <div style="text-align:right">
      <div style="font-size:11px;color:#94a3b8">Nifty 50 (5-min)</div>
      <div style="font-size:20px;font-weight:700;color:#fff">
        {fmt_price(nifty.get("close"))}</div>
      <div style="font-size:11px;color:#94a3b8">
        EMA13: {fmt_price(nifty.get("ema13"))} &nbsp;|&nbsp;
        EMA50: {fmt_price(nifty.get("ema50"))} &nbsp;|&nbsp;
        MACD: {nifty.get("macd","-")}</div>
    </div>
  </div>
  <div style="margin-top:10px">
    <div style="display:flex;gap:3px;height:6px;border-radius:3px;overflow:hidden">
      <div style="width:{adv_pct}%;background:#34d399"></div>
      <div style="width:{dec_pct}%;background:#f87171"></div>
      <div style="width:{max(0,100-adv_pct-dec_pct)}%;background:#64748b"></div>
    </div>
    <div style="display:flex;gap:14px;margin-top:3px;font-size:10px;color:#64748b">
      <span>■ Adv {adv_pct}%</span>
      <span>■ Dec {dec_pct}%</span>
      <span>■ Unch</span>
    </div>
  </div>
</div>"""
    st.markdown(html, unsafe_allow_html=True)


# ── Parallel scanner ──────────────────────────────────────────────────────────
def run_scan(symbols: list, mode: str, progress_bar) -> list:
    scanner = scan_buy if mode == "BUY" else scan_sell
    results = []
    total   = len(symbols)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(scanner, sym): sym for sym in symbols}
        done    = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            progress_bar.progress(done / total, text=f"Scanning {done}/{total}...")
            try:
                r = future.result()
                if r.get("signal") not in ("SKIP", None):
                    results.append(r)
                elif r.get("score", 0) >= 20:
                    results.append(r)
            except Exception:
                pass

    return sorted(results, key=lambda x: x.get("score", 0), reverse=True)


# ── Main App ──────────────────────────────────────────────────────────────────
def main():
    now_ist     = datetime.now(IST)
    market_open = is_market_open()

    # ── Top header row ────────────────────────────────────────────────────────
    h1, h2, h3 = st.columns([3, 2, 2])
    with h1:
        st.markdown("## 🃏 TazCard — NSE F&O Scanner")
        st.caption("EMA · Bollinger Bands · MACD · ATR · Market Trend")
    with h2:
        status_color = "#34d399" if market_open else "#ef4444"
        status_label = "🟢 Market Open" if market_open else "🔴 Market Closed"
        st.markdown(
            f'<div style="padding-top:18px;text-align:center">'
            f'<span style="background:rgba(0,0,0,0.3);color:{status_color};'
            f'border:1px solid {status_color}44;border-radius:20px;padding:5px 14px;'
            f'font-size:13px;font-weight:600">{status_label}</span><br>'
            f'<span style="font-size:11px;color:#64748b">'
            f'{now_ist.strftime("%d %b %Y %H:%M IST")}</span>'
            f'</div>', unsafe_allow_html=True
        )
    with h3:
        # Inline controls — no sidebar needed
        scan_mode = st.selectbox(
            "Mode",
            ["Both BUY + SELL", "BUY only", "SELL only", "Auto (follow market)"],
            index=0, label_visibility="collapsed",
        )

    # ── Controls row ──────────────────────────────────────────────────────────
    cc1, cc2, cc3 = st.columns([2, 2, 2])
    with cc1:
        max_stocks = st.slider("Stocks to scan", 20, 180, 60, 10)
    with cc2:
        min_score = st.slider("Min score", 0, 100, 0, 5)
    with cc3:
        st.markdown("<div style='padding-top:26px'>", unsafe_allow_html=True)
        run_clicked = st.button("🚀 Run Scanner", use_container_width=True, type="primary")
        st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

    # ── Execute scan ──────────────────────────────────────────────────────────
    if run_clicked:
        symbols_all = get_fno_symbols()[:max_stocks]
        ph = st.empty()

        ph.info("📡 Checking market trend & A/D ratio...")
        pulse   = get_market_pulse()
        overall = pulse.get("overall", "SIDEWAYS")
        st.session_state["pulse"] = pulse

        # Which scans to run — market trend GATES the scan
        # BULLISH → BUY only | BEARISH → SELL only | SIDEWAYS → both
        if scan_mode == "Auto (follow market)":
            if overall == "BULLISH":
                run_buy, run_sell = True, False
            elif overall == "BEARISH":
                run_buy, run_sell = False, True
            else:  # SIDEWAYS — run both
                run_buy, run_sell = True, True
        elif scan_mode == "BUY only":
            run_buy, run_sell = True, False
        elif scan_mode == "SELL only":
            run_buy, run_sell = False, True
        else:  # Both BUY + SELL
            run_buy, run_sell = True, True

        buy_results  = []
        sell_results = []

        if run_buy:
            ph.info(f"🟢 BUY scan — {len(symbols_all)} stocks...")
            prog = st.progress(0)
            buy_results  = run_scan(symbols_all, "BUY", prog)
            buy_results  = [r for r in buy_results  if r.get("score", 0) >= min_score]
            prog.empty()

        if run_sell:
            ph.info(f"🔴 SELL scan — {len(symbols_all)} stocks...")
            prog2 = st.progress(0)
            sell_results = run_scan(symbols_all, "SELL", prog2)
            sell_results = [r for r in sell_results if r.get("score", 0) >= min_score]
            prog2.empty()

        ph.empty()
        st.session_state["buy_results"]  = buy_results
        st.session_state["sell_results"] = sell_results
        st.session_state["scan_time"]    = now_ist.strftime("%H:%M:%S IST")
        st.session_state["scan_mode"]    = scan_mode

        # Count only actionable signals (not WATCH/SKIP)
        n_buy  = len([r for r in buy_results  if r.get("signal") in ("BUY", "STRONG BUY")])
        n_sell = len([r for r in sell_results if r.get("signal") in ("SELL", "STRONG SELL")])
        n_watch = len([r for r in buy_results + sell_results if r.get("signal") == "WATCH"])
        st.success(
            f"✅ Scan done — {n_buy} BUY  |  {n_sell} SELL  |  {n_watch} WATCH  "
            f"· {now_ist.strftime('%H:%M:%S IST')}"
        )
        st.rerun()

    # ── Display ───────────────────────────────────────────────────────────────
    if "pulse" not in st.session_state:
        st.markdown(
            '<div style="background:#111827;border:2px dashed #1e2d5a;border-radius:14px;'
            'padding:80px 24px;text-align:center">'
            '<div style="font-size:56px">🃏</div>'
            '<div style="font-size:22px;font-weight:800;color:#f3f4f6;margin:16px 0 8px">'
            'TazCard Ready</div>'
            '<div style="font-size:14px;color:#6b7280">'
            'Set your options above and click Run Scanner</div>'
            '</div>', unsafe_allow_html=True
        )
        return

    # Market pulse banner (full width)
    render_market_pulse(st.session_state["pulse"])

    buy_r  = st.session_state.get("buy_results",  [])
    sell_r = st.session_state.get("sell_results", [])

    buy_signals  = [r for r in buy_r  if r["signal"] in ("STRONG BUY",  "BUY")]
    sell_signals = [r for r in sell_r if r["signal"] in ("STRONG SELL", "SELL")]
    watch_list   = [r for r in buy_r + sell_r if r["signal"] == "WATCH"]

    # Summary metrics row
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("🟢 BUY",        len(buy_signals))
    m2.metric("⭐ Strong BUY", len([r for r in buy_signals  if r["signal"] == "STRONG BUY"]))
    m3.metric("🔴 SELL",       len(sell_signals))
    m4.metric("⭐ Strong SELL",len([r for r in sell_signals if r["signal"] == "STRONG SELL"]))
    m5.metric("👀 Watch",      len(watch_list))

    if st.session_state.get("scan_time"):
        st.caption(
            f"Last scan: {st.session_state['scan_time']} · "
            f"Mode: {st.session_state.get('scan_mode','')} · "
            f"⚠️ Data ~15min delayed. Not financial advice."
        )

    st.divider()

    # ── THREE COLUMNS — all on one page ──────────────────────────────────────
    col_buy, col_sell, col_watch = st.columns(3)

    with col_buy:
        st.markdown(
            f'<div class="section-header buy-header">'
            f'🟢 BUY Signals ({len(buy_signals)})</div>',
            unsafe_allow_html=True
        )
        if not buy_signals:
            st.markdown(
                '<div style="background:#111827;border:1px solid #1e2d5a;border-radius:8px;'
                'padding:20px;text-align:center;color:#6b7280;font-size:13px">'
                'No BUY signals</div>', unsafe_allow_html=True
            )
        else:
            for r in buy_signals:
                render_card(r, "BUY")

    with col_sell:
        st.markdown(
            f'<div class="section-header sell-header">'
            f'🔴 SELL Signals ({len(sell_signals)})</div>',
            unsafe_allow_html=True
        )
        if not sell_signals:
            st.markdown(
                '<div style="background:#111827;border:1px solid #1e2d5a;border-radius:8px;'
                'padding:20px;text-align:center;color:#6b7280;font-size:13px">'
                'No SELL signals</div>', unsafe_allow_html=True
            )
        else:
            for r in sell_signals:
                render_card(r, "SELL")

    with col_watch:
        st.markdown(
            f'<div class="section-header watch-header">'
            f'👀 Watch List ({len(watch_list)})</div>',
            unsafe_allow_html=True
        )
        if not watch_list:
            st.markdown(
                '<div style="background:#111827;border:1px solid #1e2d5a;border-radius:8px;'
                'padding:20px;text-align:center;color:#6b7280;font-size:13px">'
                'No stocks in watch zone</div>', unsafe_allow_html=True
            )
        else:
            for r in watch_list:
                mode = "BUY" if r in buy_r else "SELL"
                render_card(r, mode)


if __name__ == "__main__":
    main()
