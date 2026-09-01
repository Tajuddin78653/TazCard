"""
BUY Scanner — V2
================
5 conditions on 5-MIN chart only (matches your Zerodha setup):

  1. EMA 13 > EMA 50          → bullish crossover (trend structure)
  2. Close  > EMA 13           → price above fast EMA
  3. ATR Trailing Stop < Close → green dots below price (buy active)
  4. MACD line > Signal line   → momentum bullish
  5. MACD Histogram > 0        → momentum growing (not just crossed)

Score: 5 × 20 pts = 100
  100 → STRONG BUY  (all 5)
   80 → BUY         (4 of 5)
   60 → WATCH       (3 of 5)
  ≤40 → SKIP

SL  = ATR Trailing Stop value (dynamic, matches Zerodha green dot)
T1  = entry + (entry − sl) × 1.0   → 1:1 R/R
T2  = entry + (entry − sl) × 2.0   → 1:2 R/R
"""

from __future__ import annotations
import logging
from scanner.indicators import (
    fetch_ohlc, fetch_daily_change,
    calc_ema, calc_macd, calc_atr_trailing_stop,
    get_close, get_change_pct,
)

logger = logging.getLogger(__name__)

# 5-min data: period="60d" gives ~2250 bars — enough for EMA50 and ATR
PERIOD_5M = "60d"


def scan_buy(symbol: str) -> dict:
    """
    Run BUY scanner on a single NSE F&O symbol.
    Uses 5-min chart only — same as Zerodha Kite chart.
    """
    result = {
        "symbol":     symbol,
        "signal":     "SKIP",
        "score":      0,
        "close":      None,
        "change_pct": None,
        "entry":      None,
        "sl":         None,
        "sl_pct":     None,
        "target1":    None,
        "target2":    None,
        "risk_reward": None,
        "conditions": {},
        "indicators": {},
        "error":      None,
    }

    ticker = f"{symbol}.NS"

    try:
        # ── Fetch 5-min OHLC ────────────────────────────────────────────────
        # Need min 60 bars for EMA50; 60d gives ~2250 bars
        df = fetch_ohlc(ticker, interval="5m", period=PERIOD_5M, min_bars=60)

        if df is None:
            result["error"] = "Insufficient 5m data"
            return result

        close = get_close(df)
        if not close:
            result["error"] = "No price data"
            return result

        result["close"]      = round(close, 2)
        result["change_pct"] = fetch_daily_change(ticker) or get_change_pct(df)

        # ── Indicator calculations ───────────────────────────────────────────
        ema13 = calc_ema(df, 13)
        ema50 = calc_ema(df, 50)
        macd  = calc_macd(df)
        atr   = calc_atr_trailing_stop(df)

        # Store raw indicator values for display
        result["indicators"]["ema13"]      = round(ema13, 2)        if ema13 else None
        result["indicators"]["ema50"]      = round(ema50, 2)        if ema50 else None
        result["indicators"]["macd_line"]  = round(macd["macd"], 2) if macd  else None
        result["indicators"]["macd_sig"]   = round(macd["signal"],2) if macd  else None
        result["indicators"]["macd_hist"]  = round(macd["histogram"],2) if macd else None
        result["indicators"]["atr_stop"]   = atr["atr_stop"]        if atr   else None

        # ── Condition 1: EMA 13 > EMA 50 (bullish crossover) ────────────────
        c1 = bool(ema13 and ema50 and ema13 > ema50)
        result["conditions"]["ema13_gt_ema50"] = c1

        # ── Condition 2: Close > EMA 13 (price above fast EMA) ──────────────
        c2 = bool(ema13 and close > ema13)
        result["conditions"]["close_gt_ema13"] = c2

        # ── Condition 3: ATR Trailing Stop below price (green dots) ──────────
        c3 = bool(atr and atr["signal"] == "buy")
        result["conditions"]["atr_stop_below"] = c3

        # ── Condition 4: MACD line > Signal line ────────────────────────────
        c4 = bool(macd and macd["macd"] > macd["signal"])
        result["conditions"]["macd_line_gt_signal"] = c4

        # ── Condition 5: MACD Histogram positive (momentum growing) ──────────
        c5 = bool(macd and macd["histogram"] > 0)
        result["conditions"]["macd_hist_positive"] = c5

        # ── Score ────────────────────────────────────────────────────────────
        score = sum([c1, c2, c3, c4, c5]) * 20
        result["score"] = score

        # ── Signal label ─────────────────────────────────────────────────────
        if score == 100:
            result["signal"] = "STRONG BUY"
        elif score == 80:
            result["signal"] = "BUY"
        elif score == 60:
            result["signal"] = "WATCH"
        else:
            result["signal"] = "SKIP"

        # ── Entry / SL / Targets (only for actionable signals) ───────────────
        if result["signal"] in ("STRONG BUY", "BUY") and atr:
            sl     = atr["atr_stop"]          # ATR Trailing Stop = dynamic SL
            risk   = close - sl               # risk per unit
            if risk > 0:
                t1 = round(close + risk * 1.0, 2)   # 1:1 R/R
                t2 = round(close + risk * 2.0, 2)   # 1:2 R/R
                result["entry"]      = round(close, 2)
                result["sl"]         = round(sl, 2)
                result["sl_pct"]     = round(risk / close * 100, 2)
                result["target1"]    = t1
                result["target2"]    = t2
                result["risk_reward"] = "1:2"

    except Exception as e:
        logger.warning("BUY scan error %s: %s", symbol, e)
        result["error"] = str(e)

    return result
