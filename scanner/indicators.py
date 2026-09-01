"""
Technical indicator calculations using pandas-ta.
Covers EMA, Bollinger Bands, MACD, ATR Trailing Stop.
"""

import pandas as pd
import pandas_ta as ta
import yfinance as yf
import logging

logger = logging.getLogger(__name__)


def fetch_ohlc(ticker: str, interval: str, period: str) -> pd.DataFrame | None:
    """Fetch OHLC data from yfinance. Returns None on failure."""
    try:
        df = yf.download(ticker, interval=interval, period=period,
                         progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 30:
            return None
        if df.columns.nlevels > 1:
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.dropna(how="all", inplace=True)
        return df
    except Exception as e:
        logger.debug("fetch_ohlc %s %s: %s", ticker, interval, e)
        return None


def calc_ema(df: pd.DataFrame, length: int) -> float | None:
    """Return latest EMA value."""
    try:
        ema = ta.ema(df["Close"], length=length)
        if ema is None or ema.empty:
            return None
        return float(ema.iloc[-1])
    except Exception:
        return None


def calc_bb(df: pd.DataFrame, length: int = 20, std: float = 2.0) -> dict | None:
    """Return latest Bollinger Band values: upper, mid, lower."""
    try:
        bb = ta.bbands(df["Close"], length=length, std=std)
        if bb is None or bb.empty:
            return None
        upper_col = [c for c in bb.columns if "BBU" in c]
        lower_col = [c for c in bb.columns if "BBL" in c]
        mid_col   = [c for c in bb.columns if "BBM" in c]
        if not upper_col:
            return None
        return {
            "upper": float(bb[upper_col[0]].iloc[-1]),
            "mid":   float(bb[mid_col[0]].iloc[-1])   if mid_col   else None,
            "lower": float(bb[lower_col[0]].iloc[-1]) if lower_col else None,
        }
    except Exception:
        return None


def calc_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> dict | None:
    """Return latest MACD line, signal line, histogram."""
    try:
        macd = ta.macd(df["Close"], fast=fast, slow=slow, signal=signal)
        if macd is None or macd.empty:
            return None
        macd_col = [c for c in macd.columns if c.startswith("MACD_")]
        sig_col  = [c for c in macd.columns if c.startswith("MACDs_")]
        hist_col = [c for c in macd.columns if c.startswith("MACDh_")]
        if not macd_col:
            return None
        return {
            "macd":      float(macd[macd_col[0]].iloc[-1]),
            "signal":    float(macd[sig_col[0]].iloc[-1])  if sig_col  else None,
            "histogram": float(macd[hist_col[0]].iloc[-1]) if hist_col else None,
        }
    except Exception:
        return None


def calc_atr_trailing_stop(df: pd.DataFrame, period: int = 14, multiplier: float = 3.0) -> dict | None:
    """
    ATR Trailing Stop — like the one on your Zerodha chart.
    Returns: { "atr_stop": float, "signal": "buy" | "sell" }
    Buy  signal = price above ATR stop (green dots below price)
    Sell signal = price below ATR stop (red dots above price)
    """
    try:
        atr = ta.atr(df["High"], df["Low"], df["Close"], length=period)
        if atr is None or atr.empty:
            return None
        close      = df["Close"]
        atr_vals   = atr
        stop       = close.copy() * 0
        trend      = pd.Series(1, index=close.index)  # 1=up, -1=down

        for i in range(1, len(close)):
            prev_stop  = stop.iloc[i - 1]
            prev_close = close.iloc[i - 1]
            curr_close = close.iloc[i]
            curr_atr   = atr_vals.iloc[i]

            if pd.isna(curr_atr):
                stop.iloc[i] = prev_stop
                trend.iloc[i] = trend.iloc[i - 1]
                continue

            up_stop   = curr_close - multiplier * curr_atr
            down_stop = curr_close + multiplier * curr_atr

            if trend.iloc[i - 1] == 1:
                new_stop = max(up_stop, prev_stop) if curr_close > prev_stop else down_stop
                trend.iloc[i] = 1 if curr_close > new_stop else -1
            else:
                new_stop = min(down_stop, prev_stop) if curr_close < prev_stop else up_stop
                trend.iloc[i] = -1 if curr_close < new_stop else 1

            stop.iloc[i] = new_stop

        latest_stop  = float(stop.iloc[-1])
        latest_close = float(close.iloc[-1])
        signal       = "buy" if latest_close > latest_stop else "sell"
        return {"atr_stop": round(latest_stop, 2), "signal": signal}
    except Exception:
        return None


def get_close(df: pd.DataFrame) -> float | None:
    """Return latest close price."""
    try:
        return float(df["Close"].iloc[-1])
    except Exception:
        return None


def get_change_pct(df: pd.DataFrame) -> float | None:
    """Return % change from previous close."""
    try:
        if len(df) < 2:
            return None
        prev  = float(df["Close"].iloc[-2])
        curr  = float(df["Close"].iloc[-1])
        return round((curr - prev) / prev * 100, 2)
    except Exception:
        return None
