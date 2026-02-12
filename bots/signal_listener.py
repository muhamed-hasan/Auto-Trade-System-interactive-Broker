import logging
import json
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from core.signal_validator import validate_signal
from core.risk_engine import RiskEngine
from core.order_executor import OrderExecutor
from db.database import Database
from config import settings

logger = logging.getLogger(__name__)

class SignalListenerBot:
    def __init__(self, token: str, risk_engine: RiskEngine, order_executor: OrderExecutor, db: Database):
        self.token = token
        self.risk_engine = risk_engine
        self.executor = order_executor
        self.db = db
        self.app = Application.builder().token(token).build()
        
        # Add handlers
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def start(self):
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Signal Listener Bot started polling...")

    async def stop(self):
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message or not message.text:
            return

        chat_id = update.effective_chat.id
        
        # Filter by Channel ID if configured
        if settings.TELEGRAM_CHANNEL_ID != 0 and chat_id != settings.TELEGRAM_CHANNEL_ID:
            logger.info(f"Ignoring message from unauthorized chat: {chat_id}")
            return

        text = message.text
        logger.info(f"Received signal message from {chat_id}: {text}")
        
        # 1. Parse & Validate
        try:
            signal = validate_signal(text)
        except ValueError as e:
            # Only reply if it's not a noisy message (optional improvement)
            await message.reply_text(f"❌ Invalid format: {e}")
            return

        # Log received signal
        signal_id = await self.db.log_signal(signal, status="received")

        # 2. Risk Check
        summary = await self.executor.get_account_summary()
        positions = await self.executor.get_all_positions() # Helper in executor needed?
        # Using executor.ib.positions() is sync list? No, returns list if updated.
        # But for accurate snapshot we might want reqPositionsAsync.
        # Let's assume executor.get_all_positions() is async and works.
        
        approved, reason = await self.risk_engine.evaluate(signal, summary, positions or [])
        
        if not approved:
            await self.db.update_signal_status(signal_id, f"rejected: {reason}")
            await message.reply_text(f"⛔ Rejected: {reason}")
            return

        # 3. Execute
        try:
            await self.db.update_signal_status(signal_id, "executing")
            trade = await self.executor.execute_order(signal)
            
            # Log order mapping (Signal ID -> IB Order ID)
            # trade.order is the order object. trade.order.orderId might be 0 until placed?
            # ib_insync updates it.
            # We should insert into orders table.
            from db.models import Order
            o = Order(
                id=None,
                signal_id=signal_id,
                ib_order_id=trade.order.orderId, # Might be 0 initially
                ticker=signal.ticker,
                action=signal.action,
                quantity=trade.order.totalQuantity,
                order_type=signal.order_type,
                status=trade.orderStatus.status
            )
            await self.db.log_order(signal_id, o)
            
            await message.reply_text(f"✅ Order Placed: {signal.action.upper()} {signal.ticker}\nID: {trade.order.orderId}")
            
        except Exception as e:
            logger.error(f"Execution Error: {e}")
            await self.db.update_signal_status(signal_id, f"error: {e}")
            await message.reply_text(f"⚠️ Execution Failed: {e}")
