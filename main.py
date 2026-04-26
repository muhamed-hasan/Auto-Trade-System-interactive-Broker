import asyncio
import logging
import signal
import os
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

async def eod_close_worker(db, order_executor):
    """
    Background worker that checks once per minute if we have reached
    15 minutes before the configured market close. If EOD auto-close
    is enabled, it triggers the signal positions close logic.
    """
    logger.info("EOD Close Worker initialized.")
    from datetime import datetime, timezone
    while True:
        try:
            # Check every minute, but we only want to fire once
            now = datetime.now(timezone.utc)
            
            auto_close_time_minutes_str = await db.get_system_state("auto_close_time_minutes")
            if auto_close_time_minutes_str is None:
                auto_close_time_minutes = 5
            else:
                try:
                    auto_close_time_minutes = int(auto_close_time_minutes_str)
                except ValueError:
                    auto_close_time_minutes = 5

            close_minute_total = settings.MARKET_CLOSE_HOUR * 60 - auto_close_time_minutes
            target_hour = close_minute_total // 60
            target_minute = close_minute_total % 60

            if now.hour == target_hour and now.minute == target_minute:
                # Check status
                auto_close = await db.get_system_state("auto_close_signals_eod")
                trading_status = await db.get_system_state("trading_status")
                
                if str(auto_close).lower() == "true" and trading_status != "paused":
                    logger.info("Triggering automatic EOD close for all positions.")
                    try:
                        await order_executor.close_all_positions()
                        logger.info("EOD Auto-close initiated for all positions.")
                    except Exception as e:
                        logger.error(f"Error during EOD Auto-close: {e}")
                
                # Sleep enough to prevent triggering twice in the same minute
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(30)
                
        except asyncio.CancelledError:
            logger.info("EOD Close Worker shutting down...")
            break
        except Exception as e:
            logger.error(f"Error in EOD Close Worker: {e}")
            await asyncio.sleep(30)

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
    
    # 5. Initialize Services
    stop_event = asyncio.Event()
    
    def shutdown_trigger():
        logger.warning("Web UI requested shutdown. Stopping system...")
        stop_event.set()

    # 6. Initialize Unified Bot (BEFORE web server, so we can pass reference)
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

    # 7. Initialize Web Server with webhook support and shutdown trigger
    web_server = WebServer(db, order_executor, pnl_engine, risk_engine=risk_engine, trading_bot=trading_bot)
    web_server.add_shutdown_listener(shutdown_trigger)

    # 8. Start Services
    try:
        await web_server.start() # Start Web Dashboard
        
        # Start the Telegram bot in the background so it doesn't block the UI server 
        # from responding to account data requests if Telegram network is currently failing.
        asyncio.create_task(trading_bot.start())
        
        # Start EOD Close worker
        asyncio.create_task(eod_close_worker(db, order_executor))
        
        logger.info("System Online. Press Ctrl+C to stop.")
        
        # Send startup notification to Telegram
        try:
            startup_msg = (
                "🟢 **AutoTrade System Online**\n"
                f"⏰ Started at: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"📡 IB Connected: {order_executor.ib.isConnected()}\n"
                f"🌐 Webhook URL: http://YOUR_SERVER:8080/webhook/tradingview\n"
                f"🔧 Mode: {settings.TRADING_MODE}"
            )
            await web_server.send_telegram_notification(startup_msg)
            logger.info("Startup notification sent to Telegram")
        except Exception as e:
            logger.warning(f"Failed to send startup notification: {e}")
        
        # Signal Handling
        shutdown_called = False
        def signal_handler():
            nonlocal shutdown_called
            if not shutdown_called:
                logger.info("Shutdown signal received. Press Ctrl+C again to force quit.")
                shutdown_called = True
                stop_event.set()
            else:
                logger.warning("Force quit received. Terminating immediately.")
                os._exit(1)
            
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, signal_handler)
            loop.add_signal_handler(signal.SIGTERM, signal_handler)
        except (NotImplementedError, ValueError):
             # ValueError can happen if not in main thread, though unlikely here
             pass

        await stop_event.wait()
        
    except Exception as e:
        logger.error(f"Runtime error: {e}")
    finally:
        logger.info("Initiating shutdown sequence...")
        
        # 1. Stop Telegram Bot
        if 'trading_bot' in locals():
            logger.info("Stopping Trading Bot...")
            try:
                await asyncio.wait_for(trading_bot.stop(), timeout=3.0)
            except asyncio.TimeoutError:
                logger.error("Trading Bot stop timed out.")
            except Exception as e:
                logger.error(f"Error stopping Trading Bot: {e}")

        # 2. Stop Web Server
        if 'web_server' in locals():
            logger.info("Stopping Web Server...")
            try:
                await asyncio.wait_for(web_server.stop(), timeout=3.0)
            except asyncio.TimeoutError:
                logger.error("Web Server stop timed out.")
            except Exception as e:
                logger.error(f"Error stopping Web Server: {e}")

        # 3. Disconnect IB
        if 'order_executor' in locals():
            logger.info("Disconnecting Order Executor...")
            try:
                await asyncio.wait_for(order_executor.disconnect(), timeout=3.0)
            except asyncio.TimeoutError:
                logger.error("Order Executor disconnect timed out.")
            except Exception as e:
                logger.error(f"Error disconnecting Order Executor: {e}")

        # 4. Cancel all remaining tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if tasks:
            logger.info(f"Cancelling {len(tasks)} pending tasks...")
            for task in tasks:
                task.cancel()
            
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=1.0)
            except Exception:
                pass

        logger.info("Shutdown complete.")

if __name__ == "__main__":
    try:
        # Use a new event loop for cleaner restarts/stops if run interactively, 
        # but standard asyncio.run is fine for scripts.
        asyncio.run(main())
    except KeyboardInterrupt:
        # Handle the initial Ctrl+C if it happens during startup/before loop
        pass
