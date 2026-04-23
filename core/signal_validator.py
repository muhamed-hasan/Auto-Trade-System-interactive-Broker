import json
import logging
from jsonschema import validate, ValidationError
from db.models import Signal
from config.settings import REQUIRED_SIGNAL_KEYS
from config import settings

logger = logging.getLogger(__name__)

# JSON Schema for validation
SIGNAL_SCHEMA = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "signal": {"type": "string", "enum": ["buy", "sell", "exit"]},
        "action": {"type": "string", "enum": ["buy", "sell", "exit"]},
        "quantity": {"type": ["number", "string"]},
        "trade_power": {"type": ["number", "string"]}, # Added trade_power
        "price": {"type": ["number", "string"]},
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
    # Normalize smart/curly quotes that Telegram or TradingView may inject
    raw_json = raw_json.replace('\u201c', '"').replace('\u201d', '"')  # smart double quotes
    raw_json = raw_json.replace('\u2018', "'").replace('\u2019', "'")  # smart single quotes
    raw_json = raw_json.replace('\u00ab', '"').replace('\u00bb', '"')  # guillemets
    raw_json = raw_json.strip()
    
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed. Raw text repr: {repr(raw_json[:200])}")
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
    if action not in ["buy", "sell", "exit"]:
         raise ValueError(f"Invalid action: {action}")
    
    if action == "exit":
        action = "sell"
        data["quantity"] = data.get("quantity", "100%")
    
    # Check for quantity OR trade_power
    quantity = data.get("quantity")
    trade_power = data.get("trade_power")
    
    if isinstance(trade_power, str) and trade_power.upper() == "N/A":
        trade_power = None
        
    if action == "buy" and not quantity and not trade_power:
        trade_power = settings.DEFAULT_TRADE_POWER
    
    if not quantity and not trade_power:
         raise ValueError("Must provide either 'quantity' or 'trade_power'")

    raw_price = data.get("price")
    try:
        parsed_price = float(raw_price) if raw_price is not None else None
    except ValueError:
        raise ValueError(f"Invalid price format: {raw_price}")

    # Create Signal object
    return Signal(
        ticker=data["ticker"].upper(),
        action=action,
        quantity=quantity,
        trade_power=str(trade_power) if trade_power else None,
        order_type=data.get("order_type", "market"),
        price=parsed_price,
        msg=data.get("msg"),
        raw_json=raw_json
    )
