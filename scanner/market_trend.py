"""
Market Trend Engine — checks Nifty 50 direction using:
1. Advance / Decline ratio from Nifty 500 sample
2. Nifty 30-min: EMA 20, MACD (12,26,9)
3. Nifty 30-min: ATR Trailing Stop
"""

import yfinance as yf
import pandas as pd
import logging
from scanner.indicators import (
    fetch_ohlc, calc_ema, calc_macd, calc_atr_trailing_stop, get_close
)

logger = logging.getLogger(__name__)

# Nifty 50 index ticker
NIFTY_TICKER = "^NSEI"

# Sample of 50 Nifty 500 stocks for A/D calculation (representative)
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
    Fetch latest 1-day change for sample stocks.
    Returns advancing, declining, unchanged counts and ratio.
    """
    advancing = declining = unchanged = 0
    try:
        data = yf.download(
            " ".join(AD_SAMPLE),
            period="2d", interval="1d",
            progress=False, auto_adjust=True
        )
        if data.empty:
            return {"advancing": 0, "declining": 0, "unchanged": 0, "ratio": 1.0, "error": True}

        close = data["Close"] if "Close" in data.columns else data.xs("Close", axis=1, level=0)
        if close.columns.nlevels > 1:
            close = close.droplevel(0, axis=1)

        for col in close.columns:
            series = close[col].dropna()
            if len(series) < 2:
                continue
            chg = series.iloc[-1] - series.iloc[-2]
            if chg > 0.01:
                advancing += 1
            elif chg < -0.01:
                declining += 1
            else:
                unchanged += 1

    except Exception as e:
        logger.warning("A/D calculation error: %s", e)
        return {"advancing": 0, "declining": 0, "unchanged": 0, "ratio": 1.0, "error": True}

    total = advancing + declining + unchanged
    ratio = round(advancing / declining, 2) if declining > 0 else 9.99
    return {
        "advancing": advancing,
        "declining": declining,
        "unchanged": unchanged,
        "total":     total,
        "ratio":     ratio,
        "error":     False,
    }


def get_nifty_trend() -> dict:
    """
    Check Nifty 50 on 30-min chart.
    Returns trend direction and all indicator values.
    """
    result = {
        "direction":   "SIDEWAYS",   # BULLISH / BEARISH / SIDEWAYS
        "close":       None,
        "ema20":       None,
        "macd":        None,
        "atr_stop":    None,
        "atr_signal":  None,
        "above_ema20": False,
        "macd_bull":   False,
        "atr_bull":    False,
        "bull_count":  0,            # 0-3 how many bullish checks pass
    }

    try:
        df = fetch_ohlc(NIFTY_TICKER, interval="30m", period="5d")
        if df is None:
            return result

        close  = get_close(df)
        ema20  = calc_ema(df, 20)
        macd   = calc_macd(df)
        atr    = calc_atr_trailing_stop(df)

        result["close"]  = round(close, 2) if close else None
        result["ema20"]  = round(ema20, 2) if ema20 else None

        if macd:
            result["macd"] = round(macd["macd"], 2)
        if atr:
            result["atr_stop"]   = atr["atr_stop"]
            result["atr_signal"] = atr["signal"]

        # Bullish checks
        bull = 0
        if close and ema20 and close > ema20:
            result["above_ema20"] = True
            bull += 1
        if macd and macd["macd"] and macd["signal"] and macd["macd"] > macd["signal"]:
            result["macd_bull"] = True
            bull += 1
        if atr and atr["signal"] == "buy":
            result["atr_bull"] = True
            bull += 1

        result["bull_count"] = bull

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
    Combined market sentiment: A/D ratio + Nifty trend.
    Returns overall market direction and all sub-indicators.
    """
    ad     = get_advance_decline()
    nifty  = get_nifty_trend()

    # Combine A/D ratio with Nifty technical direction
    ad_bull = ad.get("ratio", 1.0) >= 1.2   # More advancing than declining
    ad_bear = ad.get("ratio", 1.0) <= 0.8   # More declining than advancing

    nifty_dir = nifty.get("direction", "SIDEWAYS")

    # Overall direction
    if nifty_dir == "BULLISH" and (ad_bull or not ad_bear):
        overall = "BULLISH"
    elif nifty_dir == "BEARISH" and (ad_bear or not ad_bull):
        overall = "BEARISH"
    else:
        overall = "SIDEWAYS"

    return {
        "overall":   overall,
        "nifty":     nifty,
        "ad":        ad,
        "ad_bull":   ad_bull,
        "ad_bear":   ad_bear,
    }
