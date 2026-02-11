# AutoTrade System 🤖📈

AutoTrade is a robust, asynchronous automated trading bot designed to execute trading signals received via Telegram directly to Interactive Brokers (IBKR). It features a unified Telegram interface for both signal listening and system control, ensuring seamless operation and real-time management.

## 🚀 Key Features

*   **Telegram Integration**:
    *   **Signal Listener**: Automatically parses JSON-formatted buy/sell signals from a specified Telegram channel.
    *   **Control Panel**: Interactive dashboard to monitor and control the bot (Profile, PnL, Positions, Pause/Resume).
    *   **Unified Instance**: Runs a single bot instance to avoid polling conflicts.
*   **Smart Order Execution**:
    *   Connects to Interactive Brokers via `ib_insync`.
    *   Supports **Market** and **Limit** orders.
    *   **Flexible Sizing**: Accepts specific share counts, percentage of equity (`quantity: "50%"`), or dollar amount (`trade_power: "500"`).
*   **Risk Management**:
    *   Validates signals against trading hours.
    *   Checks for sufficient buying power.
    *   Prevents duplicate signals (cooldown timer).
    *   Enforces maximum open positions limits.
*   **Robustness**:
    *   Automatic reconnection logic for IBKR.
    *   SQLite database for persistent logging of signals, orders, and trades.
    *   Graceful shutdown and error handling.

## 🛠️ Architecture

*   **Language**: Python 3.11+
*   **Broker API**: `ib_insync` (Async IO wrapper for IB API)
*   **Messaging**: `python-telegram-bot`
*   **Database**: `aiosqlite` (Async SQLite)
*   **Architecture**: Event-driven, asynchronous loop managing polling, execution, and risk checks concurrently.

## 📋 Prerequisites

1.  **Interactive Brokers Account**: IB Gateway or TWS (Trader Workstation) must be installed and running.
2.  **Python 3.11** or higher.
3.  **Telegram Bot**:
    *   Create a bot via @BotFather.
    *   Obtain the Bot Token.
    *   Get your Telegram User ID (for the whitelist).
    *   (Optional) Create a Channel for signals and get its ID.

## ⚙️ Installation

1.  **Clone the Repository**
    ```bash
    git clone <repository-url>
    cd autoTrade
    ```

2.  **Set Up Virtual Environment**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configuration**
    *   Create a `.env` file in the `config/` directory (or root, depending on setup) with the following structure:
        ```env
        # IB Connection
        IB_HOST=127.0.0.1
        IB_PORT=4002  # 7497 for TWS paper, 4002 for Gateway paper
        IB_CLIENT_ID=1

        # Telegram
        TELEGRAM_SIGNAL_BOT_TOKEN=your_bot_token_here
        TELEGRAM_CONTROL_BOT_TOKEN=your_bot_token_here # Can be same as signal token
        TELEGRAM_CHANNEL_ID=-100xxxxxxxxx
        TELEGRAM_WHITELIST_IDS=12345678,87654321

        # Trading Mode
        TRADING_MODE=paper
        ```
    *   Adjust `config/settings.py` for advanced settings like Trading Hours, Risk Limits, etc.

## 🚀 Usage

1.  **Start IB Gateway/TWS**
    *   Ensure API connections are enabled.
    *   Check "Allow connections from localhost only" is trusted or unchecked if needed.

2.  **Run the Bot**
    ```bash
    python main.py
    ```

3.  **Control via Telegram**
    *   Open a private chat with your bot.
    *   Send the command `/start`.
    *   Use the interactive buttons:
        *   **📊 Profile**: View Account Equity & Buying Power.
        *   **📈 Today PnL**: View Realized & Unrealized PnL.
        *   **📜 Open Positions**: List current holdings.
        *   **⏸ Pause / ▶️ Resume**: control signal processing.

## 📡 Signal Format

Send signals to your configured Telegram Channel. The bot listens for JSON objects.

**Example 1: Buy by Dollar Amount (Trade Power)**
```json
{
  "ticker": "AAPL",
  "signal": "buy",
  "trade_power": "1000",
  "type": "orb",
  "msg": "Buying $1000 worth of Apple"
}
```

**Example 2: Buy by Percentage of Equity**
```json
{
  "ticker": "TSLA",
  "action": "buy",
  "quantity": "10%",
  "order_type": "market"
}
```

**Example 3: Sell Specific Quantity with Limit Price**
```json
{
  "ticker": "NVDA",
  "action": "sell",
  "quantity": 50,
  "order_type": "limit",
  "price": 450.00
}
```

## ⚠️ Disclaimer

This software is for educational purposes only. Do not risk money which you are afraid to lose. USE THE SOFTWARE AT YOUR OWN RISK. THE AUTHORS AND CONTRIBUTORS ASSUME NO RESPONSIBILITY FOR YOUR TRADING RESULTS.

---

# 🇸🇦 نظام التداول الآلي (AutoTrade)

نظام AutoTrade هو بوت تداول آلي قوي ومبني بلغة بايثون، مصمم لتنفيذ إشارات التداول المستلمة عبر تيليجرام مباشرة في حساب Interactive Brokers (IBKR). يتميز بواجهة تيليجرام موحدة للاستماع للإشارات والتحكم في النظام، مما يضمن التشغيل السلس والإدارة في الوقت الفعلي.

## 🚀 الميزات الرئيسية

*   **تكامل مع تيليجرام**:
    *   **مستمع الإشارات**: يقوم تلقائيًا بتحليل إشارات الشراء/البيع المنسقة بصيغة JSON من قناة تيليجرام محددة.
    *   **لوحة التحكم**: لوحة تفاعلية لمراقبة والتحكم في البوت (الملف الشخصي، الأرباح والخسائر، المراكز المفتوحة، إيقاف مؤقت/استئناف).
    *   **بوت موحد**: يعمل كنسخة واحدة لتجنب تعارض الاتصال (polling conflict).
*   **تنفيذ ذكي للأوامر**:
    *   يتصل بـ Interactive Brokers عبر مكتبة `ib_insync`.
    *   يدعم أوامر **السوق (Market)** و **الحد (Limit)**.
    *   **تحديد حجم مرن**: يقبل عدد أسهم محدد، أو نسبة مئوية من رأس المال (`quantity: "50%"`), أو مبلغ دولاري (`trade_power: "500"`).
*   **إدارة المخاطر**:
    *   التحقق من ساعات التداول.
    *   التحقق من القوة الشرائية الكافية.
    *   منع تكرار الإشارات (مؤقت التهدئة).
    *   فرض حدود قصوى لعدد المراكز المفتوحة.
*   **الموثوقية**:
    *   منطق إعادة الاتصال التلقائي بـ IBKR.
    *   قاعدة بيانات SQLite لتسجيل الإشارات والأوامر والصفقات.
    *   إغلاق سلس ومعالجة للأخطاء.

## 📋 المتطلبات

1.  حساب **Interactive Brokers**: يجب تثبيت وتشغيل IB Gateway أو TWS.
2.  **Python 3.11** أو أحدث.
3.  **بوت تيليجرام**:
    *   أنشئ بوت عبر BotFather.
    *   احصل على التوكن (Bot Token).
    *   احصل على المعرف الخاص بك (User ID) لإضافته للقائمة البيضاء.
    *   (اختياري) أنشئ قناة للإشارات واحصل على معرفها (Channel ID).

## ⚙️ التثبيت والإعداد

1.  **نسخ المستودع (Clone)**
    ```bash
    git clone <repository-url>
    cd autoTrade
    ```

2.  **إعداد البيئة الافتراضية**
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # لنظام Mac/Linux
    ```

3.  **تثبيت المكتبات**
    ```bash
    pip install -r requirements.txt
    ```

4.  **الإعداد (Configuration)**
    *   أنشئ ملف `.env` في مجلد `config/` (أو المجلد الرئيسي) وضع فيه البيانات التالية:
        ```env
        # IB Connection
        IB_HOST=127.0.0.1
        IB_PORT=4002  # استخدم 7497 لـ TWS paper أو 4002 لـ Gateway paper
        IB_CLIENT_ID=1

        # Telegram
        TELEGRAM_SIGNAL_BOT_TOKEN=ضع_توكن_البوت_هنا
        TELEGRAM_CONTROL_BOT_TOKEN=ضع_نفس_التوكن_هنا
        TELEGRAM_CHANNEL_ID=-100xxxxxxxxx
        TELEGRAM_WHITELIST_IDS=12345678,87654321

        # Trading Mode
        TRADING_MODE=paper
        ```

## 🚀 الاستخدام

1.  **شغل IB Gateway/TWS**
    *   تأكد من تفعيل اتصالات API.
    *   تأكد من إلغاء تحديد "Read-Only API" إذا كنت تريد التداول الفعلي.

2.  **شغل البوت**
    ```bash
    python main.py
    ```

3.  **التحكم عبر تيليجرام**
    *   افتح محادثة خاصة مع البوت الخاص بك.
    *   أرسل الأمر `/start`.
    *   استخدم الأزرار التفاعلية:
        *   **📊 Profile**: عرض رصيد الحساب والقوة الشرائية.
        *   **📈 Today PnL**: عرض الأرباح والخسائر المحققة وغير المحققة لليوم.
        *   **📜 Open Positions**: عرض قائمة الصفقات المفتوحة حالياً.
        *   **⏸ Pause / ▶️ Resume**: لإيقاف أو استئناف معالجة الإشارات الجديدة.

## 📡 تنسيق الإشارة (Signal Format)

أرسل الإشارات إلى قناة تيليجرام التي قمت بإعدادها بصيغة JSON.

**مثال 1: شراء بمبلغ دولاري محدد (Trade Power)**
```json
{
  "ticker": "AAPL",
  "signal": "buy",
  "trade_power": "1000",
  "type": "orb",
  "msg": "شراء بقيمة 1000 دولار من سهم أبل"
}
```

**مثال 2: شراء بنسبة مئوية من رأس المال**
```json
{
  "ticker": "TSLA",
  "action": "buy",
  "quantity": "10%",
  "order_type": "market"
}
```

## ⚠️ إخلاء مسؤولية

هذا البرنامج للأغراض التعليمية فقط. لا تخاطر بأموال لا يمكنك تحمل خسارتها. استخدامك لهذا البرنامج هو على مسؤوليتك الخاصة. المطورون والمساهمون لا يتحملون أي مسؤولية عن نتائج تداولك.
# Auto-Trade-System-interactive-Broker-
