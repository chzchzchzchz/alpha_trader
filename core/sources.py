"""Live price feed from yfinance."""
import yfinance as yf
from dataclasses import dataclass
from enum import Enum
from typing import List
from datetime import datetime

class Sentiment(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

@dataclass
class Signal:
    source: str
    topic: str
    sentiment: Sentiment
    confidence: float
    data: dict

def get_etf_signals(tickers=None):
    if tickers is None: tickers = ["SPY","QQQ","IWM","TLT","GLD"]
    signals = []
    for tk in tickers:
        try:
            t = yf.Ticker(tk)
            h = t.history(period="5d")
            if len(h)<2: continue
            cp = float(h["Close"].iloc[-1])
            pc = float(h["Close"].iloc[-2])
            chg = (cp-pc)/pc
            sen = Sentiment.BULLISH if chg>0.01 else (Sentiment.BEARISH if chg<-0.01 else Sentiment.NEUTRAL)
            conf = max(0.3, min(0.95, 0.5+abs(chg)*10))
            signals.append(Signal("yfinance", f"{tk}: ${cp:.2f} ({chg:+.2%})", sen, conf, {"price":cp,"change":chg}))
        except: pass
    return signals
