import logging
import re
import unicodedata
from datetime import datetime, timezone
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
        # Configure application with increased timeouts to prevent httpx.ReadError
        self.app = (
            Application.builder()
            .token(token)
            .read_timeout(30)
            .write_timeout(30)
            .connect_timeout(30)
            .pool_timeout(10.0)
            .get_updates_read_timeout(42)
            .build()
        )
        
        # Whitelist filter for control commands
        whitelist_filter = filters.User(user_id=settings.TELEGRAM_WHITELIST_IDS)
        
        # Handlers - Control
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Handlers - Signal Listener
        # We listen for text messages. Filtering by channel ID is done inside the handler.
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_signal))
        
        # IMPORTANT: Channel posts (from TradingView via Telegram channels) come as
        # channel_post updates, NOT regular message updates. We need a separate handler.
        self.app.add_handler(MessageHandler(
            filters.UpdateType.CHANNEL_POST & filters.TEXT,
            self.handle_signal
        ))

    async def start(self):
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Unified Trading Bot started polling...")

    async def stop(self):
        if self.app.updater and self.app.updater.running:
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
            [InlineKeyboardButton("📊 Market Status", callback_data='market_status')],
            [InlineKeyboardButton("🚨 Close All Positions", callback_data='close_all')]
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
            
        elif data == 'close_all':
            await self.executor.close_all_positions()
            await query.edit_message_text("🚨 **CLOSE ALL**: Closing all open positions...")

            
        elif data == 'settings':
             await query.edit_message_text(f"Settings:\nMode: {settings.TRADING_MODE}\nRisk: {settings.MAX_RISK_PER_TRADE_PERCENT*100}%")

        elif data == 'market_status':
            indices = await self.executor.get_market_indices()
            spy = indices.get("SPY", {})
            vix = indices.get("VIX", {})
            
            spy_val = spy.get("value", 0.0)
            spy_change = spy.get("change", 0.0)
            vix_val = vix.get("value", 0.0)
            vix_change = vix.get("change", 0.0)
            
            spy_icon = "🟢" if spy_change >= 0 else "🔴"
            vix_icon = "🔴" if vix_change >= 0 else "🟢" # VIX up is usually bad for market
            
            msg = (f"📊 **Market Status**\n\n"
                   f"**SPY**: ${spy_val:.2f} ({spy_icon} {spy_change:+.2f}%)\n"
                   f"**VIX**: ${vix_val:.2f} ({vix_icon} {vix_change:+.2f}%)")
            await query.edit_message_text(msg)

    # --- Signal Listener Logic ---
    @staticmethod
    def _sanitize_text(text: str) -> str:
        """
        Remove invisible/special Unicode characters that TradingView or Telegram
        inject into messages. These break JSON parsing even though the message
        looks identical when copy-pasted.
        """
        # Remove BOM (Byte Order Mark)
        text = text.replace('\ufeff', '')
        # Remove zero-width characters (common in Telegram forwarded messages)
        text = text.replace('\u200b', '')  # zero-width space
        text = text.replace('\u200c', '')  # zero-width non-joiner
        text = text.replace('\u200d', '')  # zero-width joiner
        text = text.replace('\u200e', '')  # left-to-right mark
        text = text.replace('\u200f', '')  # right-to-left mark
        text = text.replace('\u2060', '')  # word joiner
        text = text.replace('\ufffe', '')  # non-character
        # Remove other common invisible control characters (C0/C1) except newlines and tabs
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        # Remove any remaining Unicode category "Cf" (format characters) except standard whitespace
        text = ''.join(
            ch for ch in text
            if unicodedata.category(ch) != 'Cf'
        )
        # Strip leading/trailing whitespace
        text = text.strip()
        return text

    async def handle_signal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if not message:
            return
        
        # Get text — channel posts may only have text in effective_message
        raw_text = message.text or message.caption
        if not raw_text:
            logger.debug(f"Received non-text message, skipping. Update type: {update.effective_message.__class__.__name__}")
            return

        chat_id = update.effective_chat.id
        
        # Prevent processing old messages on startup (older than 60 seconds)
        # Increased from 10s because TradingView -> Telegram can have delivery latency
        now = datetime.now(timezone.utc)
        if message.date:
            message_date = message.date
            # Ensure message_date is timezone-aware
            if not message_date.tzinfo:
                message_date = message_date.replace(tzinfo=timezone.utc)
            
            age = (now - message_date).total_seconds()
            if age > 20:
                logger.info(f"Ignoring old message from {chat_id} (age: {age:.1f}s)")
                return
        
        # Filter by Channel ID if configured
        if settings.TELEGRAM_CHANNEL_ID != 0 and chat_id != settings.TELEGRAM_CHANNEL_ID:
            logger.info(f"Ignoring message from unauthorized chat: {chat_id}")
            return

        # Check for System Pause
        status = await self.db.get_system_state("trading_status")
        if status == "paused":
            logger.info("Signal received but trading is PAUSED. Ignoring.")
            return

        # Sanitize text: remove invisible Unicode characters from TradingView
        text = self._sanitize_text(raw_text)
        logger.info(f"Received signal message from {chat_id}: {text}")
        
        # Log raw bytes for debugging if text differs after sanitization
        if text != raw_text:
            logger.info(f"Text was sanitized (removed invisible chars). Raw length={len(raw_text)}, clean length={len(text)}")
        
        try:
            signal = validate_signal(text)
        except ValueError as e:
            logger.warning(f"Signal validation failed from {chat_id}: {e} | Raw text: {repr(raw_text)}")
            # Only reply if this is a direct message (not a channel post, to avoid spamming channels)
            if update.effective_chat.type != 'channel':
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
            
        except ValueError as ve:
            logger.warning(f"Execution Validation Failed: {ve}")
            await self.db.update_signal_status(signal_id, f"rejected: {ve}")
            await message.reply_text(f"⚠️ Order Rejected: {ve}")
            
        except Exception as e:
            logger.error(f"Execution Error: {e}")
            await self.db.update_signal_status(signal_id, f"error: {e}")
            await message.reply_text(f"⚠️ Execution Failed: {e}")
