import pytest
from core.signal_validator import validate_signal
from db.models import Signal

def test_valid_signal_action():
    json_str = '{"ticker": "AAPL", "action": "buy", "quantity": 100}'
    signal = validate_signal(json_str)
    assert isinstance(signal, Signal)
    assert signal.ticker == "AAPL"
    assert signal.action == "buy"
    assert signal.quantity == 100

def test_valid_signal_signal_key():
    json_str = '{"ticker": "KHC", "signal": "sell", "quantity": "100%"}'
    signal = validate_signal(json_str)
    assert signal.ticker == "KHC"
    assert signal.action == "sell"
    assert signal.quantity == "100%"

def test_invalid_json():
    with pytest.raises(ValueError):
        validate_signal("{invalid_json}")

def test_missing_ticker():
    json_str = '{"action": "buy", "quantity": 100}'
    with pytest.raises(ValueError, match="Schema validation failed"):
        validate_signal(json_str)

def test_invalid_action():
    json_str = '{"ticker": "AAPL", "action": "hold", "quantity": 100}'
    # Schema validation catches 'hold' not in enum
    with pytest.raises(ValueError, match="Schema validation failed"):
        validate_signal(json_str)

def test_extra_fields_ignored_but_valid():
    json_str = '{"ticker": "AAPL", "action": "buy", "quantity": 100, "extra": "data"}'
    signal = validate_signal(json_str)
    assert signal.ticker == "AAPL"
