from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class Signal:
    ticker: str
    action: str  # 'buy' or 'sell'
    quantity: float | str | None = None # Can be a number or a percentage string like "100%"
    trade_power: Optional[str] = None # Added trade_power
    order_type: str = "market"
    price: Optional[float] = None
    msg: Optional[str] = None
    raw_json: Optional[str] = None
    received_at: datetime = field(default_factory=datetime.now)

@dataclass
class Order:
    id: Optional[int]
    signal_id: int
    ib_order_id: int
    ticker: str
    action: str
    quantity: float
    order_type: str
    status: str = "submitted" # 'submitted', 'filled', 'cancelled'
    fill_price: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.now)
    filled_at: Optional[datetime] = None

@dataclass
class Trade:
    id: Optional[int]
    ticker: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    opened_at: datetime
    closed_at: datetime

@dataclass
class DailyPnL:
    date: str
    realized_pnl: float
    unrealized_pnl: float
    total_trades: int

@dataclass
class SystemState:
    key: str
    value: str
    updated_at: datetime

# SQL Schema
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_json TEXT,
    ticker TEXT,
    action TEXT,
    quantity TEXT,
    price REAL,
    received_at TIMESTAMP,
    status TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER,
    ib_order_id INTEGER,
    ticker TEXT,
    action TEXT,
    quantity REAL,
    fill_price REAL,
    status TEXT,
    created_at TIMESTAMP,
    filled_at TIMESTAMP,
    FOREIGN KEY(signal_id) REFERENCES signals(id)
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT,
    entry_price REAL,
    exit_price REAL,
    quantity REAL,
    pnl REAL,
    opened_at TIMESTAMP,
    closed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_pnl (
    date TEXT PRIMARY KEY,
    realized_pnl REAL,
    unrealized_pnl REAL,
    total_trades INTEGER
);

CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP
);
"""
