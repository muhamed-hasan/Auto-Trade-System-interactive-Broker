import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import math
from ib_insync import IB, Stock, Index, MarketOrder, LimitOrder, Trade as IBTrade
from db.models import Signal, Order
from config import settings

logger = logging.getLogger(__name__)

class OrderExecutor:
    def __init__(self):
        self.ib = IB()
        self.client_id = settings.IB_CLIENT_ID
        self._connected = False
        self._pnl_subscribed = False
        self.spy_ticker = None
        self.vix_ticker = None

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
                # Set market data type to Delayed Frozen (4) to get data even if market closed/no sub
                self.ib.reqMarketDataType(4)

                # Subscribe to PnL updates
                await self._subscribe_pnl()
                # Subscribe to Market Indices
                await self._subscribe_market_data()
                
            except Exception as e:
                logger.error(f"Failed to connect to IB: {e}")
                self._connected = False
                raise
    
    async def _subscribe_pnl(self):
        """Subscribe to PnL updates for the account"""
        if self._pnl_subscribed:
            return
            
        try:
            accounts = self.ib.managedAccounts()
            if accounts:
                account = accounts[0] if isinstance(accounts, list) else accounts.split(',')[0]
                self.ib.reqPnL(account)
                self._pnl_subscribed = True
                logger.info(f"Subscribed to PnL updates for account {account}")
        except Exception as e:
            logger.error(f"Failed to subscribe to PnL: {e}")

    async def _subscribe_market_data(self):
        """Subscribe to SPY and VIX market data"""
        try:
            spy = Stock('SPY', 'SMART', 'USD')
            vix = Index('VIX', 'CBOE')
            
            # Request market data (snapshot=False for streaming)
            # We assign to self so we can access ticker.marketPrice() later
            self.spy_ticker = self.ib.reqMktData(spy, '', False, False)
            self.vix_ticker = self.ib.reqMktData(vix, '', False, False)
            logger.info("Subscribed to SPY and VIX market data")
        except Exception as e:
            logger.error(f"Failed to subscribe to market data: {e}")

    async def get_market_indices(self) -> dict:
        """Get current prices for SPY and VIX"""
        try:
            # marketPrice() handles NaN/None gracefully usually returning last valid
            if self.spy_ticker:
                 spy_val = self.spy_ticker.marketPrice()
            elif self.ib.isConnected():
                 # Retry subscription if missing?
                 spy = Stock('SPY', 'SMART', 'USD')
                 self.spy_ticker = self.ib.reqMktData(spy, '', False, False)
                 spy_val = 0.0
            else:
                 spy_val = 0.0

            if self.vix_ticker:
                 vix_val = self.vix_ticker.marketPrice()
            elif self.ib.isConnected():
                 vix = Index('VIX', 'CBOE')
                 self.vix_ticker = self.ib.reqMktData(vix, '', False, False)
                 vix_val = 0.0
            else:
                 vix_val = 0.0
            
            # Check for nan
            
            # Helper to extract price and change
            def get_ticker_data(ticker):
                if not ticker: 
                    return {"value": 0.0, "change": 0.0}
                
                price = ticker.marketPrice()
                # 'close' is previous day's closing price in ib_insync Ticker
                prev_close = ticker.close
                
                if math.isnan(price): price = 0.0
                if math.isnan(prev_close): prev_close = 0.0
                
                change_pct = 0.0
                if price > 0 and prev_close > 0:
                    change_pct = ((price - prev_close) / prev_close) * 100.0
                    
                return {"value": price, "change": change_pct}

            spy_data = get_ticker_data(self.spy_ticker)
            vix_data = get_ticker_data(self.vix_ticker)
            
            return {
                "SPY": spy_data,
                "VIX": vix_data
            }
        except Exception as e:
            logger.error(f"Error getting indices: {e}")
            return {
                "SPY": {"value": 0.0, "change": 0.0}, 
                "VIX": {"value": 0.0, "change": 0.0}
            }

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
        logger.debug(f"Available account summary tags: {[t.tag for t in tags]}")
        
        summary = {t.tag: float(t.value) for t in tags if t.tag in ['NetLiquidation', 'BuyingPower', 'TotalCashValue', 'UnrealizedPnL', 'RealizedPnL', 'DailyPnL']}
        logger.debug(f"Account summary P&L values: RealizedPnL={summary.get('RealizedPnL', 'N/A')}, DailyPnL={summary.get('DailyPnL', 'N/A')}, UnrealizedPnL={summary.get('UnrealizedPnL', 'N/A')}")
        return summary

    async def get_daily_pnl(self) -> dict:
        """
        Get today's P&L using IB's reqPnL API.
        Returns dict with dailyPnL, unrealizedPnL, and realizedPnL.
        """
        if not self.ib.isConnected():
            await self.connect()
        
        # Ensure we're subscribed
        if not self._pnl_subscribed:
            await self._subscribe_pnl()
            # Wait for data to arrive
            await asyncio.sleep(0.5)
        
        try:
            # Get account number
            accounts = self.ib.managedAccounts()
            if not accounts:
                logger.error("No account found for PnL request")
                return {"dailyPnL": 0.0, "unrealizedPnL": 0.0, "realizedPnL": 0.0}
            
            account = accounts[0] if isinstance(accounts, list) else accounts.split(',')[0]
            
            # Get the latest PnL data
            pnl_list = self.ib.pnl(account)
            
            if pnl_list:
                pnl = pnl_list[0]
                result = {
                    "dailyPnL": float(pnl.dailyPnL) if pnl.dailyPnL is not None else 0.0,
                    "unrealizedPnL": float(pnl.unrealizedPnL) if pnl.unrealizedPnL is not None else 0.0,
                    "realizedPnL": float(pnl.realizedPnL) if pnl.realizedPnL is not None else 0.0
                }
                logger.debug(f"PnL data from IB API: {result}")
                return result
            else:
                logger.warning("No PnL data available from subscription")
                return {"dailyPnL": 0.0, "unrealizedPnL": 0.0, "realizedPnL": 0.0}
        
        except Exception as e:
            import traceback
            logger.error(f"Error getting daily PnL: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
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

    async def close_position(self, symbol: str):
        """Close a specific position by symbol"""
        if not self.ib.isConnected():
             await self.connect()
             
        positions = await self.get_all_positions()
        for pos in positions:
            if pos.contract.symbol == symbol:
                contract = pos.contract
                # Inverse action to close
                action = 'SELL' if pos.position > 0 else 'BUY'
                quantity = abs(pos.position)
                
                logger.info(f"Closing position for {symbol}: {action} {quantity}")
                order = MarketOrder(action, quantity)
                trade = self.ib.placeOrder(contract, order)
                return True
        
        logger.warning(f"No open position found for {symbol} to close.")
        return False

    async def get_market_status(self):
        """
        Check if the market is open using SPY contract details.
        Returns a dict with status ('open', 'closed', 'error') and reasoning.
        """
        if not self.ib.isConnected():
             # Fallback to settings check if not connected, or return unknown
            now = datetime.now(timezone.utc)
            is_open = settings.MARKET_OPEN_HOUR <= now.hour < settings.MARKET_CLOSE_HOUR
            return {
                "status": "open" if is_open else "closed", 
                "reason": "Not connected to IB, using local settings",
                "source": "local"
            }
            
        try:
            contract = Stock('SPY', 'SMART', 'USD')
            details_list = await self.ib.reqContractDetailsAsync(contract)
            if not details_list:
                return {"status": "unknown", "reason": "No contract details for SPY", "source": "ib"}
                
            details = details_list[0]
            # liquidHours format: 20231027:0930-1600;20231028:CLOSED
            liquid_hours = details.liquidHours
            time_zone_id = details.timeZoneId
            
            # IB uses specific timezone IDs, usually standardized
            try:
                tz = ZoneInfo(time_zone_id)
            except Exception:
                tz = ZoneInfo('US/Eastern') # Fallback
                
            now = datetime.now(tz)
            today_str = now.strftime('%Y%m%d')
            
            hours_list = liquid_hours.split(';')
            today_hours = None
            for h in hours_list:
                if h.startswith(today_str):
                    today_hours = h
                    break
            
            if not today_hours:
                 return {"status": "closed", "reason": "No hours found for today", "source": "ib"}
                 
            if "CLOSED" in today_hours:
                 return {"status": "closed", "reason": "Market Closed Today", "source": "ib"}
                 
            # Parse intervals: date:0930-1600,1615-1700
            # Remove date part
            # Parse intervals. today_hours example: "20260211:0930-20260211:1600" or "20231027:0930-1600"
            # Strategy: Split by comma (if multiple intervals), then split by hyphen.
            # Then parse each side.
            
            # First, strip the leading date if it exists in the simplified "Date:Intervals" format
            # But since we saw "Date:Time-Date:Time", simply splitting on first colon might be misleading if the first part is just one side of a range?
            # actually, usually it is "Date:Range". If Range is "Time-Date:Time", splitting on first colon is "Date" and "Time-Date:Time".
            # If Range is "Time-Time", split is "Date" and "Time-Time".
            
            # Let's try to remove all "YYYYMMDD:" prefixes to simplify? No, we need dates for accuracy.
            
            # Let's go back to looking at the substring AFTER the first colon, OR just parsing the full chunks if they look like dates.
            # However, `liquidHours` is semi-colon separated `Date:Ranges`.
            # So `today_hours` ensures we are looking at the chunk for today.
            
            # Split on the first colon to separate the "Date" key from the "Ranges".
            try:
                parts = today_hours.split(':', 1)
                if len(parts) == 2:
                    current_intervals_str = parts[1]
                else:
                    # Maybe it's just "CLOSED"? Handled above.
                    current_intervals_str = today_hours

                intervals = current_intervals_str.split(',')
                
                is_open = False
                
                def parse_dt(dt_str, default_date_str):
                    # dt_str can be "HHMM" or "YYYYMMDD:HHMM"
                    if ':' in dt_str:
                        d_str, t_str = dt_str.split(':')
                        return now.replace(year=int(d_str[:4]), month=int(d_str[4:6]), day=int(d_str[6:8]), 
                                         hour=int(t_str[:2]), minute=int(t_str[2:]), second=0, microsecond=0)
                    else:
                        # Use default date
                        return now.replace(year=int(default_date_str[:4]), month=int(default_date_str[4:6]), day=int(default_date_str[6:8]), 
                                         hour=int(dt_str[:2]), minute=int(dt_str[2:]), second=0, microsecond=0)

                # We need the date part from the key for defaults
                default_date_str = parts[0] if len(parts) == 2 else today_str

                readable_intervals = []
                for interval in intervals:
                    if '-' not in interval: continue
                    start_str, end_str = interval.split('-')
                    
                    start_dt = parse_dt(start_str, default_date_str)
                    end_dt = parse_dt(end_str, default_date_str)
                    
                    # Store readable format
                    readable_intervals.append(f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}")
                    
                    if start_dt <= now < end_dt:
                        is_open = True
                
                # Format timezone name nicely
                tz_name = now.tzname() or ""
                reason_msg = f"Hours: {', '.join(readable_intervals)} ({tz_name})".strip()
                        
                return {
                    "status": "open" if is_open else "closed", 
                    "reason": reason_msg,
                    "source": "ib"
                }

            except Exception as ve:
                 logger.error(f"Error parsing time string '{today_hours}': {ve}")
                 return {"status": "error", "reason": f"Parse Error: {ve}", "source": "error"}
                    


        except Exception as e:
            logger.error(f"Error checking market status: {e}")
            return {"status": "error", "reason": str(e), "source": "error"}
