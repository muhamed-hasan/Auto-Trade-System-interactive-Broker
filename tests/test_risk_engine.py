import pytest
import time
from unittest.mock import patch, MagicMock
from core.risk_engine import RiskEngine
from db.models import Signal
from config import settings

@pytest.fixture
def risk_engine():
    return RiskEngine()

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

def test_market_closed(risk_engine, valid_signal, account_summary):
    with patch("core.risk_engine.datetime") as mock_datetime:
        # Set time to 22:00 (closed if close is 20:00)
        mock_now = MagicMock()
        mock_now.hour = 22
        mock_datetime.now.return_value = mock_now
        
        # Ensure we are not in paper mode to test strict hours
        with patch.object(settings, 'TRADING_MODE', 'live'):
            approved, reason = risk_engine.evaluate(valid_signal, account_summary, [])
            assert not approved
            assert "Market is closed" in reason

def test_duplicate_signal(risk_engine, valid_signal, account_summary):
    with patch("core.risk_engine.datetime") as mock_datetime:
        mock_now = MagicMock()
        mock_now.hour = 14  # Open
        mock_datetime.now.return_value = mock_now
        
        # First signal - OK
        approved, _ = risk_engine.evaluate(valid_signal, account_summary, [])
        assert approved
        
        # Immediate duplicate - Fail
        approved, reason = risk_engine.evaluate(valid_signal, account_summary, [])
        assert not approved
        assert "Duplicate signal" in reason

def test_max_open_positions(risk_engine, valid_signal, account_summary):
    with patch("core.risk_engine.datetime") as mock_datetime:
        mock_now = MagicMock()
        mock_now.hour = 14
        mock_datetime.now.return_value = mock_now
        
        # Max is 5
        current_positions = ["POS"] * 5
        approved, reason = risk_engine.evaluate(valid_signal, account_summary, current_positions)
        assert not approved
        assert "Max open positions" in reason

def test_insufficient_buying_power(risk_engine, valid_signal, account_summary):
    with patch("core.risk_engine.datetime") as mock_datetime:
        mock_now = MagicMock()
        mock_now.hour = 14
        mock_datetime.now.return_value = mock_now
        
        # Signal cost 10 * 150 = 1500. BP is 50000. OK.
        # Let's make signal huge
        valid_signal.quantity = 1000 
        valid_signal.price = 100.0 # 100,000 cost
        
        approved, reason = risk_engine.evaluate(valid_signal, account_summary, [])
        assert not approved
        assert "Insufficient buying power" in reason

def test_percentage_quantity(risk_engine, account_summary):
    signal = Signal(ticker="AAPL", action="buy", quantity="50%", price=None)
    
    with patch("core.risk_engine.datetime") as mock_datetime:
        mock_now = MagicMock()
        mock_now.hour = 14
        mock_datetime.now.return_value = mock_now

        # 50% of 10000 equity = 5000. BP is 50000. OK.
        approved, _ = risk_engine.evaluate(signal, account_summary, [])
        assert approved
        
        # Clear duplicate cache to allow next signal
        risk_engine.recent_signals.clear()
        
        # 600% of equity = 60000 > 50000 BP. Fail.
        signal.quantity = "600%"
        approved, reason = risk_engine.evaluate(signal, account_summary, [])
        assert not approved
        assert "Insufficient buying power" in reason
