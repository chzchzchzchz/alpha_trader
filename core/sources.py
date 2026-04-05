"""US-LEGAL Data Sources - verified working."""
import httpx
import yfinance as yf
import asyncio
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any
from datetime import datetime

class Sentiment(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

@dataclass
class Signal:
    source: str; topic: str; sentiment: Sentiment; confidence: float; data: Dict = field(default_factory=dict)

def get_etf_signals(tickers=None):
    if tickers is None: tickers = ["SPY","QQQ","IWM","TLT","GLD"]
    return [yf_analysis(tk) for tk in tickers]

def yf_analysis(tk):
    t = yf.Ticker(tk); h = t.history(period="5d")
    if len(h) < 2: return Signal("error", tk, Sentiment.NEUTRAL, 0.0)
    cp = float(h["Close"].iloc[-1]); pc = float(h["Close"].iloc[-2])
    chg = (cp - pc) / pc
    sent = Sentiment.BULLISH if chg > 0.01 else (Sentiment.BEARISH if chg < -0.01 else Sentiment.NEUTRAL)
    return Signal("yfinance", f"{tk} ${cp:.2f} ({chg:+.2%})", sent, max(0.3, min(0.9, 0.5+abs(chg)*10)), {"price":cp})
