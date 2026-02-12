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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='autoTrade.log',
    filemode='a'
)
# Also output to console
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger('').addHandler(console)

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
