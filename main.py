import asyncio
import logging
import signal
from config import settings
from db.database import Database
from core.risk_engine import RiskEngine
from core.order_executor import OrderExecutor
from core.trade_logger import TradeLogger
from core.pnl_engine import PnLEngine
from bots.trading_bot import UnifiedBot
from web.server import WebServer

# Configure logging
# Create a custom logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 1. Console Handler - specific level (WARNING) to hide unimportant logs
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)
console_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_format)
logger.addHandler(console_handler)

# 2. Main Log File - INFO level (detailed)
file_handler = logging.FileHandler('autoTrade.log')
file_handler.setLevel(logging.INFO)
file_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_format)
logger.addHandler(file_handler)

# 3. Error Log File - ERROR level (critical issues)
error_handler = logging.FileHandler('errors.log')
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(file_format)
logger.addHandler(error_handler)

# 4. Trade Register Logger Setup
# This logger will be used specifically for recording trades in a separate file
trade_register_logger = logging.getLogger('trade_register')
trade_register_logger.setLevel(logging.INFO)
# Prevent propagation to root logger to avoid duplicating in autoTrade.log/console
trade_register_logger.propagate = False 

trade_handler = logging.FileHandler('trades.log')
trade_handler.setLevel(logging.INFO)
trade_formatter = logging.Formatter('%(asctime)s,%(message)s')
trade_handler.setFormatter(trade_formatter)
trade_register_logger.addHandler(trade_handler)

# Use the root logger for the main script
logger = logging.getLogger(__name__)

async def main():
    logger.info("Starting AutoTrading System...")
    
    # 1. Initialize Database
    db = Database()
    await db.init_db()
    
    # 2. Key Components
    order_executor = OrderExecutor()
    risk_engine = RiskEngine(order_executor)
    
    # 3. Connect to IB
    try:
        await order_executor.connect()
    except Exception as e:
        logger.critical(f"Expected IB connection failure during development if Gateway not running: {e}")
        pass


    # 4. Attach Loggers & Engines
    trade_logger = TradeLogger(db, order_executor)
    pnl_engine = PnLEngine(db, order_executor)
    
    # 5. Initialize Web Server
    web_server = WebServer(db, order_executor, pnl_engine)

    # 6. Initialize Unified Bot
    # Using SIGNAL_BOT_TOKEN as the primary. Usually they are the same.
    token = settings.TELEGRAM_SIGNAL_BOT_TOKEN
    if not token:
        logger.error("No Telegram Bot Token found in settings!")
        return

    trading_bot = UnifiedBot(
        token=token,
        pnl_engine=pnl_engine,
        risk_engine=risk_engine,
        order_executor=order_executor,
        db=db
    )

    # 7. Start Services
    try:
        await web_server.start() # Start Web Dashboard
        await trading_bot.start()
        
        logger.info("System Online. Press Ctrl+C to stop.")
        
        # Keep alive
        stop_event = asyncio.Event()
        
        def signal_handler():
            logger.info("Shutdown signal received.")
            stop_event.set()
            
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, signal_handler)
            loop.add_signal_handler(signal.SIGTERM, signal_handler)
        except NotImplementedError:
             pass

        await stop_event.wait()
        
    except Exception as e:
        logger.error(f"Runtime error: {e}")
    finally:
        logger.info("Shutting down...")
        await trading_bot.stop()
        if 'web_server' in locals():
            await web_server.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
