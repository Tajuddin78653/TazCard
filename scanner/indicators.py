"""
Technical indicator calculations using pure pandas + numpy.
No pandas-ta dependency — works reliably on Streamlit Cloud.
Covers: EMA, Bollinger Bands, MACD, ATR Trailing Stop.
"""

from __future__ import annotations
from typing import Optional
import pandas as pd
import numpy as np
import yfinance as yf
import logging

logger = logging.getLogger(__name__)


def fetch_ohlc(ticker: str, interval: str, period: str, min_bars: int = 30) -> Optional[pd.DataFrame]:
    """
    Fetch OHLC data from yfinance. Returns None on failure.
    min_bars: minimum number of rows required (default 30, set higher for EMA200).
    """
    try:
        df = yf.download(
            ticker,
            interval=interval,
            period=period,
            progress=False,
            auto_adjust=True,
            multi_level_index=False,   # flatten multi-level columns upfront
        )
        if df is None or df.empty:
            return None

        # Flatten multi-level columns if still present (older yfinance versions)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Keep only OHLCV columns that exist
        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        if "Close" not in cols:
            return None
        df = df[cols].copy()
        df.dropna(subset=["Close"], inplace=True)

        if len(df) < min_bars:
            return None

        return df
    except Exception as e:
        logger.debug("fetch_ohlc %s %s: %s", ticker, interval, e)
        return None


def fetch_daily_change(ticker: str) -> Optional[float]:
    """Fetch today's % change using 2 days of daily data — more accurate than intraday bars."""
    try:
        df = yf.download(ticker, period="5d", interval="1d",
                         progress=False, auto_adjust=True, multi_level_index=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df is None or df.empty or len(df) < 2:
            return None
        prev = float(df["Close"].iloc[-2])
        curr = float(df["Close"].iloc[-1])
        if prev == 0:
            return None
        return round((curr - prev) / prev * 100, 2)
    except Exception:
        return None


def calc_ema(df: pd.DataFrame, length: int) -> Optional[float]:
    """EMA using pandas ewm. Returns None if not enough data."""
    try:
        if len(df) < max(length // 2, 10):
            return None
        ema = df["Close"].ewm(span=length, adjust=False).mean()
        val = float(ema.iloc[-1])
        return val if not np.isnan(val) else None
    except Exception:
        return None


def calc_bb(df: pd.DataFrame, length: int = 20, std: float = 2.0) -> Optional[dict]:
    """Bollinger Bands using rolling mean + std. Returns None if not enough data."""
    try:
        if len(df) < length:
            return None
        close  = df["Close"]
        mid    = close.rolling(length).mean()
        sigma  = close.rolling(length).std(ddof=0)
        upper  = mid + std * sigma
        lower  = mid - std * sigma
        u = float(upper.iloc[-1])
        m = float(mid.iloc[-1])
        lo = float(lower.iloc[-1])
        if any(np.isnan(v) for v in [u, m, lo]):
            return None
        return {"upper": u, "mid": m, "lower": lo}
    except Exception:
        return None


def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[dict]:
    """MACD using EWM. Returns None if insufficient data."""
    try:
        if len(df) < slow + signal:
            return None
        close       = df["Close"]
        ema_fast    = close.ewm(span=fast,   adjust=False).mean()
        ema_slow    = close.ewm(span=slow,   adjust=False).mean()
        macd_line   = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram   = macd_line - signal_line
        m = float(macd_line.iloc[-1])
        s = float(signal_line.iloc[-1])
        h = float(histogram.iloc[-1])
        if any(np.isnan(v) for v in [m, s, h]):
            return None
        return {"macd": m, "signal": s, "histogram": h}
    except Exception:
        return None


def calc_atr(df: pd.DataFrame, period: int = 14) -> Optional[pd.Series]:
    """Average True Range."""
    try:
        if len(df) < period:
            return None
        high  = df["High"]
        low   = df["Low"]
        close = df["Close"]
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()
    except Exception:
        return None


def calc_atr_trailing_stop(df: pd.DataFrame, period: int = 14, multiplier: float = 3.0) -> Optional[dict]:
    """
    ATR Trailing Stop — matches the indicator on your Zerodha chart.
    Returns: { "atr_stop": float, "signal": "buy" | "sell" }
    """
    try:
        if len(df) < period + 5:
            return None
        close    = df["Close"].values.astype(float)
        atr_vals = calc_atr(df, period)
        if atr_vals is None:
            return None
        atr   = atr_vals.values.astype(float)
        stop  = np.zeros(len(close))
        trend = np.ones(len(close))

        for i in range(1, len(close)):
            if np.isnan(atr[i]) or atr[i] == 0:
                stop[i]  = stop[i - 1]
                trend[i] = trend[i - 1]
                continue

            up_stop   = close[i] - multiplier * atr[i]
            down_stop = close[i] + multiplier * atr[i]

            if trend[i - 1] == 1:
                new_stop  = max(up_stop, stop[i - 1]) if close[i] > stop[i - 1] else down_stop
                trend[i]  = 1 if close[i] > new_stop else -1
            else:
                new_stop  = min(down_stop, stop[i - 1]) if close[i] < stop[i - 1] else up_stop
                trend[i]  = -1 if close[i] < new_stop else 1
            stop[i] = new_stop

        sig = "buy" if close[-1] > stop[-1] else "sell"
        return {"atr_stop": round(float(stop[-1]), 2), "signal": sig}
    except Exception:
        return None


def get_close(df: pd.DataFrame) -> Optional[float]:
    try:
        val = float(df["Close"].iloc[-1])
        return val if not np.isnan(val) else None
    except Exception:
        return None


def get_change_pct(df: pd.DataFrame) -> Optional[float]:
    """Intraday change: last bar vs previous bar (used when daily data not available)."""
    try:
        if len(df) < 2:
            return None
        prev = float(df["Close"].iloc[-2])
        curr = float(df["Close"].iloc[-1])
        if prev == 0:
            return None
        return round((curr - prev) / prev * 100, 2)
    except Exception:
        return None
