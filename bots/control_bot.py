import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, filters
from config import settings
from db.database import Database
from core.pnl_engine import PnLEngine
from core.order_executor import OrderExecutor

logger = logging.getLogger(__name__)

class ControlBot:
    def __init__(self, token: str, pnl_engine: PnLEngine, order_executor: OrderExecutor, db: Database):
        self.token = token
        self.pnl_engine = pnl_engine
        self.executor = order_executor
        self.db = db
        self.app = Application.builder().token(token).build()
        
        # Whitelist filter
        whitelist_filter = filters.User(user_id=settings.TELEGRAM_WHITELIST_IDS)
        
        # Handlers
        self.app.add_handler(CommandHandler("start", self.start_command, whitelist_filter))
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Fallback for unauthorized users
        # self.app.add_handler(MessageHandler(~whitelist_filter, self.unauthorized))

    async def start(self):
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Control Bot started polling...")

    async def stop(self):
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("📊 Profile", callback_data='profile'),
             InlineKeyboardButton("📈 PnL Today", callback_data='pnl')],
            [InlineKeyboardButton("📜 History", callback_data='history'),
             InlineKeyboardButton("⚙️ Settings", callback_data='settings')],
            [InlineKeyboardButton("🔴 KILL SWITCH", callback_data='kill')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Trading Control Panel", reply_markup=reply_markup)

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == 'profile':
            summary = await self.executor.get_account_summary()
            positions = await self.executor.get_all_positions()
            pos_text = "\n".join([f"{p.contract.symbol}: {p.position}" for p in positions])
            msg = (
                f"👤 **Profile**\n"
                f"Equity: ${summary.get('NetLiquidation', 'N/A')}\n"
                f"Buying Power: ${summary.get('BuyingPower', 'N/A')}\n\n"
                f"**Positions**:\n{pos_text or 'None'}"
            )
            await query.edit_message_text(msg)
            
        elif data == 'pnl':
            report = await self.pnl_engine.update() # Update first
            # Report is stored/returned? pnl_engine.update returns None, updates internal state.
            # Fix pnl_engine.update to return dict or rely on get_report
            # Report generation is sync string construction.
            report_str = self.pnl_engine.get_report()
            await query.edit_message_text(report_str)
            
        elif data == 'history':
            # Implement history fetch from DB
            await query.edit_message_text("📜 History: Not implemented yet") # TODO
            
        elif data == 'kill':
            await self.executor.cancel_all_orders()
            await self.executor.close_all_positions()
            await query.edit_message_text("🚨 KILL SWITCH ACTIVATED: All orders cancelled & positions closing.")
            
        elif data == 'settings':
             await query.edit_message_text(f"Settings:\nMode: {settings.TRADING_MODE}\nRisk: {settings.MAX_RISK_PER_TRADE_PERCENT*100}%")

        # Re-show menu? Or separate command to refresh menu.
        # Maybe add "Back" button.
