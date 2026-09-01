"""
SELL Scanner — mirror of BUY conditions for bearish market:
  1. 5-min  EMA(5)  < EMA(200)           ← fast < slow = downtrend
  2. 30-min Close   < EMA(20)             ← below medium trend
  3. 30-min Close   < Lower BB(20,2)      ← 30-min BB breakdown
  4. 2-hour Close   < Lower BB(20,2)      ← higher TF BB breakdown

All 4 must pass for a SELL/SHORT signal.

Period notes:
  - 5m  period="60d"  → yfinance max for 5m intraday; gives ~2250 bars (well above EMA200 need)
  - 30m period="60d"  → gives ~480 bars; plenty for EMA20 + BB(20) + MACD
  - 2h  period="730d" → gives ~650 bars; needed for BB(20) on 2h
"""

import logging
from scanner.indicators import (
    fetch_ohlc, fetch_daily_change, calc_ema, calc_bb, calc_macd,
    calc_atr_trailing_stop, get_close, get_change_pct
)

logger = logging.getLogger(__name__)

# yfinance period limits per interval
PERIOD_5M  = "60d"
PERIOD_30M = "60d"
PERIOD_2H  = "730d"


def scan_sell(symbol: str) -> dict:
    """
    Run SELL/SHORT scanner on a single F&O symbol.
    Returns full result dict including pass/fail per condition and score.
    """
    result = {
        "symbol":       symbol,
        "signal":       "SKIP",
        "score":        0,
        "close":        None,
        "change_pct":   None,
        "entry":        None,
        "sl":           None,
        "target1":      None,
        "target2":      None,
        "conditions":   {},
        "indicators":   {},
        "error":        None,
    }

    ticker = f"{symbol}.NS"

    try:
        # ── Fetch OHLC for 3 timeframes ────────────────────────────────────────
        df_5m  = fetch_ohlc(ticker, interval="5m",  period=PERIOD_5M,  min_bars=210)
        df_30m = fetch_ohlc(ticker, interval="30m", period=PERIOD_30M, min_bars=35)
        df_2h  = fetch_ohlc(ticker, interval="2h",  period=PERIOD_2H,  min_bars=25)

        if df_5m is None or df_30m is None or df_2h is None:
            missing = []
            if df_5m  is None: missing.append("5m")
            if df_30m is None: missing.append("30m")
            if df_2h  is None: missing.append("2h")
            result["error"] = f"Insufficient data ({', '.join(missing)})"
            return result

        close = get_close(df_5m)
        if not close:
            result["error"] = "No price data"
            return result

        result["close"]      = round(close, 2)
        result["change_pct"] = fetch_daily_change(ticker) or get_change_pct(df_5m)

        # ── Condition 1: 5-min EMA(5) < EMA(200) ───────────────────────────────
        ema5_5m   = calc_ema(df_5m, 5)
        ema200_5m = calc_ema(df_5m, 200)
        cond1 = bool(ema5_5m and ema200_5m and ema5_5m < ema200_5m)
        result["conditions"]["5m_ema5_lt_ema200"] = cond1
        result["indicators"]["ema5_5m"]           = round(ema5_5m,   2) if ema5_5m   else None
        result["indicators"]["ema200_5m"]         = round(ema200_5m, 2) if ema200_5m else None

        # ── Condition 2: 30-min Close < EMA(20) ────────────────────────────────
        close_30m = get_close(df_30m)
        ema20_30m = calc_ema(df_30m, 20)
        cond2 = bool(close_30m and ema20_30m and close_30m < ema20_30m)
        result["conditions"]["30m_close_lt_ema20"] = cond2
        result["indicators"]["ema20_30m"]          = round(ema20_30m, 2) if ema20_30m else None

        # ── Condition 3: 30-min Close < Lower BB(20,2) ─────────────────────────
        bb_30m = calc_bb(df_30m, 20, 2.0)
        cond3  = bool(close_30m and bb_30m and close_30m < bb_30m["lower"])
        result["conditions"]["30m_close_lt_lower_bb"] = cond3
        result["indicators"]["bb_upper_30m"] = round(bb_30m["upper"], 2) if bb_30m else None
        result["indicators"]["bb_lower_30m"] = round(bb_30m["lower"], 2) if bb_30m else None

        # ── Condition 4: 2-hour Close < Lower BB(20,2) ─────────────────────────
        close_2h = get_close(df_2h)
        bb_2h    = calc_bb(df_2h, 20, 2.0)
        cond4    = bool(close_2h and bb_2h and close_2h < bb_2h["lower"])
        result["conditions"]["2h_close_lt_lower_bb"] = cond4
        result["indicators"]["bb_lower_2h"] = round(bb_2h["lower"], 2) if bb_2h else None

        # ── Bonus: MACD bearish on 30-min ──────────────────────────────────────
        macd_30m  = calc_macd(df_30m)
        macd_bear = bool(
            macd_30m and
            macd_30m["macd"] < macd_30m["signal"] and
            macd_30m["histogram"] < 0
        )
        result["conditions"]["30m_macd_bearish"] = macd_bear
        result["indicators"]["macd_30m"]  = round(macd_30m["macd"],      2) if macd_30m else None
        result["indicators"]["macd_hist"] = round(macd_30m["histogram"],  2) if macd_30m else None

        # ── Bonus: ATR Trailing Stop sell signal ────────────────────────────────
        atr_30m  = calc_atr_trailing_stop(df_30m)
        atr_bear = bool(atr_30m and atr_30m["signal"] == "sell")
        result["conditions"]["30m_atr_sell"]  = atr_bear
        result["indicators"]["atr_stop_30m"]  = atr_30m["atr_stop"] if atr_30m else None

        # ── Score ───────────────────────────────────────────────────────────────
        score = 0
        if cond1:      score += 20
        if cond2:      score += 20
        if cond3:      score += 25
        if cond4:      score += 25
        if macd_bear:  score +=  5
        if atr_bear:   score +=  5
        result["score"] = score

        # ── Signal label ────────────────────────────────────────────────────────
        all_4 = cond1 and cond2 and cond3 and cond4
        if all_4 and score >= 90:
            result["signal"] = "STRONG SELL"
        elif all_4:
            result["signal"] = "SELL"
        elif score >= 40:
            result["signal"] = "WATCH"
        else:
            result["signal"] = "SKIP"

        # ── Entry / SL / Target ─────────────────────────────────────────────────
        if result["signal"] in ("STRONG SELL", "SELL") and close:
            sl_level = atr_30m["atr_stop"] if atr_30m else round(close * 1.015, 2)
            result["entry"]   = round(close, 2)
            result["sl"]      = round(sl_level, 2)       # SL ABOVE entry for short
            result["target1"] = round(close * 0.995, 2)  # -0.5%
            result["target2"] = round(close * 0.990, 2)  # -1.0%

    except Exception as e:
        logger.warning("SELL scan error %s: %s", symbol, e)
        result["error"] = str(e)

    return result
