"""
SELL Scanner - V2
=================
Exact mirror of BUY scanner. 5 conditions on 2-MIN chart:

  1. EMA 13 < EMA 50           bearish crossover
  2. Close  < EMA 13            price below fast EMA
  3. ATR Trailing Stop > Close  dots above price (sell active)
  4. MACD line < Signal line    momentum bearish
  5. MACD Histogram < 0         momentum growing bearish

Score: 5 x 20 pts = 100
  100  STRONG SELL  (all 5)
   80  SELL         (4 of 5)
   60  WATCH        (3 of 5)
  <=40 SKIP

SL  = ATR Trailing Stop value (above price for short)
T1  = entry - (sl - entry) x 1.0    1:1 R/R downside
T2  = entry - (sl - entry) x 2.0    1:2 R/R downside
"""

from __future__ import annotations
import logging
from scanner.indicators import (
    fetch_ohlc, fetch_daily_change,
    calc_ema, calc_macd, calc_atr_trailing_stop,
    get_close, get_change_pct,
)

logger = logging.getLogger(__name__)

PERIOD_2M = "60d"


def scan_sell(symbol: str) -> dict:
    """
    Run SELL/SHORT scanner on a single NSE F&O symbol.
    Uses 2-min chart — exact mirror of buy_scanner.
    """
    result = {
        "symbol":      symbol,
        "signal":      "SKIP",
        "score":       0,
        "close":       None,
        "change_pct":  None,
        "entry":       None,
        "sl":          None,
        "sl_pct":      None,
        "target1":     None,
        "target2":     None,
        "risk_reward": None,
        "conditions":  {},
        "indicators":  {},
        "error":       None,
    }

    ticker = f"{symbol}.NS"

    try:
        df = fetch_ohlc(ticker, interval="2m", period=PERIOD_2M, min_bars=60)

        if df is None:
            result["error"] = "Insufficient 2m data"
            return result

        close = get_close(df)
        if not close:
            result["error"] = "No price data"
            return result

        result["close"]      = round(close, 2)
        result["change_pct"] = fetch_daily_change(ticker) or get_change_pct(df)

        ema13 = calc_ema(df, 13)
        ema50 = calc_ema(df, 50)
        macd  = calc_macd(df)
        atr   = calc_atr_trailing_stop(df)

        result["indicators"]["ema13"]     = round(ema13, 2)              if ema13 else None
        result["indicators"]["ema50"]     = round(ema50, 2)              if ema50 else None
        result["indicators"]["macd_line"] = round(macd["macd"],    2)    if macd  else None
        result["indicators"]["macd_sig"]  = round(macd["signal"],  2)    if macd  else None
        result["indicators"]["macd_hist"] = round(macd["histogram"],2)   if macd  else None
        result["indicators"]["atr_stop"]  = atr["atr_stop"]              if atr   else None

        # Condition 1: EMA 13 < EMA 50
        c1 = bool(ema13 and ema50 and ema13 < ema50)
        result["conditions"]["ema13_lt_ema50"] = c1

        # Condition 2: Close < EMA 13
        c2 = bool(ema13 and close < ema13)
        result["conditions"]["close_lt_ema13"] = c2

        # Condition 3: ATR Trailing Stop above price
        c3 = bool(atr and atr["signal"] == "sell")
        result["conditions"]["atr_stop_above"] = c3

        # Condition 4: MACD line < Signal line
        c4 = bool(macd and macd["macd"] < macd["signal"])
        result["conditions"]["macd_line_lt_signal"] = c4

        # Condition 5: MACD Histogram negative
        c5 = bool(macd and macd["histogram"] < 0)
        result["conditions"]["macd_hist_negative"] = c5

        score = sum([c1, c2, c3, c4, c5]) * 20
        result["score"] = score

        if score == 100:
            result["signal"] = "STRONG SELL"
        elif score == 80:
            result["signal"] = "SELL"
        elif score == 60:
            result["signal"] = "WATCH"
        else:
            result["signal"] = "SKIP"

        if result["signal"] in ("STRONG SELL", "SELL") and atr:
            sl   = atr["atr_stop"]
            risk = sl - close
            if risk > 0:
                result["entry"]       = round(close, 2)
                result["sl"]          = round(sl, 2)
                result["sl_pct"]      = round(risk / close * 100, 2)
                result["target1"]     = round(close - risk * 1.0, 2)
                result["target2"]     = round(close - risk * 2.0, 2)
                result["risk_reward"] = "1:2"

    except Exception as e:
        logger.warning("SELL scan error %s: %s", symbol, e)
        result["error"] = str(e)

    return result