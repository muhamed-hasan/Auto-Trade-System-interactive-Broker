import logging
from datetime import datetime
from db.database import Database
from db.models import DailyPnL

logger = logging.getLogger(__name__)

class PnLEngine:
    def __init__(self, db: Database, order_executor):
        self.db = db
        self.executor = order_executor
        self.current_pnl = {
            "realized": 0.0,
            "unrealized": 0.0,
            "total_trades": 0,
            "timestamp": None
        }

    async def update(self):
        try:
            # 1. Realized PnL from DB (only today's closed trades)
            today_realized = await self.db.get_today_realized_pnl()
            realized_from_db = today_realized.get("pnl", 0.0)
            trades_count = today_realized.get("count", 0)

            # 2. Get P&L from IB using reqPnL API
            # This gives us TODAY's P&L values (not cumulative)
            pnl_data = await self.executor.get_daily_pnl()
            
            # From IB reqPnL API:
            # - dailyPnL: Today's total P&L change (what we show as "Total")
            # - realizedPnL: Today's realized P&L only
            # - unrealizedPnL: Total unrealized P&L from all open positions
            daily_pnl_ib = pnl_data.get("dailyPnL", 0.0)
            realized_pnl_ib = pnl_data.get("realizedPnL", 0.0)
            unrealized_pnl_ib = pnl_data.get("unrealizedPnL", 0.0)
            
            # Use IB's values directly
            today_total = daily_pnl_ib  # Today's total P&L change
            realized = realized_pnl_ib   # Today's realized P&L
            unrealized = unrealized_pnl_ib  # Total unrealized P&L
            
            # Update cache
            self.current_pnl = {
                "realized": realized,  # Today's realized P&L
                "unrealized": unrealized,  # Total unrealized P&L from all positions
                "total": today_total,  # Today's total P&L change from IB
                "total_trades": trades_count,
                "timestamp": datetime.now().isoformat()
            }
            
            # 3. Persist to Daily PnL table
            date_str = datetime.now().strftime("%Y-%m-%d")
            await self.db.update_daily_pnl(date_str, realized, unrealized, trades_count)
            
            logger.info(f"PnL Update: Daily Total={today_total:.2f} (Realized={realized:.2f}, Unrealized={unrealized:.2f}), Trades={trades_count}")
            
        except Exception as e:
            logger.error(f"Error updating PnL: {e}")

    def get_report(self) -> str:
        # Formatted string for Telegram
        r = self.current_pnl["realized"]
        u = self.current_pnl["unrealized"]
        t = self.current_pnl["total_trades"]
        total = r + u
        
        emoji = "🟢" if total >= 0 else "🔴"
        
        return (
            f"📊 **Daily P&L Report**\n"
            f"────────────────\n"
            f"💰 Realized:   ${r:.2f}\n"
            f"📉 Unrealized: ${u:.2f}\n"
            f"───────────────\n"
            f"{emoji} Total:      ${total:.2f}\n"
            f"🔢 Trades:     {t}"
        )
