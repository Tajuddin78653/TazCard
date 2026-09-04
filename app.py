"""
TazCard - NSE F&O Stock Scanner
================================
V3 — 2-min chart + Auto-refresh every 5 min + Daily Report tab

Tab 1: Live Scanner  — BUY / SELL / WATCH columns (auto-refreshes every 2 min)
Tab 2: Daily Report  — Every triggered signal logged with timestamp, entry, SL, T1, T2, status
"""

import logging
import concurrent.futures
from datetime import datetime, date
from zoneinfo import ZoneInfo

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from scanner.stock_list import get_fno_symbols
from scanner.market_trend import get_market_pulse
from scanner.buy_scanner import scan_buy
from scanner.sell_scanner import scan_sell

logging.basicConfig(level=logging.WARNING)
IST = ZoneInfo("Asia/Kolkata")

st.set_page_config(
    page_title="TazCard - NSE Scanner",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""<style>
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
div[data-testid="stTab"] button { font-size: 14px !important; font-weight: 700 !important; }
</style>""", unsafe_allow_html=True)


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
        return f"\u20b9{float(v):,.2f}"
    except Exception:
        return "-"


def fmt_pct(v):
    if v is None:
        return "-"
    color = "#34d399" if v >= 0 else "#f87171"
    arrow = "\u25b2" if v >= 0 else "\u25bc"
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


def status_badge(status: str) -> str:
    colors = {
        "OPEN":      ("#60a5fa", "#1e3a5f"),
        "T1 Hit":    ("#34d399", "#052e16"),
        "T2 Hit":    ("#4ade80", "#052e16"),
        "SL Hit":    ("#f87171", "#450a0a"),
    }
    fc, bg = colors.get(status, ("#94a3b8", "#1f2937"))
    return (f'<span style="background:{bg};color:{fc};border:1px solid {fc}44;'
            f'border-radius:12px;padding:2px 10px;font-size:11px;font-weight:700">{status}</span>')


def cond_icon(v: bool) -> str:
    return "\u2705" if v else "\u274c"


def score_color(score: int) -> str:
    if score >= 90: return "#34d399"
    if score >= 70: return "#86efac"
    if score >= 50: return "#fbbf24"
    return "#f87171"


def init_state():
    today = date.today().isoformat()
    if st.session_state.get("log_date") != today:
        st.session_state["daily_log"]    = []
        st.session_state["log_date"]     = today
        st.session_state["logged_keys"]  = set()
    for k, v in [("daily_log",[]), ("logged_keys",set()), ("buy_results",[]),
                  ("sell_results",[]), ("pulse",None), ("scan_time",None),
                  ("scan_mode","Auto (follow market)"), ("max_stocks",60), ("min_score",0)]:
        if k not in st.session_state:
            st.session_state[k] = v


def log_signals(results: list, scan_direction: str, market_trend: str, scan_ts: str):
    now = datetime.now(IST)
    minute_bucket = (now.minute // 2) * 2
    time_bucket   = f"{now.hour:02d}:{minute_bucket:02d}"
    for r in results:
        sig = r.get("signal", "SKIP")
        if sig not in ("STRONG BUY", "BUY", "STRONG SELL", "SELL"):
            continue
        dedup_key = f"{r['symbol']}-{time_bucket}"
        if dedup_key in st.session_state["logged_keys"]:
            continue
        st.session_state["logged_keys"].add(dedup_key)
        st.session_state["daily_log"].append({
            "time":         scan_ts,
            "symbol":       r["symbol"],
            "signal":       sig,
            "direction":    scan_direction,
            "market_trend": market_trend,
            "entry":        r.get("entry"),
            "sl":           r.get("sl"),
            "sl_pct":       r.get("sl_pct"),
            "target1":      r.get("target1"),
            "target2":      r.get("target2"),
            "score":        r.get("score", 0),
            "status":       "OPEN",
            "close_now":    r.get("close"),
        })


def update_log_status():
    buy_prices  = {r["symbol"]: r.get("close") for r in st.session_state.get("buy_results",  [])}
    sell_prices = {r["symbol"]: r.get("close") for r in st.session_state.get("sell_results", [])}
    for entry in st.session_state["daily_log"]:
        if entry["status"] != "OPEN":
            continue
        sym   = entry["symbol"]
        price = buy_prices.get(sym) or sell_prices.get(sym)
        if not price:
            continue
        entry["close_now"] = price
        sl  = entry.get("sl")
        t1  = entry.get("target1")
        t2  = entry.get("target2")
        sig = entry.get("signal", "")
        if sig in ("STRONG BUY", "BUY"):
            if sl and price <= sl:        entry["status"] = "SL Hit"
            elif t2 and price >= t2:      entry["status"] = "T2 Hit"
            elif t1 and price >= t1:      entry["status"] = "T1 Hit"
        else:
            if sl and price >= sl:        entry["status"] = "SL Hit"
            elif t2 and price <= t2:      entry["status"] = "T2 Hit"
            elif t1 and price <= t1:      entry["status"] = "T1 Hit"


def render_card(r: dict, mode: str = "BUY"):
    sig   = r.get("signal", "SKIP")
    score = r.get("score", 0)
    sym   = r.get("symbol", "")
    close = r.get("close")
    chg   = r.get("change_pct")
    conds = r.get("conditions", {})
    sc    = score_color(score)
    tv    = f"https://in.tradingview.com/chart/?symbol=NSE:{sym}"

    if mode == "BUY":
        c1 = cond_icon(conds.get("ema13_gt_ema50",      False))
        c2 = cond_icon(conds.get("close_gt_ema13",      False))
        c3 = cond_icon(conds.get("atr_stop_below",      False))
        c4 = cond_icon(conds.get("macd_line_gt_signal", False))
        c5 = cond_icon(conds.get("macd_hist_positive",  False))
        lbl1,lbl2,lbl3,lbl4 = "EMA13>EMA50","Close>EMA13","ATR below","MACD>"
    else:
        c1 = cond_icon(conds.get("ema13_lt_ema50",      False))
        c2 = cond_icon(conds.get("close_lt_ema13",      False))
        c3 = cond_icon(conds.get("atr_stop_above",      False))
        c4 = cond_icon(conds.get("macd_line_lt_signal", False))
        c5 = cond_icon(conds.get("macd_hist_negative",  False))
        lbl1,lbl2,lbl3,lbl4 = "EMA13<EMA50","Close<EMA13","ATR above","MACD<"

    trade_html = ""
    if sig in ("STRONG BUY", "BUY", "STRONG SELL", "SELL"):
        trade_html = (
            f"<div style='margin-top:8px;padding:6px 10px;background:#0d1220;"
            f"border-radius:6px;font-size:11px;display:flex;gap:16px;flex-wrap:wrap'>"
            f"<span><span style='color:#94a3b8'>Entry </span>"
            f"<b style='color:#fff'>{fmt_price(r.get('entry'))}</b></span>"
            f"<span><span style='color:#f87171'>SL {fmt_price(r.get('sl'))}</span></span>"
            f"<span><span style='color:#34d399'>T1 {fmt_price(r.get('target1'))}</span></span>"
            f"<span><span style='color:#4ade80'>T2 {fmt_price(r.get('target2'))}</span></span>"
            f"</div>"
        )

    st.markdown(f"""
<div style="background:#111827;border:1px solid #1e2d5a;border-radius:10px;padding:12px 14px;margin-bottom:8px">
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px">
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
      <a href="{tv}" target="_blank" style="font-size:11px;color:#60a5fa;text-decoration:none">&#x1F4CA;</a>
    </div>
  </div>
  <div style="font-size:11px;margin-top:6px;display:flex;flex-wrap:wrap;gap:10px;color:#94a3b8">
    <span>{c1} {lbl1}</span><span>{c2} {lbl2}</span>
    <span>{c3} {lbl3}</span><span>{c4} {lbl4}</span><span>{c5} Histogram</span>
  </div>
  {trade_html}
</div>""", unsafe_allow_html=True)


def render_market_pulse(pulse: dict):
    overall = pulse.get("overall", "SIDEWAYS")
    nifty   = pulse.get("nifty", {})
    ad      = pulse.get("ad", {})
    dc = {"BULLISH":"#34d399","BEARISH":"#f87171","SIDEWAYS":"#fbbf24"}.get(overall,"#fbbf24")
    db = {"BULLISH":"#052e16","BEARISH":"#450a0a","SIDEWAYS":"#451a03"}.get(overall,"#451a03")
    adv  = ad.get("advancing", 0) or 0
    dec  = ad.get("declining", 0) or 0
    unch = ad.get("unchanged", 0) or 0
    ratio = ad.get("ratio", "-")
    total = ad.get("total", 0) or 1
    adv_pct = round(adv / total * 100)
    dec_pct = round(dec / total * 100)
    ci = lambda v: cond_icon(v)
    checks = (f'{ci(nifty.get("ema_cross_bull",False))} EMA13>50 &nbsp;'
              f'{ci(nifty.get("atr_bull",False))} ATR &nbsp;'
              f'{ci(nifty.get("macd_bull",False))} MACD')
    st.markdown(f"""
<div style="background:{db};border:2px solid {dc};border-radius:12px;padding:14px 18px;margin-bottom:16px">
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
    <div>
      <div style="font-size:11px;color:#94a3b8;font-weight:600;letter-spacing:1px">MARKET TREND (Nifty 2-min)</div>
      <div style="font-size:24px;font-weight:900;color:{dc}">{overall}</div>
      <div style="font-size:11px;margin-top:4px">{checks}</div>
    </div>
    <div style="display:flex;gap:20px;text-align:center">
      <div><div style="font-size:18px;font-weight:800;color:#34d399">{adv}</div><div style="font-size:10px;color:#94a3b8">Advancing</div></div>
      <div><div style="font-size:18px;font-weight:800;color:#f87171">{dec}</div><div style="font-size:10px;color:#94a3b8">Declining</div></div>
      <div><div style="font-size:18px;font-weight:800;color:#fbbf24">{unch}</div><div style="font-size:10px;color:#94a3b8">Unchanged</div></div>
      <div><div style="font-size:18px;font-weight:800;color:#60a5fa">{ratio}</div><div style="font-size:10px;color:#94a3b8">A/D Ratio</div></div>
    </div>
    <div style="text-align:right">
      <div style="font-size:11px;color:#94a3b8">Nifty 50 (2-min)</div>
      <div style="font-size:20px;font-weight:700;color:#fff">{fmt_price(nifty.get("close"))}</div>
      <div style="font-size:11px;color:#94a3b8">EMA13:{fmt_price(nifty.get("ema13"))} | EMA50:{fmt_price(nifty.get("ema50"))} | MACD:{nifty.get("macd","-")}</div>
    </div>
  </div>
  <div style="margin-top:10px">
    <div style="display:flex;gap:3px;height:6px;border-radius:3px;overflow:hidden">
      <div style="width:{adv_pct}%;background:#34d399"></div>
      <div style="width:{dec_pct}%;background:#f87171"></div>
      <div style="width:{max(0,100-adv_pct-dec_pct)}%;background:#64748b"></div>
    </div>
    <div style="display:flex;gap:14px;margin-top:3px;font-size:10px;color:#64748b">
      <span>&#x25B2; Adv {adv_pct}%</span><span>&#x25BC; Dec {dec_pct}%</span><span>&#x2014; Unch</span>
    </div>
  </div>
</div>""", unsafe_allow_html=True)


def run_scan(symbols: list, mode: str, progress_bar=None) -> list:
    scanner = scan_buy if mode == "BUY" else scan_sell
    results = []
    total   = len(symbols)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(scanner, sym): sym for sym in symbols}
        done    = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            if progress_bar:
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


def execute_scan(symbols_all: list, scan_mode: str, min_score: int, show_progress: bool = True):
    pulse   = get_market_pulse()
    overall = pulse.get("overall", "SIDEWAYS")
    st.session_state["pulse"] = pulse

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
    scan_ts      = datetime.now(IST).strftime("%H:%M:%S")

    if run_buy:
        prog = st.progress(0) if show_progress else None
        buy_results = run_scan(symbols_all, "BUY", prog)
        buy_results = [r for r in buy_results if r.get("score", 0) >= min_score]
        if prog: prog.empty()

    if run_sell:
        prog2 = st.progress(0) if show_progress else None
        sell_results = run_scan(symbols_all, "SELL", prog2)
        sell_results = [r for r in sell_results if r.get("score", 0) >= min_score]
        if prog2: prog2.empty()

    st.session_state["buy_results"]  = buy_results
    st.session_state["sell_results"] = sell_results
    st.session_state["scan_time"]    = scan_ts
    st.session_state["scan_mode"]    = scan_mode

    if run_buy:
        log_signals(buy_results,  "BUY",  overall, scan_ts)
    if run_sell:
        log_signals(sell_results, "SELL", overall, scan_ts)

    update_log_status()
    return buy_results, sell_results, overall


def render_daily_report():
    log = st.session_state.get("daily_log", [])
    today_str = date.today().strftime("%d %b %Y")
    st.markdown(f"## \U0001f4cb Daily Triggered Signals \u2014 {today_str}")

    if not log:
        st.markdown(
            '<div style="background:#111827;border:2px dashed #1e2d5a;border-radius:14px;'
            'padding:60px 24px;text-align:center">'
            '<div style="font-size:48px">\U0001f4ed</div>'
            '<div style="font-size:18px;font-weight:800;color:#f3f4f6;margin:12px 0 6px">'
            'No signals yet today</div>'
            '<div style="font-size:13px;color:#6b7280">'
            'Every BUY/SELL signal will appear here with exact trigger time</div>'
            '</div>', unsafe_allow_html=True
        )
        return

    total      = len(log)
    buy_count  = len([e for e in log if e["signal"] in ("STRONG BUY",  "BUY")])
    sell_count = len([e for e in log if e["signal"] in ("STRONG SELL", "SELL")])
    open_count = len([e for e in log if e["status"] == "OPEN"])
    t1_count   = len([e for e in log if e["status"] == "T1 Hit"])
    t2_count   = len([e for e in log if e["status"] == "T2 Hit"])
    sl_count   = len([e for e in log if e["status"] == "SL Hit"])

    m1,m2,m3,m4,m5,m6,m7 = st.columns(7)
    m1.metric("\U0001f4ca Total",  total)
    m2.metric("\U0001f7e2 BUY",    buy_count)
    m3.metric("\U0001f534 SELL",   sell_count)
    m4.metric("\U0001f535 Open",   open_count)
    m5.metric("\u2705 T1 Hit",     t1_count)
    m6.metric("\U0001f3af T2 Hit", t2_count)
    m7.metric("\u274c SL Hit",     sl_count)

    st.markdown("---")

    fc1, fc2, fc3 = st.columns([2, 2, 2])
    with fc1:
        filter_sig = st.selectbox("Filter Signal",
            ["All","STRONG BUY","BUY","STRONG SELL","SELL"], key="rf_sig")
    with fc2:
        filter_status = st.selectbox("Filter Status",
            ["All","OPEN","T1 Hit","T2 Hit","SL Hit"], key="rf_st")
    with fc3:
        filter_dir = st.selectbox("Filter Direction",
            ["All","BUY","SELL"], key="rf_dir")

    filtered = log[:]
    if filter_sig    != "All": filtered = [e for e in filtered if e["signal"]    == filter_sig]
    if filter_status != "All": filtered = [e for e in filtered if e["status"]    == filter_status]
    if filter_dir    != "All": filtered = [e for e in filtered if e["direction"] == filter_dir]
    filtered = list(reversed(filtered))

    st.caption(f"{len(filtered)} signals matching filter \u2014 newest first")
    st.markdown("")

    for e in filtered:
        sig    = e["signal"]
        is_buy = sig in ("STRONG BUY", "BUY")
        bc     = "#34d399" if is_buy else "#f87171"
        bg     = "#0a1a10" if is_buy else "#1a0a0a"
        tc     = {"BULLISH":"#34d399","BEARISH":"#f87171","SIDEWAYS":"#fbbf24"}.get(
                    e.get("market_trend","SIDEWAYS"),"#fbbf24")

        close_now = e.get("close_now")
        pnl_html  = ""
        if close_now and e.get("entry"):
            diff = close_now - e["entry"]
            pct  = diff / e["entry"] * 100
            if not is_buy: diff,pct = -diff,-pct
            color = "#34d399" if diff >= 0 else "#f87171"
            arrow = "\u25b2" if diff >= 0 else "\u25bc"
            pnl_html = (f'<span style="color:{color};font-size:11px;font-weight:700">'
                        f'{arrow} {abs(pct):.2f}% (\u20b9{abs(diff):.2f})</span>')

        tv_url = f"https://in.tradingview.com/chart/?symbol=NSE:{e['symbol']}"

        st.markdown(f"""
<div style="background:{bg};border:1px solid {bc}44;border-left:3px solid {bc};
            border-radius:8px;padding:12px 16px;margin-bottom:8px">
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <span style="font-size:13px;font-weight:800;color:#f3f4f6">\U0001f550 {e['time']}</span>
      <span style="font-size:16px;font-weight:800">
        <a href="{tv_url}" target="_blank" style="color:#fff;text-decoration:none">{e['symbol']}</a>
      </span>
      {signal_badge(sig)}
      {status_badge(e['status'])}
    </div>
    <div style="display:flex;align-items:center;gap:12px">
      <span style="font-size:11px;color:#94a3b8">
        Trend: <span style="color:{tc};font-weight:700">{e.get('market_trend','?')}</span>
      </span>
      <span style="font-size:11px;font-weight:700;color:#fbbf24">{e['score']}/100</span>
    </div>
  </div>
  <div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:16px;font-size:12px">
    <span><span style="color:#94a3b8">Entry </span><b style="color:#fff">{fmt_price(e.get('entry'))}</b></span>
    <span><span style="color:#f87171">SL </span><b style="color:#f87171">{fmt_price(e.get('sl'))}</b>
          <span style="color:#64748b"> ({e.get('sl_pct','?')}%)</span></span>
    <span><span style="color:#34d399">T1 </span><b style="color:#34d399">{fmt_price(e.get('target1'))}</b></span>
    <span><span style="color:#4ade80">T2 </span><b style="color:#4ade80">{fmt_price(e.get('target2'))}</b></span>
    <span><span style="color:#94a3b8">Now </span><b style="color:#e2e8f0">{fmt_price(close_now)}</b></span>
    {pnl_html}
  </div>
</div>""", unsafe_allow_html=True)

    st.markdown("---")
    if st.button("\U0001f5d1 Clear Today's Log", type="secondary"):
        st.session_state["daily_log"]   = []
        st.session_state["logged_keys"] = set()
        st.rerun()


def main():
    init_state()
    now_ist     = datetime.now(IST)
    market_open = is_market_open()

    # Auto-refresh every 5 minutes — ONLY during market hours
    if market_open:
        refresh_count = st_autorefresh(interval=300_000, key="auto_refresh_5m")
    else:
        refresh_count = 0

    h1, h2, h3 = st.columns([3, 2, 2])
    with h1:
        st.markdown("## \U0001f4e1 TazCard - NSE F&O Scanner")
        st.caption("EMA 13/50 \u00b7 ATR Trailing Stop \u00b7 MACD (12,26,9) \u00b7 2-min chart \u00b7 Auto-refresh every 5 min during market hours")
    with h2:
        sc = "#34d399" if market_open else "#ef4444"
        sl = "\U0001f7e2 Market Open" if market_open else "\U0001f534 Market Closed"
        al = " \u00b7 \U0001f504 Auto ON" if market_open else " \u00b7 \u23f8 Auto paused"
        st.markdown(
            f'<div style="padding-top:18px;text-align:center">'
            f'<span style="background:rgba(0,0,0,0.3);color:{sc};border:1px solid {sc}44;'
            f'border-radius:20px;padding:5px 14px;font-size:13px;font-weight:600">{sl}{al}</span><br>'
            f'<span style="font-size:11px;color:#64748b">{now_ist.strftime("%d %b %Y %H:%M:%S IST")}</span>'
            f'</div>', unsafe_allow_html=True
        )
    with h3:
        scan_mode = st.selectbox(
            "Mode",
            ["Both BUY + SELL","BUY only","SELL only","Auto (follow market)"],
            index=3, key="scan_mode_select", label_visibility="collapsed",
        )
        st.session_state["scan_mode"] = scan_mode

    cc1, cc2, cc3 = st.columns([2, 2, 2])
    with cc1:
        max_stocks = st.slider("Stocks to scan", 20, 180, st.session_state["max_stocks"], 10, key="ms_sl")
        st.session_state["max_stocks"] = max_stocks
    with cc2:
        min_score = st.slider("Min score", 0, 100, st.session_state["min_score"], 5, key="msc_sl")
        st.session_state["min_score"] = min_score
    with cc3:
        st.markdown("<div style='padding-top:26px'>", unsafe_allow_html=True)
        run_clicked = st.button("\u25b6 Run Scanner", use_container_width=True, type="primary")
        st.markdown("</div>", unsafe_allow_html=True)

    st.divider()
    symbols_all = get_fno_symbols()[:max_stocks]

    # Auto-scan on refresh (skip count=0 which is initial page load)
    if market_open and refresh_count > 0:
        ph = st.empty()
        ph.info(f"\U0001f504 Auto-refresh #${refresh_count} (5-min) u2014 scanning {len(symbols_all)} stocks on 2-min chart...")
        execute_scan(symbols_all, scan_mode, min_score, show_progress=False)
        ph.empty()

    if run_clicked:
        ph = st.empty()
        ph.info(f"\U0001f50d Scanning {len(symbols_all)} stocks...")
        buy_r, sell_r, overall = execute_scan(symbols_all, scan_mode, min_score, show_progress=True)
        ph.empty()
        n_buy   = len([r for r in buy_r  if r.get("signal") in ("BUY","STRONG BUY")])
        n_sell  = len([r for r in sell_r if r.get("signal") in ("SELL","STRONG SELL")])
        n_watch = len([r for r in buy_r+sell_r if r.get("signal")=="WATCH"])
        st.success(f"\u2705 Done \u2014 {n_buy} BUY | {n_sell} SELL | {n_watch} WATCH \u00b7 {datetime.now(IST).strftime('%H:%M:%S IST')}")
        st.rerun()

    tab1, tab2 = st.tabs([
        "\U0001f4e1 Live Scanner",
        f"\U0001f4cb Daily Report ({len(st.session_state.get('daily_log',[]))} signals)"
    ])

    with tab1:
        if st.session_state.get("pulse") is None:
            st.markdown(
                '<div style="background:#111827;border:2px dashed #1e2d5a;border-radius:14px;'
                'padding:80px 24px;text-align:center">'
                '<div style="font-size:56px">\U0001f4e1</div>'
                '<div style="font-size:22px;font-weight:800;color:#f3f4f6;margin:16px 0 8px">TazCard Ready</div>'
                '<div style="font-size:14px;color:#6b7280">Click Run Scanner or wait for auto-refresh (market hours only)</div>'
                '</div>', unsafe_allow_html=True
            )
        else:
            render_market_pulse(st.session_state["pulse"])
            buy_r  = st.session_state.get("buy_results",  [])
            sell_r = st.session_state.get("sell_results", [])
            buy_sigs  = [r for r in buy_r  if r["signal"] in ("STRONG BUY",  "BUY")]
            sell_sigs = [r for r in sell_r if r["signal"] in ("STRONG SELL", "SELL")]
            watch     = [r for r in buy_r+sell_r if r["signal"] == "WATCH"]

            m1,m2,m3,m4,m5 = st.columns(5)
            m1.metric("\U0001f7e2 BUY",        len(buy_sigs))
            m2.metric("\u2b50 Strong BUY", len([r for r in buy_sigs  if r["signal"]=="STRONG BUY"]))
            m3.metric("\U0001f534 SELL",       len(sell_sigs))
            m4.metric("\u2b50 Strong SELL",len([r for r in sell_sigs if r["signal"]=="STRONG SELL"]))
            m5.metric("\U0001f441 Watch",      len(watch))

            if st.session_state.get("scan_time"):
                st.caption(f"Last scan: {st.session_state['scan_time']} \u00b7 Mode: {st.session_state.get('scan_mode','')} \u00b7 Chart: 2-min \u00b7 \u26a0\ufe0f Not financial advice.")

            st.divider()
            col_buy, col_sell, col_watch = st.columns(3)

            with col_buy:
                st.markdown(f'<div class="section-header buy-header">\U0001f7e2 BUY Signals ({len(buy_sigs)})</div>', unsafe_allow_html=True)
                if not buy_sigs:
                    st.markdown('<div style="background:#111827;border:1px solid #1e2d5a;border-radius:8px;padding:20px;text-align:center;color:#6b7280;font-size:13px">No BUY signals</div>', unsafe_allow_html=True)
                else:
                    for r in buy_sigs: render_card(r, "BUY")

            with col_sell:
                st.markdown(f'<div class="section-header sell-header">\U0001f534 SELL Signals ({len(sell_sigs)})</div>', unsafe_allow_html=True)
                if not sell_sigs:
                    st.markdown('<div style="background:#111827;border:1px solid #1e2d5a;border-radius:8px;padding:20px;text-align:center;color:#6b7280;font-size:13px">No SELL signals</div>', unsafe_allow_html=True)
                else:
                    for r in sell_sigs: render_card(r, "SELL")

            with col_watch:
                st.markdown(f'<div class="section-header watch-header">\U0001f441 Watch List ({len(watch)})</div>', unsafe_allow_html=True)
                if not watch:
                    st.markdown('<div style="background:#111827;border:1px solid #1e2d5a;border-radius:8px;padding:20px;text-align:center;color:#6b7280;font-size:13px">No stocks in watch zone</div>', unsafe_allow_html=True)
                else:
                    for r in watch:
                        mode = "BUY" if r in buy_r else "SELL"
                        render_card(r, mode)

    with tab2:
        render_daily_report()


if __name__ == "__main__":
    main()
