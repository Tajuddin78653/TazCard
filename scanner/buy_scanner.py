"""
BUY Scanner — your exact Chartink conditions:
  1. 5-min  EMA(5)  > EMA(200)           ← fast > slow = uptrend
  2. 30-min Close   > EMA(20)             ← above medium trend
  3. 30-min Close   > Upper BB(20,2)      ← 30-min BB breakout
  4. 2-hour Close   > Upper BB(20,2)      ← higher TF BB breakout

All 4 must pass for a BUY signal.
Score 0–100 based on conditions + ATR + MACD confirmation.
"""

import logging
from scanner.indicators import (
    fetch_ohlc, calc_ema, calc_bb, calc_macd,
    calc_atr_trailing_stop, get_close, get_change_pct
)

logger = logging.getLogger(__name__)


def scan_buy(symbol: str) -> dict:
    """
    Run BUY scanner on a single F&O symbol.
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
        # ── Fetch OHLC for 3 timeframes ────────────────────────────────────
        df_5m   = fetch_ohlc(ticker, interval="5m",  period="5d")
        df_30m  = fetch_ohlc(ticker, interval="30m", period="10d")
        df_2h   = fetch_ohlc(ticker, interval="2h",  period="30d")

        if df_5m is None or df_30m is None or df_2h is None:
            result["error"] = "Insufficient data"
            return result

        close = get_close(df_5m)
        if not close:
            result["error"] = "No price data"
            return result

        result["close"]      = round(close, 2)
        result["change_pct"] = get_change_pct(df_5m)

        # ── Condition 1: 5-min EMA(5) > EMA(200) ───────────────────────────
        ema5_5m   = calc_ema(df_5m, 5)
        ema200_5m = calc_ema(df_5m, 200)
        cond1 = bool(ema5_5m and ema200_5m and ema5_5m > ema200_5m)
        result["conditions"]["5m_ema5_gt_ema200"]  = cond1
        result["indicators"]["ema5_5m"]            = round(ema5_5m,   2) if ema5_5m   else None
        result["indicators"]["ema200_5m"]          = round(ema200_5m, 2) if ema200_5m else None

        # ── Condition 2: 30-min Close > EMA(20) ────────────────────────────
        close_30m = get_close(df_30m)
        ema20_30m = calc_ema(df_30m, 20)
        cond2 = bool(close_30m and ema20_30m and close_30m > ema20_30m)
        result["conditions"]["30m_close_gt_ema20"] = cond2
        result["indicators"]["ema20_30m"]          = round(ema20_30m, 2) if ema20_30m else None

        # ── Condition 3: 30-min Close > Upper BB(20,2) ─────────────────────
        bb_30m  = calc_bb(df_30m, 20, 2.0)
        cond3   = bool(close_30m and bb_30m and close_30m > bb_30m["upper"])
        result["conditions"]["30m_close_gt_upper_bb"] = cond3
        result["indicators"]["bb_upper_30m"] = round(bb_30m["upper"], 2) if bb_30m else None
        result["indicators"]["bb_lower_30m"] = round(bb_30m["lower"], 2) if bb_30m else None

        # ── Condition 4: 2-hour Close > Upper BB(20,2) ─────────────────────
        close_2h = get_close(df_2h)
        bb_2h    = calc_bb(df_2h, 20, 2.0)
        cond4    = bool(close_2h and bb_2h and close_2h > bb_2h["upper"])
        result["conditions"]["2h_close_gt_upper_bb"] = cond4
        result["indicators"]["bb_upper_2h"] = round(bb_2h["upper"], 2) if bb_2h else None

        # ── Bonus: MACD confirmation on 30-min ─────────────────────────────
        macd_30m = calc_macd(df_30m)
        macd_bull = bool(
            macd_30m and
            macd_30m["macd"] and macd_30m["signal"] and
            macd_30m["macd"] > macd_30m["signal"] and
            macd_30m["histogram"] and macd_30m["histogram"] > 0
        )
        result["conditions"]["30m_macd_bullish"] = macd_bull
        result["indicators"]["macd_30m"]  = round(macd_30m["macd"], 2)      if macd_30m else None
        result["indicators"]["macd_hist"] = round(macd_30m["histogram"], 2) if macd_30m else None

        # ── Bonus: ATR Trailing Stop on 30-min ─────────────────────────────
        atr_30m  = calc_atr_trailing_stop(df_30m)
        atr_bull = bool(atr_30m and atr_30m["signal"] == "buy")
        result["conditions"]["30m_atr_buy"] = atr_bull
        result["indicators"]["atr_stop_30m"] = atr_30m["atr_stop"] if atr_30m else None

        # ── Score ───────────────────────────────────────────────────────────
        score = 0
        if cond1:      score += 20  # 5-min EMA trend
        if cond2:      score += 20  # 30-min above EMA
        if cond3:      score += 25  # 30-min BB breakout (most important)
        if cond4:      score += 25  # 2-hour BB breakout (most important)
        if macd_bull:  score += 5   # MACD bonus
        if atr_bull:   score += 5   # ATR bonus
        result["score"] = score

        # ── Signal label ────────────────────────────────────────────────────
        all_4 = cond1 and cond2 and cond3 and cond4
        if all_4 and score >= 90:
            result["signal"] = "STRONG BUY"
        elif all_4:
            result["signal"] = "BUY"
        elif score >= 60:
            result["signal"] = "WATCH"
        else:
            result["signal"] = "SKIP"

        # ── Entry / SL / Target (only for BUY signals) ─────────────────────
        if result["signal"] in ("STRONG BUY", "BUY") and close:
            sl_level = atr_30m["atr_stop"] if atr_30m else round(close * 0.985, 2)
            result["entry"]   = round(close, 2)
            result["sl"]      = round(sl_level, 2)
            result["target1"] = round(close * 1.005, 2)   # +0.5%
            result["target2"] = round(close * 1.010, 2)   # +1.0%

    except Exception as e:
        logger.warning("BUY scan error %s: %s", symbol, e)
        result["error"] = str(e)

    return result
