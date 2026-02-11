import json
import logging
from jsonschema import validate, ValidationError
from db.models import Signal
from config.settings import REQUIRED_SIGNAL_KEYS

logger = logging.getLogger(__name__)

# JSON Schema for validation
SIGNAL_SCHEMA = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "signal": {"type": "string", "enum": ["buy", "sell"]},
        "action": {"type": "string", "enum": ["buy", "sell"]},
        "quantity": {"type": ["number", "string"]},
        "trade_power": {"type": ["number", "string"]}, # Added trade_power
        "price": {"type": "number"},
        "msg": {"type": "string"},
        "order_type": {"type": "string", "enum": ["market", "limit"]},
        "type": {"type": "string"},
        "trail": {"type": "string"},
        "auto_close": {"type": "string"}
    },
    "anyOf": [
        {"required": ["ticker", "signal"]},
        {"required": ["ticker", "action"]}
    ]
}

def validate_signal(raw_json: str) -> Signal:
    """
    Parses and validates a JSON string, returning a normalized Signal object.
    Raises ValueError if validation fails.
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format: {e}")

    try:
        validate(instance=data, schema=SIGNAL_SCHEMA)
    except ValidationError as e:
        raise ValueError(f"Schema validation failed: {e.message}")

    # Normalize keys
    action = data.get("action") or data.get("signal")
    if not action:
        raise ValueError("Missing 'action' or 'signal' field")
    
    action = action.lower()
    if action not in ["buy", "sell"]:
         raise ValueError(f"Invalid action: {action}")
    
    # Check for quantity OR trade_power
    quantity = data.get("quantity")
    trade_power = data.get("trade_power")
    
    if not quantity and not trade_power:
         raise ValueError("Must provide either 'quantity' or 'trade_power'")

    # Create Signal object
    return Signal(
        ticker=data["ticker"].upper(),
        action=action,
        quantity=quantity,
        trade_power=str(trade_power) if trade_power else None,
        order_type=data.get("order_type", "market"),
        price=data.get("price"),
        msg=data.get("msg"),
        raw_json=raw_json
    )
