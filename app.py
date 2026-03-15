import requests
import time
import random
from datetime import datetime, timedelta
import threading
import json
import pytz
import pandas as pd
import numpy as np
import os
from flask import Flask

# ======================== CONFIGURATION ========================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TWELVE_DATA_API_KEY = os.environ.get('TWELVE_DATA_API_KEY')
POCKET_OPTION_EMAIL = os.environ.get('POCKET_OPTION_EMAIL')
POCKET_OPTION_PASSWORD = os.environ.get('POCKET_OPTION_PASSWORD')

# Trading pairs list
PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD",
    "EUR/GBP", "EUR/JPY", "GBP/JPY", "AUD/JPY", "NZD/USD",
    "AUD/CAD (OTC)", "AUD/CHF (OTC)", "AUD/JPY (OTC)", "AUD/NZD (OTC)", 
    "CAD/CHF (OTC)", "CAD/JPY (OTC)", "CHF/JPY (OTC)", 
    "EUR/AUD (OTC)", "EUR/CAD (OTC)", "EUR/CHF (OTC)",
    "EUR/GBP (OTC)", "EUR/JPY (OTC)", "EUR/NZD (OTC)",
    "GBP/AUD (OTC)", "GBP/CAD (OTC)", "GBP/CHF (OTC)", 
    "GBP/JPY (OTC)", "GBP/USD (OTC)", "NZD/CAD (OTC)",
    "NZD/CHF (OTC)", "NZD/JPY (OTC)", "NZD/USD (OTC)",
    "USD/CAD (OTC)", "USD/CHF (OTC)", "USD/CNH (OTC)",
    "USD/JPY (OTC)", "USD/MXN (OTC)", "USD/NOK (OTC)", "USD/SEK (OTC)"
]

# ======================== STATISTICS ========================
statistics = {"win": 0, "loss": 0, "total": 0, "win_rate": 0}
active_signals = {}

# ======================== POCKET OPTION CONNECTION ========================
try:
    from pocketoptionapi.stable_api import PocketOption
    PO_AVAILABLE = True
except ImportError:
    print("⚠️ PocketOptionAPI not installed. Automatic trading disabled.")
    PO_AVAILABLE = False

po_api = None
po_connected = False

def connect_pocket_option():
    """Connect to Pocket Option account"""
    global po_api, po_connected
    
    if not PO_AVAILABLE:
        return False
    
    if not POCKET_OPTION_EMAIL or not POCKET_OPTION_PASSWORD:
        print("⚠️ Pocket Option credentials not available")
        return False
    
    try:
        po_api = PocketOption(POCKET_OPTION_EMAIL, POCKET_OPTION_PASSWORD, demo=True)
        po_api.connect()
        time.sleep(3)
        
        if po_api.check_connect():
            po_connected = True
            print("✅ Connected to Pocket Option")
            return True
        else:
            print("❌ Failed to connect to Pocket Option")
            return False
    except Exception as e:
        print(f"❌ Pocket Option connection error: {e}")
        return False

def pocket_option_trade(pair, signal, amount=10, expiration=60):
    """Execute a trade on Pocket Option and return result"""
    global po_api, po_connected
    
    if not po_connected:
        if not connect_pocket_option():
            return None
    
    try:
        # Convert pair name
        pair_po = pair.replace("/", "").replace(" (OTC)", "_otc")
        
        # Convert signal
        action = "call" if signal == "BUY" else "put"
        
        # Place order
        result = po_api.buy(
            amount=amount,
            active=pair_po,
            action=action,
            expirations=expiration
        )
        
        if result["success"]:
            order_id = result["order_id"]
            print(f"✅ Order placed: {order_id}")
            
            # Wait for trade to complete
            time.sleep(expiration + 5)
            
            # Check result
            trade_result = po_api.check_win(order_id)
            return trade_result
        else:
            print(f"❌ Order failed: {result}")
            return None
            
    except Exception as e:
        print(f"❌ Trade error: {e}")
        return None

# ======================== NEW YORK TIME FUNCTIONS ========================
def get_new_york_time():
    ny_tz = pytz.timezone('America/New_York')
    ny_time = datetime.now(ny_tz)
    return ny_time

def format_ny_time():
    ny_time = get_new_york_time()
    return ny_time.strftime("%H:%M:%S")

# ======================== TWELVE DATA API FUNCTIONS ========================
def get_twelve_data(pair):
    """Get market data from Twelve Data API"""
    if "(OTC)" in pair:
        pair = pair.replace(" (OTC)", "")
    
    url = f"https://api.twelvedata.com/time_series"
    params = {
        "symbol": pair,
        "interval": "1min",
        "outputsize": 50,
        "apikey": TWELVE_DATA_API_KEY
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if "values" in data:
            df = pd.DataFrame(data["values"])
            df = df.iloc[::-1]  # Reverse for chronological order
            df['close'] = pd.to_numeric(df['close'])
            df['high'] = pd.to_numeric(df['high'])
            df['low'] = pd.to_numeric(df['low'])
            return df
        elif "code" in data and data["code"] == 429:
            return "limit"
        else:
            return None
    except Exception as e:
        print(f"❌ Twelve Data API error: {e}")
        return None

def calculate_rsi(data, period=14):
    """Calculate RSI (Relative Strength Index)"""
    close = data['close']
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(data):
    """Calculate MACD"""
    exp1 = data['close'].ewm(span=12, adjust=False).mean()
    exp2 = data['close'].ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    histogram = macd - signal
    return macd, signal, histogram

def detect_signal(data):
    """Detect BUY or SELL signal based on technical indicators"""
    
    if data is None or len(data) < 20:
        return random.choice(["BUY", "SELL"]), 60, "Limited data"
    
    # Calculate indicators
    rsi = calculate_rsi(data)
    macd, signal, hist = calculate_macd(data)
    
    # Latest values
    last_rsi = rsi.iloc[-1] if len(rsi) > 0 else 50
    prev_rsi = rsi.iloc[-2] if len(rsi) > 1 else 50
    
    last_hist = hist.iloc[-1] if len(hist) > 0 else 0
    prev_hist = hist.iloc[-2] if len(hist) > 1 else 0
    
    # Current price
    current_price = data['close'].iloc[-1]
    prev_price = data['close'].iloc[-2] if len(data) > 1 else current_price
    
    # BUY signal conditions
    if last_rsi < 40:
        confidence = 75
        if last_hist > prev_hist:
            confidence = 85
            return "BUY", confidence, f"RSI {last_rsi:.1f} (oversold) + MACD bullish crossover"
        elif current_price > prev_price:
            return "BUY", 70, f"RSI {last_rsi:.1f} (oversold) + Price rising"
        else:
            return "BUY", 65, f"RSI {last_rsi:.1f} (oversold)"
    
    # SELL signal conditions
    elif last_rsi > 60:
        confidence = 75
        if last_hist < prev_hist:
            confidence = 85
            return "SELL", confidence, f"RSI {last_rsi:.1f} (overbought) + MACD bearish crossover"
        elif current_price < prev_price:
            return "SELL", 70, f"RSI {last_rsi:.1f} (overbought) + Price falling"
        else:
            return "SELL", 65, f"RSI {last_rsi:.1f} (overbought)"
    
    # Neutral market - use price action
    else:
        if current_price > prev_price:
            return "BUY", 55, f"RSI {last_rsi:.1f} - Price rising"
        else:
            return "SELL", 55, f"RSI {last_rsi:.1f} - Price falling"

def generate_signal(selected_pair=None):
    """Generate signal based on real market data"""
    
    if selected_pair:
        pair = selected_pair
    else:
        pair = random.choice(PAIRS)
    
    # Get market data
    data = get_twelve_data(pair)
    
    if data == "limit":
        signal = random.choice(["BUY", "SELL"])
        confidence = 50
        reason = "API limit reached - Random signal"
        return pair, signal, confidence, reason
    elif data is None or len(data) < 20:
        signal = random.choice(["BUY", "SELL"])
        confidence = random.randint(60, 70)
        reason = "Limited data - Technical analysis not available"
        return pair, signal, confidence, reason
    
    # Detect signal
    signal, confidence, reason = detect_signal(data)
    
    return pair, signal, confidence, reason

# ======================== TELEGRAM FUNCTIONS ========================
def send_message(chat_id, text, buttons=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if buttons:
        data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    
    try:
        response = requests.post(url, json=data, timeout=10)
        if response.status_code != 200:
            print(f"Telegram API error: {response.text}")
        return True
    except Exception as e:
        print(f"Error sending message: {e}")
        return False

def edit_message(chat_id, message_id, text, buttons=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if buttons:
        data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Error editing message: {e}")

def send_signal_with_preparation(chat_id, message_id, pair, signal, confidence, reason):
    """Send signal with 1 minute preparation time"""
    
    current_time = get_new_york_time()
    entry_time = current_time + timedelta(minutes=1)
    close_time = entry_time + timedelta(minutes=1)
    
    current_time_str = current_time.strftime("%H:%M:%S")
    entry_time_str = entry_time.strftime("%H:%M:%S")
    close_time_str = close_time.strftime("%H:%M:%S")
    
    signal_emoji = "🟢" if signal == "BUY" else "🔴"
    
    # Store signal information
    signal_id = f"{chat_id}_{message_id}"
    active_signals[signal_id] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "pair": pair,
        "signal": signal,
        "entry_time": entry_time_str,
        "close_time": close_time_str,
        "confidence": confidence
    }
    
    # FIRST MESSAGE: 1 minute warning
    preparation_message = f"""⚠️ *SIGNAL ALERT* ⚠️

━━━━━━━━━━━━━━━━━━━
**{pair}**
{signal_emoji} Signal: *{signal}*
📊 Confidence: {confidence}%
📌 Reason: {reason}
━━━━━━━━━━━━━━━━━━━

🕐 *New York Time:* {current_time_str}
⏳ *Entry Time:* {entry_time_str}
⌛️ *Close Time:* {close_time_str}

━━━━━━━━━━━━━━━━━━━
🔥 *PREPARE NOW!*
📱 Open Pocket Option
💰 Prepare your trade amount

*Countdown starts in 1 minute...* ⏱️"""
    
    edit_message(chat_id, message_id, preparation_message)
    time.sleep(60)
    
    # SECOND MESSAGE: 60 second countdown
    for i in range(60, 0, -1):
        current_time = get_new_york_time()
        entry_time_str = (current_time + timedelta(seconds=i)).strftime("%H:%M:%S")
        
        text = f"""🚨 *DFG2K TRADING SIGNAL* 🚨

━━━━━━━━━━━━━━━━━━━
**{pair}**
{signal_emoji} Signal: *{signal}*
📊 Confidence: {confidence}%
📌 Reason: {reason}
━━━━━━━━━━━━━━━━━━━

⏳ *Entry in:* {i}s
🕐 *New York Time:* {current_time.strftime("%H:%M:%S")}
⌛️ *Entry at:* {entry_time_str}
━━━━━━━━━━━━━━━━━━━

💡 *STAY CALM AND FOLLOW THE PLAN*"""
        
        edit_message(chat_id, message_id, text)
        time.sleep(1)
    
    # Send message that bot is trading
    edit_message(chat_id, message_id, "🔄 *Executing trade on Pocket Option...*\nPlease wait 1 minute...")
    
    # Execute trade on Pocket Option
    result = pocket_option_trade(pair, signal, amount=10, expiration=60)
    
    final_close_time = get_new_york_time()
    
    if result is not None:
        if result > 0:  # WIN
            statistics["win"] += 1
            statistics["total"] += 1
            
            final_message = f"""✅ *WIN - AUTOMATIC TRADE* ✅

━━━━━━━━━━━━━━━━━━━
**{pair}**
{signal_emoji} Signal: *{signal}*
📊 Confidence: {confidence}%
━━━━━━━━━━━━━━━━━━━
💰 *Profit: +${result:.2f}*
🕐 *Close Time:* {final_close_time.strftime("%H:%M:%S")}
━━━━━━━━━━━━━━━━━━━
📈 Win Rate: {statistics['win']/statistics['total']*100:.1f}%
━━━━━━━━━━━━━━━━━━━

Congratulations! 🎉"""
            
        elif result == 0:  # LOSS
            statistics["loss"] += 1
            statistics["total"] += 1
            
            final_message = f"""❌ *LOSS - AUTOMATIC TRADE* ❌

━━━━━━━━━━━━━━━━━━━
**{pair}**
{signal_emoji} Signal: *{signal}*
📊 Confidence: {confidence}%
━━━━━━━━━━━━━━━━━━━
💸 *Loss: -$10.00*
🕐 *Close Time:* {final_close_time.strftime("%H:%M:%S")}
━━━━━━━━━━━━━━━━━━━
📈 Win Rate: {statistics['win']/statistics['total']*100:.1f}%
━━━━━━━━━━━━━━━━━━━

Don't give up, next one will be better! 💪"""
        else:
            final_message = f"""⚠️ *TRADE NOT CONFIRMED* ⚠️

━━━━━━━━━━━━━━━━━━━
**{pair}**
{signal_emoji} Signal: *{signal}*
━━━━━━━━━━━━━━━━━━━

Could not get result. Please check manually."""
    else:
        final_message = f"""⚠️ *TRADE NOT EXECUTED* ⚠️

━━━━━━━━━━━━━━━━━━━
**{pair}**
{signal_emoji} Signal: *{signal}*
━━━━━━━━━━━━━━━━━━━

Could not connect to Pocket Option. Please check your credentials."""
    
    edit_message(chat_id, message_id, final_message)

def update_statistics():
    global statistics
    if statistics["total"] > 0:
        statistics["win_rate"] = (statistics["win"] / statistics["total"]) * 100
    else:
        statistics["win_rate"] = 0
    return statistics

def create_pair_buttons():
    buttons = []
    row = []
    
    for i, pair in enumerate(PAIRS):
        row.append({"text": pair, "callback_data": f"select_pair_{pair}"})
        if len(row) == 2 or i == len(PAIRS) - 1:
            buttons.append(row)
            row = []
    
    return buttons

# ======================== COMMAND HANDLING ========================
last_update_id = 0

app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 DFG2K Trading Bot is running 24/7!"

def run_bot():
    global last_update_id, statistics
    
    # Verify Telegram token
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set!")
        return
    
    print(f"✅ TELEGRAM_TOKEN: {TELEGRAM_TOKEN[:5]}...{TELEGRAM_TOKEN[-5:] if TELEGRAM_TOKEN else 'Not set'}")
    print(f"📊 Twelve Data API Key: {TWELVE_DATA_API_KEY[:5]}...{TWELVE_DATA_API_KEY[-5:] if TWELVE_DATA_API_KEY else 'Not set'}")
    
    # Try to connect to Pocket Option at startup
    if PO_AVAILABLE:
        connect_pocket_option()
    
    print("🤖 Bot is running...")
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            response = requests.get(url, params={
                "offset": last_update_id + 1,
                "timeout": 30
            }, timeout=35).json()
            
            if "result" in response:
                for update in response["result"]:
                    last_update_id = update["update_id"]
                    
                    # Check if it's a message
                    if "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"]["text"]
                        
                        if text == "/start":
                            welcome_message = f"""🎯 *WELCOME TO DFG2K SIGNAL BOT* 🎯

I'm a trading signal bot that provides real-time signals for **Pocket Option** and other platforms.

━━━━━━━━━━━━━━━━━━━
*📊 AVAILABLE COMMANDS:*
/signal - Get an immediate signal
/follow - Start automatic signal following
/stats - View bot performance
/help - Get help

━━━━━━━━━━━━━━━━━━━
*💡 HOW IT WORKS:*
1️⃣ Type /signal
2️⃣ I'll analyze the market
3️⃣ I'll automatically trade for you
4️⃣ I'll tell you the result (WIN/LOSS)

━━━━━━━━━━━━━━━━━━━
🕐 *New York Time:* {format_ny_time()}
━━━━━━━━━━━━━━━━━━━
👑 Developed by @Dfg2k"""
                            
                            send_message(chat_id, welcome_message)
                        
                        elif text == "/signal":
                            result = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                                "chat_id": chat_id,
                                "text": "🔄 Analyzing market..."
                            }).json()
                            
                            if result.get("ok"):
                                message_id = result["result"]["message_id"]
                                time.sleep(2)
                                
                                pair, signal, confidence, reason = generate_signal()
                                threading.Thread(target=send_signal_with_preparation, 
                                               args=(chat_id, message_id, pair, signal, confidence, reason)).start()
                        
                        elif text == "/follow":
                            send_message(chat_id, """⚙️ *AUTOMATIC FOLLOW FUNCTION*

For now, use /signal to get signals.

*Next update will include:*  
✅ Automatic signals every 30 minutes
✅ Seamless automatic trading

Thank you for using DFG2K Bot! 🙏""")
                        
                        elif text == "/stats":
                            update_statistics()
                            stats_message = f"""📊 *BOT STATISTICS*

━━━━━━━━━━━━━━━━━━━
✅ Wins: {statistics['win']}
❌ Losses: {statistics['loss']}
📊 Total Trades: {statistics['total']}
📈 Win Rate: {statistics['win_rate']:.1f}%
━━━━━━━━━━━━━━━━━━━

🕐 *New York Time:* {format_ny_time()}
━━━━━━━━━━━━━━━━━━━

*Keep trusting the signals!* 💪"""
                            send_message(chat_id, stats_message)
                        
                        elif text == "/help":
                            help_message = f"""📚 *HELP & SUPPORT*

━━━━━━━━━━━━━━━━━━━
*COMMANDS:*
/signal - Get signal with automatic trade
/follow - Start automatic following
/stats - View performance statistics

━━━━━━━━━━━━━━━━━━━
*💡 HOW TO USE:*
1️⃣ Type /signal
2️⃣ Bot will analyze the market
3️⃣ Bot will execute trade for you
4️⃣ You'll see the result automatically

━━━━━━━━━━━━━━━━━━━
🕐 *New York Time:* {format_ny_time()}
━━━━━━━━━━━━━━━━━━━
👑 Developed by @Dfg2k"""
                            
                            send_message(chat_id, help_message)
                    
                    # Check if it's a callback query (button response)
                    elif "callback_query" in update:
                        cb = update["callback_query"]
                        chat_id = cb["message"]["chat"]["id"]
                        message_id = cb["message"]["message_id"]
                        data = cb["data"]
                        
                        # Answer callback to remove loading state
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                                     json={"callback_query_id": cb["id"]})
                        
                        if data.startswith("win_"):
                            parts = data.split("_")
                            pair = parts[1]
                            
                            statistics["win"] += 1
                            statistics["total"] += 1
                            update_statistics()
                            
                            confirmation_message = f"""✅ *WIN CONFIRMED* ✅

━━━━━━━━━━━━━━━━━━━
**{pair}**
━━━━━━━━━━━━━━━━━━━
📊 Result: *WIN* 🎉
📈 Win Rate: {statistics['win_rate']:.1f}%
━━━━━━━━━━━━━━━━━━━

Congratulations! 🎉"""
                            
                            edit_message(chat_id, message_id, confirmation_message)
                        
                        elif data.startswith("loss_"):
                            parts = data.split("_")
                            pair = parts[1]
                            
                            statistics["loss"] += 1
                            statistics["total"] += 1
                            update_statistics()
                            
                            confirmation_message = f"""❌ *LOSS CONFIRMED* ❌

━━━━━━━━━━━━━━━━━━━
**{pair}**
━━━━━━━━━━━━━━━━━━━
📊 Result: *LOSS* 😢
📈 Win Rate: {statistics['win_rate']:.1f}%
━━━━━━━━━━━━━━━━━━━

Don't give up, next one will be better! 💪"""
                            
                            edit_message(chat_id, message_id, confirmation_message)
            
            time.sleep(1)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

# Start bot in a separate thread
if __name__ == "__main__":
    # Start the bot thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Run Flask app
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
