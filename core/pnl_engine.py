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
            pnl_data = await self.executor.get_daily_pnl()
            
            # DailyPnL from IB includes both realized and unrealized for today
            daily_pnl_ib = pnl_data.get("dailyPnL", 0.0)
            total_unrealized = pnl_data.get("unrealizedPnL", 0.0)
            realized_from_ib = pnl_data.get("realizedPnL", 0.0)
            
            # Use IB's daily PnL which is the most accurate
            # Calculate today's unrealized: dailyPnL - realized
            # We use our DB realized if available, otherwise IB's
            realized = realized_from_db if realized_from_db != 0 else realized_from_ib
            today_unrealized = daily_pnl_ib - realized
            today_total = daily_pnl_ib
            
            # Update cache
            self.current_pnl = {
                "realized": realized,  # Today's realized
                "unrealized": today_unrealized,  # Today's unrealized change
                "total": today_total,  # Today's total P&L (from IB)
                "total_unrealized": total_unrealized,  # Total unrealized from all positions
                "total_trades": trades_count,
                "timestamp": datetime.now().isoformat()
            }
            
            # 3. Persist to Daily PnL table
            date_str = datetime.now().strftime("%Y-%m-%d")
            await self.db.update_daily_pnl(date_str, realized, today_unrealized, trades_count)
            
            logger.info(f"PnL Update: Today's Total={today_total:.2f} (Realized={realized:.2f}, Unrealized Change={today_unrealized:.2f}), Total Unrealized={total_unrealized:.2f}, Trades={trades_count}")
            
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
