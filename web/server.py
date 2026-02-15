
import logging
import asyncio
from aiohttp import web
import json
from config import settings

logger = logging.getLogger(__name__)

class WebServer:
    def __init__(self, db, order_executor, pnl_engine):
        self.db = db
        self.executor = order_executor
        self.pnl_engine = pnl_engine
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
        self.app.router.add_get('/api/pnl', self.handle_pnl)
        self.app.router.add_get('/api/activity', self.handle_activity)
        self.app.router.add_get('/api/orders/open', self.handle_open_orders)
        self.app.router.add_post('/api/orders/cancel', self.handle_cancel_order)
        self.app.router.add_get('/api/history', self.handle_history)
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_post('/api/shutdown', self.handle_shutdown)
        
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


    async def handle_history(self, request):
        try:
            orders = await self.db.get_todays_orders()
            return web.json_response(orders)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_status(self, request):
        try:
            trading_status = await self.db.get_system_state("trading_status") or "active"
            ib_connected = self.executor.ib.isConnected()
            
            market_status = await self.executor.get_market_status()
            market_indices = await self.executor.get_market_indices()
            
            return web.json_response({
                "trading_status": trading_status,
                "ib_connected": ib_connected,
                "mode": settings.TRADING_MODE,
                "market_status": market_status,
                "indices": market_indices
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
