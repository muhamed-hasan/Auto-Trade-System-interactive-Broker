import aiosqlite
import logging
import json
from datetime import datetime
from db.models import Signal, Order, Trade, SCHEMA_SQL
from config import settings

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path=settings.DB_PATH):
        self.db_path = db_path

    async def init_db(self):
        # Create parent dir if not exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.commit()
            logger.info(f"Database initialized at {self.db_path}")

    async def log_signal(self, signal: Signal, status: str = "received") -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO signals (raw_json, ticker, action, quantity, price, received_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.raw_json,
                    signal.ticker,
                    signal.action,
                    str(signal.quantity),
                    signal.price,
                    datetime.now(),
                    status
                )
            )
            await db.commit()
            return cursor.lastrowid

    async def update_signal_status(self, signal_id: int, status: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE signals SET status = ? WHERE id = ?", (status, signal_id))
            await db.commit()

    async def log_order(self, signal_id: int, order: Order) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO orders (signal_id, ib_order_id, ticker, action, quantity, fill_price, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_id,
                    order.ib_order_id,
                    order.ticker,
                    order.action,
                    order.quantity,
                    order.fill_price,
                    order.status,
                    datetime.now()
                )
            )
            await db.commit()
            return cursor.lastrowid

    async def update_order_by_ib_id(self, ib_order_id: int, status: str, filled_qty: float = None, fill_price: float = None):
         async with aiosqlite.connect(self.db_path) as db:
             updates = ["status = ?"]
             params = [status]
             if filled_qty is not None:
                 updates.append("quantity = ?")
                 params.append(filled_qty)
             if fill_price is not None:
                 updates.append("fill_price = ?")
                 params.append(fill_price)
             
             params.append(ib_order_id)
             
             query = f"UPDATE orders SET {', '.join(updates)} WHERE ib_order_id = ?"
             await db.execute(query, tuple(params))
             await db.commit()
            
    async def log_trade(self, trade: Trade):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO trades (ticker, entry_price, exit_price, quantity, pnl, opened_at, closed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.ticker,
                    trade.entry_price,
                    trade.exit_price,
                    trade.quantity,
                    trade.pnl,
                    trade.opened_at,
                    trade.closed_at
                )
            )
            await db.commit()

    async def get_today_realized_pnl(self):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT SUM(pnl), COUNT(*) FROM trades WHERE date(closed_at) = date('now', 'localtime')"
            )
            row = await cursor.fetchone()
            if row and row[0] is not None:
                return {"pnl": row[0], "count": row[1]}
            return {"pnl": 0.0, "count": 0}

    async def get_daily_pnl(self, date_str: str = None):
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
            
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT * FROM daily_pnl WHERE date = ?", (date_str,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "date": row[0],
                        "realized_pnl": row[1],
                        "unrealized_pnl": row[2],
                        "total_trades": row[3]
                    }
                return None
    
    async def update_daily_pnl(self, date_str: str, realized: float, unrealized: float, trades: int):
         async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO daily_pnl (date, realized_pnl, unrealized_pnl, total_trades)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    realized_pnl = excluded.realized_pnl,
                    unrealized_pnl = excluded.unrealized_pnl,
                    total_trades = excluded.total_trades
                """,
                (date_str, realized, unrealized, trades)
            )
            await db.commit()

    async def get_system_state(self, key: str):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT value FROM system_state WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def set_system_state(self, key: str, value: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO system_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, str(value), datetime.now())
            )
            await db.commit()
