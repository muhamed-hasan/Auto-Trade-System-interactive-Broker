import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from core.order_executor import OrderExecutor
from db.models import Signal
from ib_insync import Contract, Stock, Trade as IBTrade
from ib_insync.objects import AccountValue, Position

@pytest.fixture
def order_executor():
    # Base fixture setup
    with patch('core.order_executor.IB') as mock_ib_cls:
        executor = OrderExecutor()
        # By default use MagicMock for the IB instance
        executor.ib = MagicMock()
        # Explicitly mock async methods used generally
        executor.ib.connectAsync = AsyncMock()
        executor.ib.qualifyContractsAsync = AsyncMock()
        executor.ib.accountSummaryAsync = AsyncMock()
        executor.ib.reqTickersAsync = AsyncMock()
        executor.ib.reqPositionsAsync = AsyncMock()
        return executor

@pytest.mark.asyncio
async def test_connect(order_executor):
    # Setup for this test
    order_executor.ib.isConnected.return_value = False
    
    await order_executor.connect()
    
    order_executor.ib.connectAsync.assert_called_once()
    assert order_executor._connected

@pytest.mark.asyncio
async def test_execute_order_market_numeric(order_executor):
    signal = Signal(ticker="AAPL", action="buy", quantity=10)
    
    contract = Stock("AAPL", "SMART", "USD")
    order_executor.ib.qualifyContractsAsync.return_value = [contract]
    
    # Mock placeOrder (sync, returns Trade immediately)
    mock_trade = MagicMock(spec=IBTrade)
    order_executor.ib.placeOrder.return_value = mock_trade
    
    await order_executor.execute_order(signal)
    
    order_executor.ib.placeOrder.assert_called_once()
    args, _ = order_executor.ib.placeOrder.call_args
    assert args[0] == contract
    assert args[1].action == "BUY"
    assert args[1].totalQuantity == 10.0
    assert args[1].orderType == "MKT"

@pytest.mark.asyncio
async def test_execute_order_limit(order_executor):
    signal = Signal(ticker="AAPL", action="buy", quantity=10, order_type="limit", price=150.0)
    
    contract = Stock("AAPL", "SMART", "USD")
    order_executor.ib.qualifyContractsAsync.return_value = [contract]
    order_executor.ib.placeOrder.return_value = MagicMock(spec=IBTrade)

    await order_executor.execute_order(signal)
    
    args, _ = order_executor.ib.placeOrder.call_args
    assert args[1].orderType == "LMT"
    assert args[1].lmtPrice == 150.0

@pytest.mark.asyncio
async def test_calculate_quantity_percentage_buy(order_executor):
    signal = Signal(ticker="AAPL", action="buy", quantity="50%")
    
    av = AccountValue('DU123', 'NetLiquidation', '10000', 'USD', '')
    order_executor.ib.accountSummaryAsync.return_value = [av]
    
    mock_ticker = MagicMock()
    mock_ticker.marketPrice.return_value = 100.0
    order_executor.ib.reqTickersAsync.return_value = [mock_ticker]
    
    qty = await order_executor._calculate_quantity(signal)
    assert qty == 50

@pytest.mark.asyncio
async def test_calculate_quantity_percentage_sell(order_executor):
    signal = Signal(ticker="AAPL", action="sell", quantity="50%")
    
    contract = Stock("AAPL", "SMART", "USD")
    pos = Position(account='DU123', contract=contract, position=100.0, avgCost=140.0)
    order_executor.ib.reqPositionsAsync.return_value = [pos]
    
    qty = await order_executor._calculate_quantity(signal)
    assert qty == 50
