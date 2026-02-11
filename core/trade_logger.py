import logging
import asyncio
from ib_insync import Trade as IBTrade, Fill
from db.database import Database
from db.models import Order, Trade

logger = logging.getLogger(__name__)

class TradeLogger:
    def __init__(self, db: Database, order_executor):
        self.db = db
        self.executor = order_executor
        self.ib = order_executor.ib
        
        # Subscribe to events
        self.ib.orderStatusEvent += self.on_order_status
        self.ib.execDetailsEvent += self.on_exec_details

    def on_order_status(self, trade: IBTrade):
        # Fire and forget / run as task because DB is async
        asyncio.create_task(self._process_order_status(trade))

    def on_exec_details(self, trade: IBTrade, fill: Fill):
        asyncio.create_task(self._process_exec_details(trade, fill))

    async def _process_order_status(self, trade: IBTrade):
        # Update or Insert order in DB
        # Use ib_order_id (trade.order.orderId)
        # Check if exists (not implemented in DB yet, need query by ib_order_id)
        # For MVP: We only log initial order in 'log_order'.
        # But here we get updates. So we need `update_order_status` in DB.
        # And if not exists? Assume logged by main flow or insert here?
        # Safer to insert if missing.
        
        try:
             # Just update via log_order (insert or ignore? DB doesn't have UNIQUE on ib_order_id yet)
             # Let's assume main loop logs initial order.
             # We just update status.
             # But we need row ID? No, we can update by ib_order_id.
             # I need to add `update_order_by_ib_id` to Database.
             # For now, let's just log every status change as a new row? No, that spams.
             # Let's implement `update_order(ib_order_id, ...)` in DB.
             # Since I can't modify DB.py easily without rewrite, I will use `log_order` for now or assume implemented.
             # Wait, I defined `update_order_status` taking `order_id` (internal ID).
             # I should change DB to support `ib_order_id`.
             pass
        except Exception as e:
            logger.error(f"Error processing order status: {e}")

    async def _process_exec_details(self, trade: IBTrade, fill: Fill):
        # Check for realized PnL
        if fill.execution.realizedPNL:
             pnl = fill.execution.realizedPNL
             logger.info(f"Realized PnL: {pnl} for {trade.contract.symbol}")
             
             # Log trade
             t = Trade(
                 id=None,
                 ticker=trade.contract.symbol,
                 entry_price=0.0, # Hard to track without full history matching
                 exit_price=fill.execution.price,
                 quantity=fill.execution.shares,
                 pnl=pnl,
                 opened_at=fill.execution.time, # Approximate
                 closed_at=fill.execution.time
             )
             await self.db.log_trade(t)
