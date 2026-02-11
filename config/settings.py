import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# --- Project Paths ---
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "trading_bot.db"

# --- IB Connection ---
IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
IB_PORT = int(os.getenv("IB_PORT", "4002"))  # 4002 for Gateway
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))

# --- Telegram ---
TELEGRAM_SIGNAL_BOT_TOKEN = os.getenv("TELEGRAM_SIGNAL_BOT_TOKEN")
TELEGRAM_CONTROL_BOT_TOKEN = os.getenv("TELEGRAM_CONTROL_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = int(os.getenv("TELEGRAM_CHANNEL_ID", "0"))
TELEGRAM_WHITELIST_IDS = [int(id_str) for id_str in os.getenv("TELEGRAM_WHITELIST_IDS", "").split(",") if id_str]

# --- Trading Mode ---
# Options: 'paper', 'live'
TRADING_MODE = os.getenv("TRADING_MODE", "paper").lower()

# --- Risk Management Settings ---
MAX_RISK_PER_TRADE_PERCENT = 0.02  # 2% of equity
MAX_OPEN_POSITIONS = 20
MAX_DAILY_LOSS_PERCENT = 0.05      # 5% of daily starting equity accounts for a kill switch
SYMBOL_COOLDOWN_SECONDS = 300      # 5 minutes cooldown between same-symbol trades
ORDER_THROTTLE_SECONDS = 60        # Max 1 order per minute per symbol? Or system wide? Let's say system wide check for burst.

# --- Trading Hours (UTC) ---
# Simple market hours check, can be expanded for specific exchanges
MARKET_OPEN_HOUR = 13  # 9:00 AM EST is roughly 14:00 UTC (varies by DST) - this needs a better robust check, maybe utilize IB contract details
MARKET_CLOSE_HOUR = 20 # 4:00 PM EST is roughly 21:00 UTC

# --- Signal Validation ---
REQUIRED_SIGNAL_KEYS = {"ticker", "action", "quantity"}
VALID_ACTIONS = {"buy", "sell"}
