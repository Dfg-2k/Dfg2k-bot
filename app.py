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
from collections import deque

# ======================== CONFIGURATION ========================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TWELVE_DATA_API_KEY = os.environ.get('TWELVE_DATA_API_KEY')
POCKET_OPTION_EMAIL = os.environ.get('POCKET_OPTION_EMAIL')
POCKET_OPTION_PASSWORD = os.environ.get('POCKET_OPTION_PASSWORD')

# Trading pairs (OTC)
PAIRS = [
    "AUDCHF-OTC", "AUDJPY-OTC", "AUDNZD-OTC", "AUDUSD-OTC",
    "CADCHF-OTC", "CADJPY-OTC", "CHFJPY-OTC", "EURAUD-OTC",
    "EURCAD-OTC", "EURCHF-OTC", "EURGBP-OTC", "EURJPY-OTC",
    "EURNZD-OTC", "EURUSD-OTC", "GBPAUD-OTC", "GBPCAD-OTC",
    "GBPCHF-OTC", "GBPJPY-OTC", "GBPUSD-OTC", "NZDCAD-OTC",
    "NZDCHF-OTC", "NZDJPY-OTC", "NZDUSD-OTC", "USDCAD-OTC",
    "USDCHF-OTC", "USDCNH-OTC", "USDJPY-OTC", "USDMXN-OTC",
    "USDNOK-OTC", "USDSEK-OTC", "YERUSD-OTC"
]

# Timeframes available
TIMEFRAMES = {
    "M1": 60,      # 1 minute
    "M5": 300,     # 5 minutes
    "M15": 900,    # 15 minutes
    "M30": 1800,   # 30 minutes
    "H1": 3600     # 1 hour
}

# ======================== STATISTICS ========================
statistics = {
    "win": 0, 
    "loss": 0, 
    "total": 0,
    "trades": []  # Store last 15 trades
}
active_signals = {}
auto_signal_active = False
selected_timeframe = "M1"  # Default timeframe

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

def pocket_option_trade(pair, signal, amount=10):
    """Execute a trade on Pocket Option and return result"""
    global po_api, po_connected
    
    if not po_connected:
        if not connect_pocket_option():
            return None
    
    try:
        # Convert pair name
        pair_po = pair.replace("-OTC", "_otc")
        
        # Convert signal
        action = "call" if signal == "BUY" else "put"
        
        # Get timeframe in seconds
        expiration = TIMEFRAMES[selected_timeframe]
        
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

def format_time_for_display(dt):
    return dt.strftime("%I:%M %p").lower()

# ======================== TWELVE DATA API FUNCTIONS ========================
def get_twelve_data(pair):
    """Get market data from Twelve Data API"""
    if "-OTC" in pair:
        pair = pair.replace("-OTC", "")
    
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
            df = df.iloc[::-1]
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
    close = data['close']
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(data):
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
    
    try:
        rsi = calculate_rsi(data)
        macd, signal, hist = calculate_macd(data)
        
        last_rsi = rsi.iloc[-1] if len(rsi) > 0 else 50
        last_hist = hist.iloc[-1] if len(hist) > 0 else 0
        prev_hist = hist.iloc[-2] if len(hist) > 1 else 0
        
        current_price = data['close'].iloc[-1]
        prev_price = data['close'].iloc[-2] if len(data) > 1 else current_price
        
        # BUY signal
        if last_rsi < 40:
            if last_hist > prev_hist:
                return "BUY", 85, f"RSI {last_rsi:.1f} (oversold) + MACD bullish"
            elif current_price > prev_price:
                return "BUY", 75, f"RSI {last_rsi:.1f} (oversold) + Price rising"
            else:
                return "BUY", 70, f"RSI {last_rsi:.1f} (oversold)"
        
        # SELL signal
        elif last_rsi > 60:
            if last_hist < prev_hist:
                return "SELL", 85, f"RSI {last_rsi:.1f} (overbought) + MACD bearish"
            elif current_price < prev_price:
                return "SELL", 75, f"RSI {last_rsi:.1f} (overbought) + Price falling"
            else:
                return "SELL", 70, f"RSI {last_rsi:.1f} (overbought)"
        
        # Neutral
        else:
            if current_price > prev_price:
                return "BUY", 55, f"RSI {last_rsi:.1f} - Rising"
            else:
                return "SELL", 55, f"RSI {last_rsi:.1f} - Falling"
    except Exception as e:
        print(f"Error in signal detection: {e}")
        return random.choice(["BUY", "SELL"]), 60, "Analysis error"

def generate_signal(selected_pair=None):
    """Generate signal based on real market data"""
    
    if selected_pair:
        pair = selected_pair
    else:
        pair = random.choice(PAIRS)
    
    data = get_twelve_data(pair)
    
    if data == "limit":
        signal = random.choice(["BUY", "SELL"])
        confidence = 50
        reason = "API limit reached"
        return pair, signal, confidence, reason
    elif data is None or len(data) < 20:
        signal = random.choice(["BUY", "SELL"])
        confidence = random.randint(60, 70)
        reason = "Limited data"
        return pair, signal, confidence, reason
    
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
        requests.post(url, json=data, timeout=10)
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

def create_timeframe_buttons():
    """Create buttons for timeframe selection"""
    buttons = []
    row = []
    tf_list = list(TIMEFRAMES.keys())
    
    for i, tf in enumerate(tf_list):
        row.append({"text": tf, "callback_data": f"set_tf_{tf}"})
        if len(row) == 3 or i == len(tf_list) - 1:
            buttons.append(row)
            row = []
    
    return buttons

def create_pair_buttons():
    """Create buttons for pair selection"""
    buttons = []
    row = []
    
    for i, pair in enumerate(PAIRS[:20]):  # Limit to 20 pairs for button size
        row.append({"text": pair, "callback_data": f"pair_{pair}"})
        if len(row) == 2 or i == 19:
            buttons.append(row)
            row = []
    
    return buttons

def send_signal_and_trade(chat_id, message_id, pair, signal, confidence, reason):
    """Send signal and execute trade"""
    global statistics
    
    current_time = get_new_york_time()
    entry_time = current_time
    close_time = current_time + timedelta(seconds=TIMEFRAMES[selected_timeframe])
    
    current_time_str = current_time.strftime("%H:%M:%S")
    display_time = format_time_for_display(current_time)
    
    signal_emoji = "🟢" if signal == "BUY" else "🔴"
    
    # Store signal info
    signal_id = f"{chat_id}_{message_id}"
    active_signals[signal_id] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "pair": pair,
        "signal": signal,
        "entry_time": current_time_str,
        "close_time": close_time.strftime("%H:%M:%S"),
        "confidence": confidence
    }
    
    # Send signal message
    signal_message = f"""FxMamba PocketBot
Pocket Sniper Bot OTC

{pair}
{selected_timeframe}
{current_time_str}
{signal.lower()}
🔘 1  {display_time}

{signal}"""
    
    edit_message(chat_id, message_id, signal_message)
    
    # Execute trade on Pocket Option
    result = pocket_option_trade(pair, signal)
    
    final_time = get_new_york_time()
    
    if result is not None:
        if result > 0:  # WIN
            statistics["win"] += 1
            result_text = "WIN ✅"
            
            # Store trade in history
            statistics["trades"].append({
                "pair": pair,
                "signal": signal,
                "entry_time": current_time_str,
                "result": "WIN",
                "profit": f"+${result:.2f}"
            })
        elif result == 0:  # LOSS
            statistics["loss"] += 1
            result_text = "LOSS ❌"
            
            statistics["trades"].append({
                "pair": pair,
                "signal": signal,
                "entry_time": current_time_str,
                "result": "LOSS",
                "profit": "-$10.00"
            })
        else:
            result_text = "UNKNOWN"
    else:
        result_text = "TRADE FAILED"
    
    statistics["total"] += 1
    
    # Keep only last 15 trades
    if len(statistics["trades"]) > 15:
        statistics["trades"] = statistics["trades"][-15:]
    
    # Send result message
    result_message = f"""FxMamba PocketBot
{result_text}
🔘 1  {format_time_for_display(final_time)}"""
    
    edit_message(chat_id, message_id, result_message)
    
    # Check if we have 15 trades to report
    if statistics["total"] % 15 == 0 and statistics["total"] > 0:
        send_trade_report(chat_id)

def send_trade_report(chat_id):
    """Send report of last 15 trades"""
    global statistics
    
    report = "📊 *15 TRADES REPORT*\n\n"
    report += "```\n"
    report += "No. | Pair      | Signal | Time     | Result | Profit\n"
    report += "----|-----------|--------|----------|--------|--------\n"
    
    for i, trade in enumerate(statistics["trades"][-15:], 1):
        report += f"{i:3} | {trade['pair']:9} | {trade['signal']:4} | {trade['entry_time']} | {trade['result']:4} | {trade['profit']}\n"
    
    report += "```\n\n"
    report += f"📈 Win Rate: {statistics['win']/statistics['total']*100:.1f}% ({statistics['win']}/{statistics['total']})"
    
    send_message(chat_id, report)

def auto_signal_loop(chat_id):
    """Automatic signal loop every 3 minutes"""
    global auto_signal_active
    
    while auto_signal_active:
        # Send typing action
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction", json={
            "chat_id": chat_id,
            "action": "typing"
        })
        
        # Generate and send signal
        pair, signal, confidence, reason = generate_signal()
        
        result = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
            "chat_id": chat_id,
            "text": "🔄 *Generating signal...*"
        }).json()
        
        if result.get("ok"):
            message_id = result["result"]["message_id"]
            time.sleep(2)
            send_signal_and_trade(chat_id, message_id, pair, signal, confidence, reason)
        
        # Wait 3 minutes (180 seconds)
        time.sleep(180)

# ======================== COMMAND HANDLING ========================
last_update_id = 0

app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 FxMamba PocketBot is running 24/7!"

def run_bot():
    global last_update_id, statistics, auto_signal_active, selected_timeframe
    
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set!")
        return
    
    # Connect to Pocket Option
    if PO_AVAILABLE:
        connect_pocket_option()
    
    print("✅ FxMamba PocketBot is running...")
    print(f"📊 Default Timeframe: {selected_timeframe}")
    
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
                    
                    if "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"]["text"]
                        
                        if text == "/start":
                            welcome = f"""🎯 *Welcome to FxMamba PocketBot*

Pocket Sniper Bot OTC

*Current Timeframe:* {selected_timeframe}

*Commands:*
/signal - Get one signal now
/auto - Start auto signals (every 3 min)
/stop - Stop auto signals
/timeframe - Change timeframe
/stats - View performance
/report - Get last 15 trades report
/help - Get help

Developed by @Dfg2k"""
                            send_message(chat_id, welcome)
                        
                        elif text == "/signal":
                            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction", json={
                                "chat_id": chat_id,
                                "action": "typing"
                            })
                            
                            pair, signal, confidence, reason = generate_signal()
                            
                            result = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                                "chat_id": chat_id,
                                "text": "🔄 *Generating signal...*"
                            }).json()
                            
                            if result.get("ok"):
                                message_id = result["result"]["message_id"]
                                threading.Thread(target=send_signal_and_trade, 
                                               args=(chat_id, message_id, pair, signal, confidence, reason)).start()
                        
                        elif text == "/auto":
                            if not auto_signal_active:
                                auto_signal_active = True
                                send_message(chat_id, f"🔄 *Auto signals started*\nEvery 3 minutes with {selected_timeframe}")
                                threading.Thread(target=auto_signal_loop, args=(chat_id,), daemon=True).start()
                            else:
                                send_message(chat_id, "⚠️ Auto signals already running")
                        
                        elif text == "/stop":
                            if auto_signal_active:
                                auto_signal_active = False
                                send_message(chat_id, "⏹️ *Auto signals stopped*")
                            else:
                                send_message(chat_id, "ℹ️ Auto signals not running")
                        
                        elif text == "/timeframe":
                            tf_buttons = create_timeframe_buttons()
                            send_message(chat_id, "⏱️ *Select Timeframe:*", tf_buttons)
                        
                        elif text == "/stats":
                            win_rate = (statistics["win"] / statistics["total"] * 100) if statistics["total"] > 0 else 0
                            stats = f"""📊 *Bot Statistics*

✅ Wins: {statistics['win']}
❌ Losses: {statistics['loss']}
📈 Total Trades: {statistics['total']}
🎯 Win Rate: {win_rate:.1f}%

🕐 {format_ny_time()}
⏱️ Current TF: {selected_timeframe}"""
                            send_message(chat_id, stats)
                        
                        elif text == "/report":
                            send_trade_report(chat_id)
                        
                        elif text == "/help":
                            help_text = f"""📚 *Help & Commands*

*Trading Commands:*
/signal - Get one signal now
/auto - Start auto signals (3 min)
/stop - Stop auto signals
/timeframe - Change timeframe

*Info Commands:*
/stats - View performance
/report - Last 15 trades report
/help - Show this message

*Current Settings:*
⏱️ Timeframe: {selected_timeframe}
🤖 Auto: {'ON' if auto_signal_active else 'OFF'}

Developed by @Dfg2k"""
                            send_message(chat_id, help_text)
                    
                    elif "callback_query" in update:
                        cb = update["callback_query"]
                        chat_id = cb["message"]["chat"]["id"]
                        message_id = cb["message"]["message_id"]
                        data = cb["data"]
                        
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                                     json={"callback_query_id": cb["id"]})
                        
                        if data.startswith("set_tf_"):
                            new_tf = data.replace("set_tf_", "")
                            if new_tf in TIMEFRAMES:
                                selected_timeframe = new_tf
                                edit_message(chat_id, message_id, 
                                           f"✅ Timeframe set to **{new_tf}**\n\nUse /auto to start trading.")
                        
                        elif data.startswith("pair_"):
                            selected_pair = data.replace("pair_", "")
                            
                            pair, signal, confidence, reason = generate_signal(selected_pair)
                            
                            edit_message(chat_id, message_id, "🔄 *Generating signal...*")
                            time.sleep(2)
                            
                            threading.Thread(target=send_signal_and_trade, 
                                           args=(chat_id, message_id, pair, signal, confidence, reason)).start()
            
            time.sleep(1)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

# Start bot
if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
