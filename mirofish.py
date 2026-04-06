#!/usr/bin/env python3
"""
MiroFish — Swarm Intelligence Engine for Kalshi Prediction Markets.
Multi-agent social simulation that predicts market outcomes.
Each agent has a personality, processes market data, and votes YES/NO.
The swarm consensus is the prediction.
"""
import random
import math
import json
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

PERSONALITIES = {
    "data_driven_quant": {"weight": 0.20, "bias": 0.0, "volatility": 0.3, "sensitivity": 0.8},
    "political_bull":    {"weight": 0.15, "bias": 0.6, "volatility": 0.7, "sensitivity": 0.9},
    "political_bear":    {"weight": 0.10, "bias": -0.5, "volatility": 0.8, "sensitivity": 0.9},
    "crypto_degen":      {"weight": 0.15, "bias": 0.3, "volatility": 1.2, "sensitivity": 0.6},
    "sports_fanatic":    {"weight": 0.10, "bias": 0.1, "volatility": 0.9, "sensitivity": 0.4},
    "cautious_saver":    {"weight": 0.10, "bias": -0.2, "volatility": 0.2, "sensitivity": 0.3},
    "momentum_chaser":   {"weight": 0.10, "bias": 0.0, "volatility": 1.5, "sensitivity": 0.95},
    "contrarian":        {"weight": 0.05, "bias": 0.0, "volatility": 0.5, "sensitivity": -0.7},
    "news_junkie":       {"weight": 0.05, "bias": 0.2, "volatility": 1.0, "sensitivity": 0.7},
}


class Agent:
    def __init__(self, personality_type, agent_id):
        p = PERSONALITIES[personality_type]
        self.id = agent_id
        self.type = personality_type
        self.weight = p["weight"]
        self.bias = p["bias"]
        self.volatility = p["volatility"]
        self.sensitivity = p["sensitivity"]
        self.confidence = 0.5 + random.gauss(0, 0.15)
        self.confidence = max(0.05, min(0.95, self.confidence))

    def vote(self, market_data):
        price = market_data.get("price", 0.5)
        trend = market_data.get("trend", 0)
        cat = market_data.get("category", "")

        # Binary option edge: very low price = asymmetric opportunity
        # If price is 5c, risk is 5c but reward is 95c = 19:1 odds
        # Smart agents recognize this asymmetry
        is_cheap = price < 0.15  # Below 15c
        
        if self.type == "data_driven_quant":
            # Quant sees risk/reward asymmetry in cheap markets
            if is_cheap:
                # Cheap markets have higher expected value if any chance of YES
                base_ev = (1 - price) * (0.2 + trend * 0.3)  # Assume 20%+ chance of resolution
                prob = base_ev + random.gauss(0, 0.05)
            else:
                prob = price + trend * 0.15 + random.gauss(0, self.volatility * 0.05)
        elif self.type == "political_bull":
            if "politics" in cat.lower() or "election" in cat.lower():
                prob = price * (1 + self.bias * 0.3) + self.bias * 0.2
            else:
                prob = price + self.bias * 0.1
        elif self.type == "political_bear":
            if "politics" in cat.lower() or "election" in cat.lower():
                prob = price * (1 - abs(self.bias) * 0.2) - abs(self.bias) * 0.15
            else:
                prob = price + self.bias * 0.05
        elif self.type == "crypto_degen":
            if "crypto" in cat.lower():
                prob = price * (1 + self.bias * 0.5) + trend * self.volatility * 0.1
            else:
                prob = price + self.bias * 0.05
        elif self.type == "momentum_chaser":
            prob = price + trend * 0.3 * self.sensitivity
        elif self.type == "contrarian":
            # Contrarian sees value where others don't -- cheap markets
            if is_cheap:
                prob = 0.2 + random.gauss(0, 0.1)  # Believes cheap has real odds
            else:
                prob = 1 - price + trend * self.sensitivity * 0.1
        elif self.type == "cautious_saver":
            prob = price * 0.7 + 0.5 * 0.3
            prob *= 0.95
        elif self.type == "news_junkie":
            if is_cheap:
                prob = 0.15 + random.gauss(0, 0.1)  # News might change everything
            else:
                prob = price + 0.05
        else:
            prob = price + self.bias * 0.1 + random.gauss(0, self.volatility * 0.1)

        prob += random.gauss(0, 0.03 * self.volatility)
        days = market_data.get("days_to_close", 7)
        if days is not None:
            uncertainty = 0.1 * math.exp(-days / 30)
            prob += random.gauss(0, uncertainty)
        prob = max(0.01, min(0.99, prob))
        vote = "yes" if prob >= 0.5 else "no"
        return {
            "agent_id": self.id, "type": self.type, "vote": vote,
            "probability": round(prob, 4), "confidence": round(self.confidence, 3),
            "weight": self.weight,
        }


class MiroFishSwarm:
    def __init__(self, n_agents=200):
        self.n_agents = n_agents
        self.agents = []
        agent_id = 0
        for ptype, config in PERSONALITIES.items():
            count = max(5, int(n_agents * config["weight"]))
            for _ in range(count):
                self.agents.append(Agent(ptype, agent_id))
                agent_id += 1
        while len(self.agents) < n_agents:
            ptype = random.choice(list(PERSONALITIES.keys()))
            self.agents.append(Agent(ptype, agent_id))
            agent_id += 1
        self.agents = self.agents[:n_agents]

    def predict(self, market_data):
        votes = [agent.vote(market_data) for agent in self.agents]
        yes_weight = sum(v["weight"] for v in votes if v["vote"] == "yes")
        no_weight = sum(v["weight"] for v in votes if v["vote"] == "no")
        total_weight = yes_weight + no_weight
        yes_pct = yes_weight / total_weight if total_weight > 0 else 0.5
        no_pct = no_weight / total_weight if total_weight > 0 else 0.5

        type_votes = defaultdict(list)
        for v in votes:
            type_votes[v["type"]].append(v)
        type_consensus = {}
        for t, av in type_votes.items():
            yes = sum(1 for v in av if v["vote"] == "yes")
            type_consensus[t] = round(yes / len(av), 3) if av else 0.5

        signal = abs(yes_pct - 0.5) * 2
        market_price = market_data.get("price", 0.5)
        edge = round(yes_pct - market_price, 4)

        if yes_pct > market_price + 0.05:
            rec = "buy_yes"
        elif no_pct > (1 - market_price) + 0.05:
            rec = "buy_no"
        else:
            rec = "hold"

        return {
            "yes_pct": round(yes_pct, 4), "no_pct": round(no_pct, 4),
            "n_agents": len(votes),
            "yes_votes": sum(1 for v in votes if v["vote"] == "yes"),
            "no_votes": sum(1 for v in votes if v["vote"] == "no"),
            "signal_strength": round(signal, 4), "edge": edge, "recommendation": rec,
            "type_consensus": type_consensus,
        }


def analyze_market(market, n_agents=300):
    yes_bid = float(market.get("yes_bid_dollars", 0) or 0)
    yes_ask = float(market.get("yes_ask_dollars", 0) or 0)
    price = (yes_bid + yes_ask) / 2 if (yes_bid + yes_ask) > 0 else 0.5

    close_str = market.get("close_time", "")
    days_to_close = None
    if close_str:
        try:
            ct = datetime.fromisoformat(close_str.replace("Z", "+00:00"))
            days_to_close = max(0, (ct - datetime.now(timezone.utc)).total_seconds() / 86400)
        except Exception:
            pass

    swarm = MiroFishSwarm(n_agents=n_agents)
    return swarm.predict({
        "price": price, "volume_24h": float(market.get("volume_24h_fp", 0) or 0),
        "days_to_close": days_to_close, "trend": 0, "news_signal": 0,
        "category": market.get("event_ticker", ""),
    })


if __name__ == "__main__":
    print("=" * 70)
    print("  MIROFISH SWARM INTELLIGENCE — KALSHI EDITION")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    import requests
    KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"

    swarm = MiroFishSwarm(n_agents=300)

    for series in ["KXHIGHNY", "KXBTC100K", "KXINX"]:
        try:
            r = requests.get(f"{KALSHI_API}/markets?series_ticker={series}&status=open&limit=3", timeout=10)
            if r.status_code == 200:
                mkts = r.json().get("markets", [])
                for m in mkts[:2]:
                    result = analyze_market(m, n_agents=300)
                    price = (float(m.get("yes_bid_dollars", 0) or 0) + float(m.get("yes_ask_dollars", 0) or 0)) / 2
                    print(f"\n  Market: {m['ticker']} (price={price:.0%})")
                    print(f"  Swarm:  YES={result['yes_pct']:.1%} NO={result['no_pct']:.1%}")
                    print(f"  Signal: {result['signal_strength']:.2f} | Edge: {result['edge']:+.1%} | Agents: {result['yes_votes']}Y/{result['no_votes']}N")
                    print(f"  Verdict: {result['recommendation'].upper()}")
        except Exception as e:
            print(f"\n  {series}: {e}")
