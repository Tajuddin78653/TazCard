# TazCard 🃏

**NSE F&O Stock Scanner** — BUY & SELL signals with market trend analysis

## Features
- **Market Trend Panel** — Nifty 50 direction + Advance/Decline ratio from 50-stock sample
- **BUY Scanner** — your exact Chartink conditions (5m/30m/2h timeframes)
- **SELL Scanner** — mirror conditions for bearish market
- **Digital Signal Cards** — Entry, SL, Target1, Target2 per stock
- **Score 0–100** — weighted by how many conditions pass
- **Auto mode** — follows market direction (BUY in bull, SELL in bear)

## Scanner Conditions

### BUY Signal
| Timeframe | Condition | Weight |
|-----------|-----------|--------|
| 5-min | EMA(5) > EMA(200) | 20 pts |
| 30-min | Close > EMA(20) | 20 pts |
| 30-min | Close > Upper BB(20,2) | 25 pts |
| 2-hour | Close > Upper BB(20,2) | 25 pts |
| 30-min | MACD bullish crossover | 5 pts |
| 30-min | ATR Trailing Stop buy | 5 pts |

### SELL Signal (mirror)
Same conditions inverted — EMA bearish, Close < Lower BB, MACD bearish

## Tech Stack
- Python + Streamlit
- yfinance (data)
- pandas-ta (indicators)
- Streamlit Cloud (free hosting)

## Data Note
yfinance provides ~15-min delayed data. Results are for reference and planning — not real-time execution signals.

## Disclaimer
Educational tool only. Not financial advice. Always use your own judgement.
