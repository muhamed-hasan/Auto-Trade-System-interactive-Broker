import logging
import time
from datetime import datetime, timezone
from typing import List, Tuple, Optional
from db.models import Signal, Order
from config import settings

logger = logging.getLogger(__name__)

class RiskEngine:
    def __init__(self):
        # Cache for duplicate signal check: {(ticker, action): timestamp}
        self.recent_signals = {}
    
    def evaluate(self, signal: Signal, account_summary: dict, open_positions: List) -> Tuple[bool, str]:
        """
        Evaluates a signal against risk rules.
        Returns (approved, reason).
        """
        
        # 1. Trading Hours
        if not self._is_market_open():
             if settings.TRADING_MODE != 'paper': # Allow off-hours in paper? Maybe.
                 return False, "Market is closed"

        # 2. Duplicate Signal Check
        if self._is_duplicate(signal):
            return False, f"Duplicate signal for {signal.ticker} within cooldown"
        
        # 3. Max Open Positions
        # If open positions + pending orders >= MAX, reject new OPENING orders
        # Allow closing orders (sell if we hold, buy if short)
        # For simplicity, assume 'buy' increases exposure, 'sell' decreases (long only for now)
        if signal.action == 'buy':
            if len(open_positions) >= settings.MAX_OPEN_POSITIONS:
                return False, f"Max open positions reached ({settings.MAX_OPEN_POSITIONS})"

        # 4. Buying Power Check
        # Requires estimating cost. If quantity is %, we need account equity.
        cost_estimate = self._estimate_cost(signal, account_summary)
        if cost_estimate > account_summary.get('buying_power', float('inf')):
             return False, f"Insufficient buying power (Estimated: {cost_estimate})"

        # 5. Max Risk / Daily Loss
        # This requires PnL engine status. For now, pass.
        # check_daily_loss(pnl_engine.current_daily_pnl)

        # Update cache on approval
        self.recent_signals[(signal.ticker, signal.action)] = time.time()
        
        return True, "Approved"

    def _is_market_open(self) -> bool:
        # Simple check based on settings (UTC)
        # TODO: Use IB contract details for improved accuracy
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        return settings.MARKET_OPEN_HOUR <= current_hour < settings.MARKET_CLOSE_HOUR

    def _is_duplicate(self, signal: Signal) -> bool:
        key = (signal.ticker, signal.action)
        last_time = self.recent_signals.get(key)
        if last_time:
            if time.time() - last_time < settings.SYMBOL_COOLDOWN_SECONDS:
                return True
        return False

    def _estimate_cost(self, signal: Signal, account_summary: dict) -> float:
        # Check trade_power first
        if signal.trade_power:
             try:
                 return float(signal.trade_power)
             except ValueError:
                 return 0

        # If quantity is percentage string, calculate based on equity
        if isinstance(signal.quantity, str) and signal.quantity.endswith('%'):
            pct = float(signal.quantity.strip('%')) / 100.0
            equity = account_summary.get('NetLiquidation', 0) # Fixed key from 'equity'
            return equity * pct
            
        # If numeric quantity
        if signal.quantity is None:
             return 0
             
        price = signal.price or 0
        try:
            qty = float(signal.quantity)
        except ValueError:
             return 0
        return qty * price
