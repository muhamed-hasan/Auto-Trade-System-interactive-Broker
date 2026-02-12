import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from config import settings
from db.database import Database
from core.pnl_engine import PnLEngine
from core.order_executor import OrderExecutor
from core.signal_validator import validate_signal

logger = logging.getLogger(__name__)

class UnifiedBot:
    def __init__(self, token: str, pnl_engine: PnLEngine, risk_engine, order_executor: OrderExecutor, db: Database):
        self.token = token
        self.pnl_engine = pnl_engine
        self.risk_engine = risk_engine
        self.executor = order_executor
        self.db = db
        self.app = Application.builder().token(token).build()
        
        # Whitelist filter for control commands
        whitelist_filter = filters.User(user_id=settings.TELEGRAM_WHITELIST_IDS)
        
        # Handlers - Control
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Handlers - Signal Listener
        # We listen for text messages. Filtering by channel ID is done inside the handler.
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_signal))

    async def start(self):
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Unified Trading Bot started polling...")

    async def stop(self):
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

    # --- Control Bot Logic ---
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        logger.info(f"Received /start command from user: {user_id}")
        
        if user_id not in settings.TELEGRAM_WHITELIST_IDS:
             logger.warning(f"Unauthorized access attempt by {user_id}")
             await update.message.reply_text("⛔ Unauthorized Access")
             return

        keyboard = [
            [InlineKeyboardButton("📊 Profile", callback_data='profile'),
             InlineKeyboardButton("📈 Today PnL", callback_data='pnl')],
            [InlineKeyboardButton("📜 Open Positions", callback_data='positions')],
            [InlineKeyboardButton("⏸ Pause Trading", callback_data='pause'),
             InlineKeyboardButton("▶️ Resume Trading", callback_data='resume')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        status = await self.db.get_system_state("trading_status") or "active"
        await update.message.reply_text(f"🤖 **AutoTrade Control Panel**\nStatus: {status.upper()}", reply_markup=reply_markup)

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        
        if data == 'profile':
            summary = await self.executor.get_account_summary()
            msg = (f"👤 **Account Profile**\n"
                   f"Equity: ${summary.get('NetLiquidation', 'N/A')}\n"
                   f"Buying Power: ${summary.get('BuyingPower', 'N/A')}")
            await query.edit_message_text(msg)
            
        elif data == 'pnl':
            await self.pnl_engine.update()
            report_str = self.pnl_engine.get_report()
            await query.edit_message_text(report_str)

        elif data == 'positions':
            positions = await self.executor.get_all_positions()
            # Filter out positions with quantity 0
            active_positions = [p for p in positions if p.position != 0]
            if active_positions:
                pos_text = "\n".join([f"{p.contract.symbol}: {p.position} @ {p.avgCost:.2f}" for p in active_positions])
                msg = f"📜 **Open Positions**:\n{pos_text}"
            else:
                msg = "📜 **Open Positions**: None"
            await query.edit_message_text(msg)
            
        elif data == 'pause':
            await self.db.set_system_state("trading_status", "paused")
            await query.edit_message_text("⏸ **Trading PAUSED**. No new signals will be processed.")
            
        elif data == 'resume':
            await self.db.set_system_state("trading_status", "active")
            await query.edit_message_text("▶️ **Trading RESUMED**. Waiting for signals...")
            
        elif data == 'kill':
            await self.executor.cancel_all_orders()
            await self.executor.close_all_positions()
            await query.edit_message_text("🚨 KILL SWITCH ACTIVATED: All orders cancelled & positions closing.")
            
        elif data == 'settings':
             await query.edit_message_text(f"Settings:\nMode: {settings.TRADING_MODE}\nRisk: {settings.MAX_RISK_PER_TRADE_PERCENT*100}%")

    # --- Signal Listener Logic ---
    async def handle_signal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message or not message.text:
            return

        chat_id = update.effective_chat.id
        
        # Filter by Channel ID if configured
        if settings.TELEGRAM_CHANNEL_ID != 0 and chat_id != settings.TELEGRAM_CHANNEL_ID:
            logger.info(f"Ignoring message from unauthorized chat: {chat_id}")
            return

        # Check for System Pause
        status = await self.db.get_system_state("trading_status")
        if status == "paused":
            logger.info("Signal received but trading is PAUSED. Ignoring.")
            return

        text = message.text
        logger.info(f"Received signal message from {chat_id}: {text}")
        
        try:
            signal = validate_signal(text)
        except ValueError as e:
            await message.reply_text(f"❌ Invalid format: {e}")
            return

        signal_id = await self.db.log_signal(signal, status="received")
        summary = await self.executor.get_account_summary()
        positions = await self.executor.get_all_positions()
        
        approved, reason = await self.risk_engine.evaluate(signal, summary, positions or [])
        
        if not approved:
            await self.db.update_signal_status(signal_id, f"rejected: {reason}")
            await message.reply_text(f"⛔ Rejected: {reason}")
            return

        try:
            await self.db.update_signal_status(signal_id, "executing")
            trade = await self.executor.execute_order(signal)
            
            from db.models import Order
            o = Order(
                id=None,
                signal_id=signal_id,
                ib_order_id=trade.order.orderId,
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
