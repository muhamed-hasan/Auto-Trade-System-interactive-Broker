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
            # 1. Realized PnL from DB
            today_realized = await self.db.get_today_realized_pnl()
            realized = today_realized.get("pnl", 0.0)
            trades_count = today_realized.get("count", 0)

            # 2. Unrealized PnL from IB
            summary = await self.executor.get_account_summary()
            unrealized = summary.get("UnrealizedPnL", 0.0)
            
            # Update cache
            self.current_pnl = {
                "realized": realized,
                "unrealized": unrealized,
                "total_trades": trades_count,
                "timestamp": datetime.now()
            }
            
            # 3. Persist to Daily PnL table
            date_str = datetime.now().strftime("%Y-%m-%d")
            await self.db.update_daily_pnl(date_str, realized, unrealized, trades_count)
            
            logger.info(f"PnL Update: Realized={realized}, Unrealized={unrealized}, Trades={trades_count}")
            
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
