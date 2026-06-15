import pytest
import time
from unittest.mock import patch, MagicMock
from core.risk_engine import RiskEngine
from db.models import Signal
from config import settings

@pytest.fixture
def risk_engine():
    mock_executor = MagicMock()
    from unittest.mock import AsyncMock
    mock_executor.get_market_status = AsyncMock(return_value={"status": "open"})
    return RiskEngine(mock_executor)

@pytest.fixture
def valid_signal():
    return Signal(
        ticker="AAPL",
        action="buy",
        quantity=10,
        price=150.0
    )

@pytest.fixture
def account_summary():
    # Mock account summary
    return {
        "NetLiquidation": 10000.0,
        "buying_power": 50000.0
    }

@pytest.mark.asyncio
async def test_market_closed(risk_engine, valid_signal, account_summary):
    # Mock get_market_status in the executor as AsyncMock
    from unittest.mock import AsyncMock
    risk_engine.order_executor.get_market_status = AsyncMock(return_value={"status": "closed", "reason": "Market Closed"})
    
    # Ensure we are not in paper mode to test strict hours
    with patch.object(settings, 'TRADING_MODE', 'live'):
        approved, reason = await risk_engine.evaluate(valid_signal, account_summary, [])
        assert not approved
        assert "Market is closed" in reason

@pytest.mark.asyncio
async def test_duplicate_signal(risk_engine, valid_signal, account_summary):
    # First signal - OK
    approved, _ = await risk_engine.evaluate(valid_signal, account_summary, [])
    assert approved
    
    # Immediate duplicate - Fail
    approved, reason = await risk_engine.evaluate(valid_signal, account_summary, [])
    assert not approved
    assert "Duplicate signal" in reason

@pytest.mark.asyncio
async def test_max_open_positions(risk_engine, valid_signal, account_summary):
    # Max is 100 (configured in settings.MAX_OPEN_POSITIONS)
    mock_pos = MagicMock()
    mock_pos.position = 10
    current_positions = [mock_pos] * 100
    approved, reason = await risk_engine.evaluate(valid_signal, account_summary, current_positions)
    assert not approved
    assert "Max open positions" in reason

@pytest.mark.asyncio
async def test_insufficient_buying_power(risk_engine, valid_signal, account_summary):
    # Signal cost 10 * 150 = 1500. BP is 50000. OK.
    # Let's make signal huge
    valid_signal.quantity = 1000 
    valid_signal.price = 100.0 # 100,000 cost
    
    approved, reason = await risk_engine.evaluate(valid_signal, account_summary, [])
    assert not approved
    assert "Insufficient buying power" in reason

@pytest.mark.asyncio
async def test_percentage_quantity(risk_engine, account_summary):
    signal = Signal(ticker="AAPL", action="buy", quantity="50%", price=None)
    
    # 50% of 10000 equity = 5000. BP is 50000. OK.
    approved, _ = await risk_engine.evaluate(signal, account_summary, [])
    assert approved
    
    # Clear duplicate cache to allow next signal
    risk_engine.recent_signals.clear()
    
    # 600% of equity = 60000 > 50000 BP. Fail.
    signal.quantity = "600%"
    approved, reason = await risk_engine.evaluate(signal, account_summary, [])
    assert not approved
    assert "Insufficient buying power" in reason
