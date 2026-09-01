"""
Market Trend Engine — V2
========================
Uses Nifty 50 on 5-MIN chart (same as your Zerodha chart).

3 checks on Nifty 5-min:
  1. EMA 13 > EMA 50          → trend structure bullish
  2. ATR Trailing Stop < price → buy signal active
  3. MACD line > Signal line   → momentum positive

Result:
  2–3 checks pass → BULLISH  → run BUY scan
  0–1 checks pass → BEARISH  → run SELL scan
  1   check pass  → SIDEWAYS → run both scans
"""

from __future__ import annotations
from typing import Optional
import logging
import yfinance as yf

from scanner.indicators import (
    fetch_ohlc,
    calc_ema,
    calc_macd,
    calc_atr_trailing_stop,
    get_close,
)

logger = logging.getLogger(__name__)

NIFTY_TICKER = "^NSEI"

# Advance/Decline sample — 50 Nifty 500 stocks
AD_SAMPLE = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "BHARTIARTL.NS", "SBIN.NS", "BAJFINANCE.NS", "LT.NS", "HCLTECH.NS",
    "WIPRO.NS", "AXISBANK.NS", "MARUTI.NS", "ASIANPAINT.NS", "NTPC.NS",
    "KOTAKBANK.NS", "TITAN.NS", "SUNPHARMA.NS", "POWERGRID.NS", "TATAMOTORS.NS",
    "ADANIENT.NS", "ADANIPORTS.NS", "BAJAJFINSV.NS", "COALINDIA.NS", "ONGC.NS",
    "JSWSTEEL.NS", "HINDALCO.NS", "INDUSINDBK.NS", "TATASTEEL.NS", "ULTRACEMCO.NS",
    "GRASIM.NS", "TECHM.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS",
    "BRITANNIA.NS", "EICHERMOT.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS", "TATACONSUM.NS",
    "ITC.NS", "NESTLEIND.NS", "APOLLOHOSP.NS", "BPCL.NS", "HINDUNILVR.NS",
    "M&M.NS", "SBILIFE.NS", "HDFCLIFE.NS", "TRENT.NS", "ZOMATO.NS",
]


def get_advance_decline() -> dict:
    """
    Fetch latest daily change for AD_SAMPLE stocks.
    Returns advancing / declining / unchanged counts + ratio.
    """
    advancing = declining = unchanged = 0
    try:
        import pandas as pd
        data = yf.download(
            " ".join(AD_SAMPLE),
            period="2d", interval="1d",
            progress=False, auto_adjust=True,
            multi_level_index=False,
        )
        if data.empty:
            return {"advancing": 0, "declining": 0, "unchanged": 0,
                    "ratio": 1.0, "total": 0, "error": True}

        # Handle multi-level columns from batch download
        if isinstance(data.columns, pd.MultiIndex):
            close = data.xs("Close", axis=1, level=0)
        elif "Close" in data.columns:
            close = data[["Close"]]
        else:
            return {"advancing": 0, "declining": 0, "unchanged": 0,
                    "ratio": 1.0, "total": 0, "error": True}

        for col in close.columns:
            series = close[col].dropna()
            if len(series) < 2:
                continue
            chg = float(series.iloc[-1]) - float(series.iloc[-2])
            if chg > 0.01:
                advancing += 1
            elif chg < -0.01:
                declining += 1
            else:
                unchanged += 1

    except Exception as e:
        logger.warning("A/D error: %s", e)
        return {"advancing": 0, "declining": 0, "unchanged": 0,
                "ratio": 1.0, "total": 0, "error": True}

    total = advancing + declining + unchanged
    ratio = round(advancing / declining, 2) if declining > 0 else 9.99
    return {
        "advancing": advancing, "declining": declining,
        "unchanged": unchanged, "total": total,
        "ratio": ratio, "error": False,
    }


def get_nifty_trend() -> dict:
    """
    Check Nifty 50 on 5-MIN chart using EMA 13/50 + ATR Trailing Stop + MACD.
    Same indicators as your Zerodha chart.

    Returns direction: BULLISH / BEARISH / SIDEWAYS
    """
    result = {
        "direction":    "SIDEWAYS",
        "close":        None,
        "ema13":        None,
        "ema50":        None,
        "atr_stop":     None,
        "atr_signal":   None,
        "macd":         None,
        "macd_signal":  None,
        # Individual checks
        "ema_cross_bull":  False,   # EMA13 > EMA50
        "atr_bull":        False,   # ATR stop below price
        "macd_bull":       False,   # MACD line > signal line
        "bull_count":      0,       # 0–3
    }

    try:
        # 5-min Nifty — need enough bars for EMA50 (at least 60 bars)
        df = fetch_ohlc(NIFTY_TICKER, interval="5m", period="5d", min_bars=60)
        if df is None:
            logger.warning("Could not fetch Nifty 5-min data")
            return result

        close = get_close(df)
        ema13 = calc_ema(df, 13)
        ema50 = calc_ema(df, 50)
        macd  = calc_macd(df)
        atr   = calc_atr_trailing_stop(df)

        result["close"] = round(close, 2) if close else None
        result["ema13"] = round(ema13, 2) if ema13 else None
        result["ema50"] = round(ema50, 2) if ema50 else None

        if macd:
            result["macd"]        = round(macd["macd"],   2)
            result["macd_signal"] = round(macd["signal"], 2)
        if atr:
            result["atr_stop"]   = atr["atr_stop"]
            result["atr_signal"] = atr["signal"]

        # ── 3 bullish checks ────────────────────────────────────────────────
        bull = 0

        # 1. EMA crossover: EMA13 > EMA50
        if ema13 and ema50 and ema13 > ema50:
            result["ema_cross_bull"] = True
            bull += 1

        # 2. ATR Trailing Stop below price (green dots = buy signal)
        if atr and close and atr["signal"] == "buy":
            result["atr_bull"] = True
            bull += 1

        # 3. MACD line above signal line
        if macd and macd["macd"] > macd["signal"]:
            result["macd_bull"] = True
            bull += 1

        result["bull_count"] = bull

        # ── Direction decision ───────────────────────────────────────────────
        if bull >= 2:
            result["direction"] = "BULLISH"
        elif bull == 0:
            result["direction"] = "BEARISH"
        else:
            result["direction"] = "SIDEWAYS"

    except Exception as e:
        logger.warning("Nifty trend error: %s", e)

    return result


def get_market_pulse() -> dict:
    """
    Combined: Nifty 5-min trend + Advance/Decline ratio.
    Overall direction gates which scanner runs.
    """
    nifty = get_nifty_trend()
    ad    = get_advance_decline()

    nifty_dir = nifty.get("direction", "SIDEWAYS")

    # A/D ratio confirms or softens direction
    ad_bull = ad.get("ratio", 1.0) >= 1.2   # more stocks advancing
    ad_bear = ad.get("ratio", 1.0) <= 0.8   # more stocks declining

    if nifty_dir == "BULLISH" and (ad_bull or not ad_bear):
        overall = "BULLISH"
    elif nifty_dir == "BEARISH" and (ad_bear or not ad_bull):
        overall = "BEARISH"
    else:
        overall = "SIDEWAYS"

    return {
        "overall": overall,
        "nifty":   nifty,
        "ad":      ad,
        "ad_bull": ad_bull,
        "ad_bear": ad_bear,
    }
