#!/usr/bin/env python3
import os, sqlite3
DB_PATH = os.path.expanduser("~/alpha_trader/data/autonomous.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Signals table
cur.execute("""
CREATE TABLE IF NOT EXISTS signals (
    ts INTEGER,
    strategy TEXT,
    ticker TEXT,
    recommendation TEXT,
    swarm_yes REAL,
    price REAL,
    edge REAL,
    signal_strength REAL,
    score INTEGER
)
""")

# Trades table
cur.execute("""
CREATE TABLE IF NOT EXISTS trades (
    ts INTEGER,
    ticker TEXT,
    side TEXT,
    price_cents INTEGER,
    status TEXT,
    order_id TEXT,
    strategy TEXT,
    exit_ts INTEGER,
    exit_price_cents INTEGER
)
""")

# Strategy performance table
cur.execute("""
CREATE TABLE IF NOT EXISTS strategy_performance (
    strategy TEXT PRIMARY KEY,
    bt_wr REAL,  -- backtest win rate
    last_updated INTEGER
)
""")

# Proposals table (from research_agent)
cur.execute("""
CREATE TABLE IF NOT EXISTS research_proposals (
    ts INTEGER,
    ticker TEXT,
    side TEXT,
    strategy TEXT,
    price_cents INTEGER,
    edge REAL,
    score REAL,
    market_yes_ask REAL,
    market_yes_bid REAL,
    vol REAL,
    swarm_yes REAL,
    details TEXT
)
""")

# Positions table (for local tracking)
cur.execute("""
CREATE TABLE IF NOT EXISTS positions (
    ticker TEXT PRIMARY KEY,
    count INTEGER,
    side TEXT,
    avg_price REAL
)
""")

conn.commit()
conn.close()
print("Database initialized at", DB_PATH)
