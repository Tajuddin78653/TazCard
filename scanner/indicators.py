"""
Technical indicator calculations using pure pandas + numpy.
No pandas-ta dependency — works reliably on Streamlit Cloud.
Covers: EMA, Bollinger Bands, MACD, ATR Trailing Stop.
"""

import pandas as pd
import numpy as np
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
    """EMA using pandas ewm."""
    try:
        ema = df["Close"].ewm(span=length, adjust=False).mean()
        return float(ema.iloc[-1])
    except Exception:
        return None


def calc_bb(df: pd.DataFrame, length: int = 20, std: float = 2.0) -> dict | None:
    """Bollinger Bands using rolling mean + std."""
    try:
        close  = df["Close"]
        mid    = close.rolling(length).mean()
        sigma  = close.rolling(length).std(ddof=0)
        upper  = mid + std * sigma
        lower  = mid - std * sigma
        return {
            "upper": float(upper.iloc[-1]),
            "mid":   float(mid.iloc[-1]),
            "lower": float(lower.iloc[-1]),
        }
    except Exception:
        return None


def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> dict | None:
    """MACD using EWM."""
    try:
        close      = df["Close"]
        ema_fast   = close.ewm(span=fast,   adjust=False).mean()
        ema_slow   = close.ewm(span=slow,   adjust=False).mean()
        macd_line  = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram  = macd_line - signal_line
        return {
            "macd":      float(macd_line.iloc[-1]),
            "signal":    float(signal_line.iloc[-1]),
            "histogram": float(histogram.iloc[-1]),
        }
    except Exception:
        return None


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series | None:
    """Average True Range."""
    try:
        high  = df["High"]
        low   = df["Low"]
        close = df["Close"]
        tr    = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr   = tr.ewm(span=period, adjust=False).mean()
        return atr
    except Exception:
        return None


def calc_atr_trailing_stop(df: pd.DataFrame, period: int = 14, multiplier: float = 3.0) -> dict | None:
    """
    ATR Trailing Stop — matches the indicator on your Zerodha chart.
    Returns: { "atr_stop": float, "signal": "buy" | "sell" }
    """
    try:
        close    = df["Close"].values
        atr_vals = calc_atr(df, period)
        if atr_vals is None:
            return None
        atr = atr_vals.values

        stop  = np.zeros(len(close))
        trend = np.ones(len(close))   # 1=up, -1=down

        for i in range(1, len(close)):
            if np.isnan(atr[i]):
                stop[i]  = stop[i - 1]
                trend[i] = trend[i - 1]
                continue

            up_stop   = close[i] - multiplier * atr[i]
            down_stop = close[i] + multiplier * atr[i]

            if trend[i - 1] == 1:
                new_stop = max(up_stop, stop[i - 1]) if close[i] > stop[i - 1] else down_stop
                trend[i] = 1 if close[i] > new_stop else -1
            else:
                new_stop = min(down_stop, stop[i - 1]) if close[i] < stop[i - 1] else up_stop
                trend[i] = -1 if close[i] < new_stop else 1
            stop[i] = new_stop

        signal = "buy" if close[-1] > stop[-1] else "sell"
        return {"atr_stop": round(float(stop[-1]), 2), "signal": signal}
    except Exception:
        return None


def get_close(df: pd.DataFrame) -> float | None:
    try:
        return float(df["Close"].iloc[-1])
    except Exception:
        return None


def get_change_pct(df: pd.DataFrame) -> float | None:
    try:
        if len(df) < 2:
            return None
        prev = float(df["Close"].iloc[-2])
        curr = float(df["Close"].iloc[-1])
        return round((curr - prev) / prev * 100, 2)
    except Exception:
        return None
