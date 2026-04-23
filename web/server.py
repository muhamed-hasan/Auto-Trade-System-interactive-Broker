
import logging
import asyncio
from aiohttp import web
import json
import re
import unicodedata
from datetime import datetime, timezone
from config import settings
from core.signal_validator import validate_signal

logger = logging.getLogger(__name__)

class WebServer:
    def __init__(self, db, order_executor, pnl_engine, risk_engine=None, trading_bot=None):
        self.db = db
        self.executor = order_executor
        self.pnl_engine = pnl_engine
        self.risk_engine = risk_engine
        self.trading_bot = trading_bot  # Reference to send Telegram notifications
        self.app = web.Application()
        self.runner = None
        self.site = None
        
        # Setup Routes
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_static('/static/', path='web/static', name='static')
        
        # API Routes
        self.app.router.add_get('/api/account', self.handle_account)
        self.app.router.add_get('/api/positions', self.handle_positions)
        self.app.router.add_post('/api/positions/close', self.handle_close_position)
        self.app.router.add_post('/api/positions/close_all', self.handle_close_all_positions)
        self.app.router.add_get('/api/pnl', self.handle_pnl)
        self.app.router.add_get('/api/activity', self.handle_activity)
        self.app.router.add_get('/api/orders/open', self.handle_open_orders)
        self.app.router.add_post('/api/orders/cancel', self.handle_cancel_order)
        self.app.router.add_get('/api/history', self.handle_history)
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_post('/api/settings/trade_power', self.handle_update_trade_power)
        self.app.router.add_post('/api/settings/auto_close_eod', self.handle_update_auto_close_eod)
        self.app.router.add_post('/api/shutdown', self.handle_shutdown)
        
        # TradingView Webhook endpoint - receives signals directly via HTTP POST
        self.app.router.add_post('/webhook/tradingview', self.handle_tradingview_webhook)
        
        self.shutdown_callbacks = []

    async def start(self, host="0.0.0.0", port=8080):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, host, port)
        await self.site.start()
        logger.info(f"Web Dashboard started at http://{host}:{port}")

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()

    def add_shutdown_listener(self, callback):
        self.shutdown_callbacks.append(callback)

    # --- Handlers ---
    
    async def handle_shutdown(self, request):
        logger.warning("Shutdown initiated via Web UI")
        # Trigger all registered shutdown callbacks
        for callback in self.shutdown_callbacks:
             # If callback is async, await it, otherwise run it
             if asyncio.iscoroutinefunction(callback):
                 asyncio.create_task(callback())
             else:
                 callback()
                 
        return web.json_response({"status": "shutting_down", "message": "System is stopping..."})

    async def handle_update_trade_power(self, request):
        try:
            data = await request.json()
            power = data.get("trade_power")
            if not power:
                return web.json_response({"error": "Missing trade_power"}, status=400)
            
            new_power = float(power)
            settings.DEFAULT_TRADE_POWER = new_power
            settings.update_env_variable("DEFAULT_TRADE_POWER", str(new_power))
            
            return web.json_response({"status": "success", "trade_power": new_power})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_update_auto_close_eod(self, request):
        try:
            data = await request.json()
            enabled = data.get("enabled")
            if enabled is None:
                return web.json_response({"error": "Missing enabled flag"}, status=400)
            
            val_str = "true" if enabled else "false"
            await self.db.set_system_state("auto_close_signals_eod", val_str)
            return web.json_response({"status": "success", "auto_close_signals_eod": enabled})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_index(self, request):
        return web.FileResponse('./web/static/index.html')

    async def handle_account(self, request):
        try:
            summary = await self.executor.get_account_summary()
            return web.json_response(summary)
        except Exception as e:
            logger.error(f"Web API Error (Account): {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_positions(self, request):
        try:
            positions = await self.executor.get_all_positions()
            
            # Get portfolio items which include market prices
            portfolio = self.executor.ib.portfolio()
            
            # Create a lookup dict by symbol
            portfolio_map = {item.contract.symbol: item for item in portfolio}
            
            # Convert IB Position objects to dicts
            pos_list = []
            for p in positions:
                symbol = p.contract.symbol
                
                # Get portfolio item for this position
                portfolio_item = portfolio_map.get(symbol)
                
                if portfolio_item:
                    market_price = portfolio_item.marketPrice
                    market_value = portfolio_item.marketValue
                    unrealized_pnl = portfolio_item.unrealizedPNL
                else:
                    # Fallback if not in portfolio
                    market_price = p.avgCost
                    market_value = p.position * p.avgCost
                    unrealized_pnl = 0.0
                
                if p.position == 0:
                    continue
                    
                pos_list.append({
                    "symbol": symbol,
                    "position": p.position,
                    "avg_cost": p.avgCost,
                    "market_price": market_price,
                    "market_value": market_value,
                    "unrealized_pnl": unrealized_pnl
                })
            return web.json_response(pos_list)
        except Exception as e:
            logger.error(f"Web API Error (Positions): {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_pnl(self, request):
        try:
            # Update P&L from IB before returning
            await self.pnl_engine.update()
            pnl_data = self.pnl_engine.current_pnl
            return web.json_response(pnl_data)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_activity(self, request):
        try:
            signals = await self.db.get_recent_signals(limit=20)
            orders = await self.db.get_recent_orders(limit=20)
            
            # Combine and sort? Or just return both
            return web.json_response({
                "signals": signals,
                "orders": orders
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_open_orders(self, request):
        try:
            open_orders = await self.executor.get_open_orders()
            return web.json_response(open_orders)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_cancel_order(self, request):
        try:
            data = await request.json()
            order_id = data.get('order_id')
            if not order_id:
                return web.json_response({"error": "Missing order_id"}, status=400)
            
            success = await self.executor.cancel_order(int(order_id))
            if success:
                return web.json_response({"status": "cancelled", "order_id": order_id})
            else:
                return web.json_response({"error": "Order not found or could not cancel"}, status=404)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_close_position(self, request):
        try:
            data = await request.json()
            symbol = data.get('symbol')
            if not symbol:
                return web.json_response({"error": "Missing symbol"}, status=400)
            
            success = await self.executor.close_position(symbol)
            if success:
                return web.json_response({"status": "closed", "symbol": symbol})
            else:
                return web.json_response({"error": f"Position for {symbol} not found or could not be closed"}, status=404)
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_close_all_positions(self, request):
        try:
            await self.executor.close_all_positions()
            return web.json_response({"status": "closed_all", "message": "Close all positions initiated"})
        except Exception as e:
            logger.error(f"Error closing all positions: {e}")
            return web.json_response({"error": str(e)}, status=500)


    async def handle_history(self, request):
        try:
            orders = await self.db.get_todays_orders()
            trades_data = await self.db.get_recent_trades(limit=100)
            
            # Build a lookup of trades by ticker for P&L data
            trades_by_ticker = {}
            for t in trades_data:
                ticker = t.get('ticker', '')
                if ticker not in trades_by_ticker:
                    trades_by_ticker[ticker] = []
                trades_by_ticker[ticker].append(t)
            
            # Pair buy/sell orders per ticker to compute P&L
            # Group orders by ticker
            ticker_orders = {}
            for o in orders:
                ticker = o.get('ticker', '')
                if ticker not in ticker_orders:
                    ticker_orders[ticker] = {'buys': [], 'sells': []}
                if o.get('action') == 'buy':
                    ticker_orders[ticker]['buys'].append(o)
                else:
                    ticker_orders[ticker]['sells'].append(o)
            
            # Enrich each order with buy_price, sell_price, pnl_usd, result
            enriched = []
            for o in orders:
                ticker = o.get('ticker', '')
                action = o.get('action', '')
                qty = o.get('quantity', 0)
                fill_price = o.get('fill_price')
                
                entry = dict(o)
                entry['buy_price'] = None
                entry['sell_price'] = None
                entry['pnl_usd'] = None
                entry['result'] = None
                
                pair = ticker_orders.get(ticker, {})
                
                if action == 'buy' and fill_price:
                    entry['buy_price'] = fill_price
                    # Find matching sell for this ticker
                    for s in pair.get('sells', []):
                        if s.get('fill_price'):
                            entry['sell_price'] = s['fill_price']
                            pnl = (s['fill_price'] - fill_price) * qty
                            entry['pnl_usd'] = round(pnl, 2)
                            entry['result'] = 'WIN' if pnl > 0 else 'LOSS' if pnl < 0 else 'BREAK EVEN'
                            break
                elif action == 'sell' and fill_price:
                    entry['sell_price'] = fill_price
                    # Find matching buy
                    for b in pair.get('buys', []):
                        if b.get('fill_price'):
                            entry['buy_price'] = b['fill_price']
                            pnl = (fill_price - b['fill_price']) * qty
                            entry['pnl_usd'] = round(pnl, 2)
                            entry['result'] = 'WIN' if pnl > 0 else 'LOSS' if pnl < 0 else 'BREAK EVEN'
                            break
                
                # If no pair found but order is filled, mark as OPEN
                if entry['result'] is None and o.get('status') == 'Filled':
                    entry['result'] = 'OPEN'
                
                # Also check trades table for realized PnL
                if entry['pnl_usd'] is None and ticker in trades_by_ticker:
                    for t in trades_by_ticker[ticker]:
                        if t.get('pnl') and t['pnl'] != 0:
                            entry['pnl_usd'] = round(t['pnl'], 2)
                            entry['result'] = 'WIN' if t['pnl'] > 0 else 'LOSS'
                            if t.get('entry_price') and t['entry_price'] > 0:
                                entry['buy_price'] = entry['buy_price'] or t['entry_price']
                            if t.get('exit_price') and t['exit_price'] > 0:
                                entry['sell_price'] = entry['sell_price'] or t['exit_price']
                            break
                
                enriched.append(entry)
            
            return web.json_response(enriched)
        except Exception as e:
            logger.error(f"History API error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_status(self, request):
        try:
            trading_status = await self.db.get_system_state("trading_status") or "active"
            ib_connected = self.executor.ib.isConnected()
            
            market_status = await self.executor.get_market_status()
            market_indices = await self.executor.get_market_indices()
            
            if self.trading_bot and self.trading_bot.app and self.trading_bot.app.bot and not getattr(self, '_telegram_info', None):
                try:
                    me = await self.trading_bot.app.bot.get_me()
                    bot_name = me.username  or me.first_name
                    channel_title = str(settings.TELEGRAM_CHANNEL_ID)
                    if settings.TELEGRAM_CHANNEL_ID:
                        try:
                            chat = await self.trading_bot.app.bot.get_chat(settings.TELEGRAM_CHANNEL_ID)
                            channel_title = chat.title or chat.username or str(settings.TELEGRAM_CHANNEL_ID)
                        except Exception:
                            pass
                    self._telegram_info = {"bot_name": bot_name, "channel_title": channel_title}
                except Exception as e:
                    logger.debug(f"Telegram status error: {e}")
            
            auto_close = await self.db.get_system_state("auto_close_signals_eod")
            auto_close_bool = str(auto_close).lower() == "true"
            
            return web.json_response({
                "trading_status": trading_status,
                "ib_connected": ib_connected,
                "mode": settings.TRADING_MODE,
                "market_status": market_status,
                "indices": market_indices,
                "telegram": getattr(self, '_telegram_info', None),
                "default_trade_power": getattr(settings, 'DEFAULT_TRADE_POWER', 4000),
                "auto_close_signals_eod": auto_close_bool
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    # --- TradingView Webhook ---
    
    @staticmethod
    def _sanitize_webhook_text(text: str) -> str:
        """Remove invisible Unicode characters from webhook payloads."""
        text = text.replace('\ufeff', '')
        text = text.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '')
        text = text.replace('\u200e', '').replace('\u200f', '').replace('\u2060', '')
        text = text.replace('\u201c', '"').replace('\u201d', '"')
        text = text.replace('\u2018', "'").replace('\u2019', "'")
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Cf')
        return text.strip()

    async def send_telegram_notification(self, message: str):
        """Send a notification message to the configured Telegram channel/user."""
        if not self.trading_bot:
            logger.warning("No trading bot reference, can't send Telegram notification")
            return

        async def _send():
            try:
                # Send to whitelisted user(s) for reliability
                for user_id in settings.TELEGRAM_WHITELIST_IDS:
                    try:
                        await asyncio.wait_for(
                            self.trading_bot.app.bot.send_message(
                                chat_id=user_id,
                                text=message
                            ),
                            timeout=5.0
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify user {user_id}: {e}")
            except Exception as e:
                logger.error(f"Failed to send Telegram notification: {e}")

        asyncio.create_task(_send())

    async def handle_tradingview_webhook(self, request):
        """
        Receives TradingView webhook alerts directly via HTTP POST.
        This bypasses the Telegram relay entirely, fixing the issue where
        the bot cannot read its own messages posted to a Telegram channel.
        
        TradingView Alert URL: http://YOUR_SERVER:8080/webhook/tradingview
        TradingView Alert Message: Your JSON signal body
        """
        try:
            # Read the raw body
            raw_body = await request.text()
            logger.info(f"[WEBHOOK] Received TradingView webhook: {raw_body[:200]}")
            
            # Sanitize
            clean_body = self._sanitize_webhook_text(raw_body)
            
            # Check for System Pause
            status = await self.db.get_system_state("trading_status")
            if status == "paused":
                logger.info("[WEBHOOK] Signal received but trading is PAUSED.")
                await self.send_telegram_notification("⏸ Webhook signal received but trading is PAUSED.")
                return web.json_response({"status": "paused", "message": "Trading is paused"}, status=200)
            
            # Validate signal
            try:
                signal = validate_signal(clean_body)
            except ValueError as e:
                logger.warning(f"[WEBHOOK] Invalid signal: {e}")
                return web.json_response({"status": "error", "message": f"Invalid signal: {e}"}, status=400)
            
            # Log signal
            signal_id = await self.db.log_signal(signal, status="received")
            
            # Risk check
            if self.risk_engine:
                summary = await self.executor.get_account_summary()
                positions = await self.executor.get_all_positions()
                approved, reason = await self.risk_engine.evaluate(signal, summary, positions or [])
                
                if not approved:
                    await self.db.update_signal_status(signal_id, f"rejected: {reason}")
                    msg = f"⛔ Webhook Signal Rejected: {reason}\nTicker: {signal.ticker}"
                    await self.send_telegram_notification(msg)
                    logger.warning(f"[WEBHOOK] Signal rejected: {reason}")
                    return web.json_response({"status": "rejected", "reason": reason}, status=200)
            
            # Execute order
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
                
                msg = f"✅ Order Placed (Webhook): {signal.action.upper()} {signal.ticker}\nID: {trade.order.orderId}\nQty: {trade.order.totalQuantity}"
                await self.send_telegram_notification(msg)
                logger.info(f"[WEBHOOK] Order executed: {signal.action} {signal.ticker}")
                
                return web.json_response({
                    "status": "executed",
                    "ticker": signal.ticker,
                    "action": signal.action,
                    "order_id": trade.order.orderId
                })
                
            except ValueError as ve:
                await self.db.update_signal_status(signal_id, f"rejected: {ve}")
                msg = f"⚠️ Order Rejected (Webhook): {ve}\nTicker: {signal.ticker}"
                await self.send_telegram_notification(msg)
                logger.warning(f"[WEBHOOK] Order rejected: {ve}")
                return web.json_response({"status": "rejected", "reason": str(ve)}, status=200)
                
            except Exception as e:
                await self.db.update_signal_status(signal_id, f"error: {e}")
                msg = f"⚠️ Execution Failed (Webhook): {e}\nTicker: {signal.ticker}"
                await self.send_telegram_notification(msg)
                logger.error(f"[WEBHOOK] Execution error: {e}")
                return web.json_response({"status": "error", "message": str(e)}, status=500)
                
        except Exception as e:
            logger.error(f"[WEBHOOK] Webhook handler error: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)
