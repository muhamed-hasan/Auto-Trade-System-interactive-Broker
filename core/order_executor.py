import asyncio
import logging
from ib_insync import IB, Stock, MarketOrder, LimitOrder, Trade as IBTrade
from db.models import Signal, Order
from config import settings

logger = logging.getLogger(__name__)

class OrderExecutor:
    def __init__(self):
        self.ib = IB()
        self.client_id = settings.IB_CLIENT_ID
        self._connected = False

    async def connect(self):
        """
        Connects to IB Gateway/TWS asynchronously.
        """
        if not self.ib.isConnected():
            logger.info(f"Connecting to IB at {settings.IB_HOST}:{settings.IB_PORT} with ID {self.client_id}...")
            try:
                await self.ib.connectAsync(
                    host=settings.IB_HOST, 
                    port=settings.IB_PORT, 
                    clientId=self.client_id
                )
                self._connected = True
                logger.info("Connected to IB.")
            except Exception as e:
                logger.error(f"Failed to connect to IB: {e}")
                self._connected = False
                raise

    async def execute_order(self, signal: Signal) -> IBTrade:
        """
        Executes an order based on the signal.
        """
        if not self.ib.isConnected():
            await self.connect()

        contract = Stock(signal.ticker, 'SMART', 'USD')
        # Qualify contract to get details (conId, etc)
        # Put logic inside try/except block
        try:
            contracts = await self.ib.qualifyContractsAsync(contract)
            if not contracts:
                 raise ValueError(f"Contract not found for {signal.ticker}")
            contract = contracts[0]
        except Exception as e:
            logger.error(f"Failed to qualify contract {signal.ticker}: {e}")
            raise

        # Determine quantity
        quantity = await self._calculate_quantity(signal)
        if quantity <= 0:
            logger.warning(f"Calculated quantity for {signal.ticker} is {quantity}. Skipping order.")
            raise ValueError(f"Invalid quantity: {quantity}")
        
        # Create Order
        if signal.order_type == "market":
            order = MarketOrder(signal.action.upper(), quantity)

        elif signal.order_type == "limit" and signal.price:
            order = LimitOrder(signal.action.upper(), quantity, signal.price)
        else:
            # Fallback to market if limit price not provided
            logger.warning("Limit order requested but no price provided. Using Market.")
            order = MarketOrder(signal.action.upper(), quantity)

        trade = self.ib.placeOrder(contract, order)
        logger.info(f"Order placed: {trade}")
        return trade

    async def _calculate_quantity(self, signal: Signal) -> float:
        # NOTE: IB does not accept "Dollar Amount" orders directly for Stocks in a simple way easily via API without conditions.
        # We calculate the share count client-side based on the current price.

        # Pre-fetch position for SELL to enforce "No Shorting" and optimization
        current_pos_size = 0.0
        if signal.action == 'sell':
            positions = await self.get_all_positions()
            for p in positions:
                if p.contract.symbol == signal.ticker:
                    current_pos_size = p.position
                    break
            
            # Enforce: Don't short if no open position
            if current_pos_size == 0:
                logger.warning(f"No open position for {signal.ticker}. Cannot SELL.")
                raise ValueError(f"No open position {signal.ticker}")

        # Check trade_power first
        if signal.trade_power:
            try:
                power_amt = float(signal.trade_power)
                # Get price
                price = signal.price
                if not price:
                    ticker_data = await self.get_market_price_async(signal.ticker)
                    if ticker_data:
                         price = ticker_data.marketPrice()
                
                if price and price > 0:
                    return int(power_amt // price)
                else:
                    logger.error(f"Cannot calculate trade_power quantity for {signal.ticker}: price unavailable")
                    return 0
            except ValueError:
                logger.error(f"Invalid trade_power: {signal.trade_power}")
                return 0

        # If numeric, return as is
        if isinstance(signal.quantity, (int, float)):
             # Ensure we don't sell more than we have?
             # User didn't strictly ask for this, but it's good practice to prevent flipping to short.
             # But let's stick to the requested "no open position" rule for now.
             return float(signal.quantity)
        
        # If string percentage
        if isinstance(signal.quantity, str) and signal.quantity.endswith('%'):
            pct = float(signal.quantity.strip('%')) / 100.0
            
            if signal.action == 'buy':
                # Get equity
                summary = await self.get_account_summary()
                equity = summary.get('NetLiquidation', 0)
                target_value = equity * pct
                
                # specific price or market price
                price = signal.price
                if not price:
                    ticker_data = await self.get_market_price_async(signal.ticker)
                    if ticker_data:
                         price = ticker_data.marketPrice()
                
                if price and price > 0:
                    return int(target_value // price)
                else:
                    logger.error(f"Cannot calculate buy quantity for {signal.ticker}: price unavailable")
                    return 0

            elif signal.action == 'sell':
                # Use pre-fetched current_pos_size
                if current_pos_size > 0:
                    qty = int(current_pos_size * pct)
                    logger.info(f"Calculated SELL qty for {signal.ticker}: {qty} shares ({pct*100}% of {current_pos_size})")
                    return qty
                else:
                    # Short position handling (if current_pos_size < 0)?
                    # The percentage logic typically applies to Long positions. 
                    # If Short, logic implies shrinking the short? 
                    # "Sell" on Short adds to Short. "Sell 50%" of -10 is -5. 
                    # Selling -5 means buying? No.
                    # Standard logic: "Sell %" implies closing Longs.
                    logger.warning(f"No positive position found for {signal.ticker} to sell percentage")
                    return 0

        try:
            return float(signal.quantity)
        except ValueError:
            logger.error(f"Invalid quantity format: {signal.quantity}")
            return 0

    async def get_account_summary(self) -> dict:
        if not self.ib.isConnected():
             await self.connect()
             
        try:
            tags = await self.ib.accountSummaryAsync()
        except Exception: # If lost connection during call
            await self.connect()
            tags = await self.ib.accountSummaryAsync()

        # Log all available tags for debugging
        logger.info(f"Available account summary tags: {[t.tag for t in tags]}")
        
        summary = {t.tag: float(t.value) for t in tags if t.tag in ['NetLiquidation', 'BuyingPower', 'TotalCashValue', 'UnrealizedPnL', 'RealizedPnL', 'DailyPnL']}
        return summary

    async def get_daily_pnl(self) -> dict:
        """
        Get today's P&L using IB's reqPnL API.
        Returns dict with dailyPnL, unrealizedPnL, and realizedPnL.
        """
        if not self.ib.isConnected():
            await self.connect()
        
        # Get account number
        accounts = self.ib.managedAccounts()
        if accounts:
            account = accounts[0] if isinstance(accounts, list) else accounts.split(',')[0]
        else:
            account = ""
        
        if not account:
            logger.error("No account found for PnL request")
            return {"dailyPnL": 0.0, "unrealizedPnL": 0.0, "realizedPnL": 0.0}
        
        try:
            # Subscribe to PnL updates (if not already subscribed)
            pnl_obj = self.ib.reqPnL(account)
            
            # Wait briefly for the data to arrive
            await asyncio.sleep(0.5)
            
            # Get the latest PnL data
            pnl_list = self.ib.pnl(account)
            
            if pnl_list:
                pnl = pnl_list[0]
                return {
                    "dailyPnL": float(pnl.dailyPnL) if pnl.dailyPnL else 0.0,
                    "unrealizedPnL": float(pnl.unrealizedPnL) if pnl.unrealizedPnL else 0.0,
                    "realizedPnL": float(pnl.realizedPnL) if pnl.realizedPnL else 0.0
                }
            else:
                logger.warning("No PnL data available")
                return {"dailyPnL": 0.0, "unrealizedPnL": 0.0, "realizedPnL": 0.0}
        
        except Exception as e:
            logger.error(f"Error getting daily PnL: {e}")
            return {"dailyPnL": 0.0, "unrealizedPnL": 0.0, "realizedPnL": 0.0}

    async def get_all_positions(self):
        if not self.ib.isConnected():
            await self.connect()
        return await self.ib.reqPositionsAsync()

    async def get_market_price_async(self, ticker: str):
         if not self.ib.isConnected():
             await self.connect()
         contract = Stock(ticker, 'SMART', 'USD')
         try:
             [ticker_data] = await self.ib.reqTickersAsync(contract)
             return ticker_data
         except Exception as e:
             logger.error(f"Error fetching price for {ticker}: {e}")
             return None

    async def cancel_all_orders(self):
        reqs = self.ib.reqOpenOrders()
        for order in reqs:
            self.ib.cancelOrder(order)

    async def get_open_orders(self):
        if not self.ib.isConnected():
            await self.connect()
        
        # reqOpenOrders returns a list of existing Order objects (not Trades)
        # But commonly we want the Trade object to see status? 
        # ib.reqOpenOrders() returns list of Order.
        # ib.openTrades() returns list of Trade objects for open orders (better).
        
        trades = self.ib.openTrades()
        results = []
        for t in trades:
            results.append({
                "orderId": t.order.orderId,
                "symbol": t.contract.symbol,
                "action": t.order.action,
                "quantity": t.order.totalQuantity,
                "type": t.order.orderType,
                "price": t.order.lmtPrice if t.order.lmtPrice else 0.0,
                "status": t.orderStatus.status
            })
        return results

    async def cancel_order(self, order_id: int):
        # Find the open order
        trades = self.ib.openTrades()
        for t in trades:
            if t.order.orderId == order_id:
                self.ib.cancelOrder(t.order)
                return True
        return False

    async def close_all_positions(self):
        positions = self.ib.positions()
        for pos in positions:
            contract = pos.contract
            action = 'SELL' if pos.position > 0 else 'BUY'
            order = MarketOrder(action, abs(pos.position))
            self.ib.placeOrder(contract, order)
