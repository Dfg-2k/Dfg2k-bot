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

# ======================== KONFIGIRASYON ========================
# NOUVO TOKEN OU A
TELEGRAM_TOKEN = "8732682223:AAF-RTy1QuqIpxi-g9fQchnIJMC-vYZbQt4"

TWELVE_DATA_API_KEY = os.environ.get('TWELVE_DATA_API_KEY')

# ======================== POCKET OPTION SSID ========================
POCKET_OPTION_SSID = "42[\"auth\",{\"sessionToken\":\"610648e6d940f217a9e05b179aac75ad\",\"uid\":\"124162892\",\"lang\":\"en\",\"currentUrl\":\"cabinet\",\"isChart\":1}]"

# Trading pairs list
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

# Timeframes
TIMEFRAMES = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600
}

# ======================== STATISTICS ========================
statistics = {"win": 0, "loss": 0, "total": 0, "win_rate": 0}
active_signals = {}
auto_signal_active = False
selected_timeframe = "M1"

# ======================== POCKET OPTION CONNECTION ========================
try:
    from pocketoptionapi.stable_api import PocketOption
    PO_AVAILABLE = True
except ImportError:
    print("⚠️ PocketOptionAPI not installed")
    PO_AVAILABLE = False

po_api = None
po_connected = False

def connect_pocket_option():
    global po_api, po_connected
    
    if not PO_AVAILABLE:
        return False
    
    try:
        po_api = PocketOption(ssid=POCKET_OPTION_SSID, demo=True)
        po_api.connect()
        time.sleep(3)
        
        if po_api.check_connect():
            po_connected = True
            print("✅ Connected to Pocket Option with SSID")
            return True
        else:
            print("❌ Failed to connect")
            return False
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False

def pocket_option_trade(pair, signal, amount=10):
    global po_api, po_connected
    
    if not po_connected:
        if not connect_pocket_option():
            return None
    
    try:
        pair_po = pair.replace("-OTC", "_otc")
        action = "call" if signal == "BUY" else "put"
        expiration = TIMEFRAMES[selected_timeframe]
        
        result = po_api.buy(
            amount=amount,
            active=pair_po,
            action=action,
            expirations=expiration
        )
        
        if result["success"]:
            order_id = result["order_id"]
            print(f"✅ Order placed: {order_id}")
            time.sleep(expiration + 5)
            trade_result = po_api.check_win(order_id)
            return trade_result
        else:
            return None
    except Exception as e:
        print(f"❌ Trade error: {e}")
        return None

# ======================== NEW YORK TIME ========================
def get_new_york_time():
    return datetime.now(pytz.timezone('America/New_York'))

def format_ny_time():
    return get_new_york_time().strftime("%H:%M:%S")

def format_time_for_display(dt):
    return dt.strftime("%I:%M %p").lower()

# ======================== TWELVE DATA API ========================
def get_twelve_data(pair):
    if "-OTC" in pair:
        pair = pair.replace("-OTC", "")
    
    if not TWELVE_DATA_API_KEY:
        return None
    
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
            return df
        elif "code" in data and data["code"] == 429:
            return "limit"
        else:
            return None
    except Exception as e:
        print(f"❌ Twelve Data error: {e}")
        return None

def calculate_rsi(data, period=14):
    close = data['close']
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def detect_signal(data):
    if data is None or len(data) < 20:
        return random.choice(["BUY", "SELL"]), 60, "Limited data"
    
    try:
        rsi = calculate_rsi(data)
        last_rsi = rsi.iloc[-1] if len(rsi) > 0 else 50
        current_price = data['close'].iloc[-1]
        prev_price = data['close'].iloc[-2] if len(data) > 1 else current_price
        
        if last_rsi < 40:
            return "BUY", 75, f"RSI {last_rsi:.1f} (oversold)"
        elif last_rsi > 60:
            return "SELL", 75, f"RSI {last_rsi:.1f} (overbought)"
        else:
            if current_price > prev_price:
                return "BUY", 55, f"RSI {last_rsi:.1f} - Rising"
            else:
                return "SELL", 55, f"RSI {last_rsi:.1f} - Falling"
    except Exception as e:
        return random.choice(["BUY", "SELL"]), 60, "Analysis error"

def generate_signal():
    pair = random.choice(PAIRS)
    data = get_twelve_data(pair)
    
    if data == "limit" or data is None:
        signal = random.choice(["BUY", "SELL"])
        confidence = 50
        reason = "API limit"
        return pair, signal, confidence, reason
    
    signal, confidence, reason = detect_signal(data)
    return pair, signal, confidence, reason

# ======================== TELEGRAM FUNCTIONS ========================
def send_message(chat_id, text, buttons=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
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
    data = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if buttons:
        data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Error editing message: {e}")

def send_signal_and_trade(chat_id, message_id, pair, signal, confidence, reason):
    current_time = get_new_york_time()
    entry_time = current_time
    display_time = format_time_for_display(current_time)
    
    signal_emoji = "🟢" if signal == "BUY" else "🔴"
    
    # Signal message
    signal_message = f"""FxMamba PocketBot
Pocket Sniper Bot OTC

{pair}
{selected_timeframe}
{entry_time.strftime("%H:%M:%S")}
{signal.lower()}
🔘 1  {display_time}

{signal}"""
    
    edit_message(chat_id, message_id, signal_message)
    
    # Execute trade
    result = pocket_option_trade(pair, signal)
    final_time = get_new_york_time()
    
    if result is not None:
        if result > 0:
            statistics["win"] += 1
            result_text = "WIN ✅"
        elif result == 0:
            statistics["loss"] += 1
            result_text = "LOSS ❌"
        else:
            result_text = "UNKNOWN"
    else:
        result_text = "TRADE FAILED"
    
    statistics["total"] += 1
    if statistics["total"] > 0:
        statistics["win_rate"] = (statistics["win"] / statistics["total"]) * 100
    
    # Result message
    result_message = f"""FxMamba PocketBot
{result_text}
🔘 1  {format_time_for_display(final_time)}"""
    
    edit_message(chat_id, message_id, result_message)

def auto_signal_loop(chat_id):
    global auto_signal_active
    while auto_signal_active:
        pair, signal, confidence, reason = generate_signal()
        
        result = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
            "chat_id": chat_id,
            "text": "🔄 *Generating signal...*"
        }).json()
        
        if result.get("ok"):
            message_id = result["result"]["message_id"]
            time.sleep(2)
            send_signal_and_trade(chat_id, message_id, pair, signal, confidence, reason)
        
        time.sleep(180)  # 3 minutes

def create_timeframe_buttons():
    buttons = []
    row = []
    for i, tf in enumerate(TIMEFRAMES.keys()):
        row.append({"text": tf, "callback_data": f"set_tf_{tf}"})
        if len(row) == 3 or i == len(TIMEFRAMES) - 1:
            buttons.append(row)
            row = []
    return buttons

# ======================== COMMAND HANDLING ========================
last_update_id = 0
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 FxMamba PocketBot is running 24/7!"

def run_bot():
    global last_update_id, auto_signal_active, selected_timeframe, statistics
    
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set!")
        return
    
    print(f"✅ Telegram Token: {TELEGRAM_TOKEN[:10]}...")
    
    # Connect to Pocket Option
    if PO_AVAILABLE:
        connect_pocket_option()
    
    print("✅ FxMamba PocketBot is running...")
    
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

*Commands:*
/signal - Get one signal
/auto - Start auto signals (3 min)
/stop - Stop auto signals
/timeframe - Change timeframe
/stats - View performance
/help - Get help

⏱️ Current TF: {selected_timeframe}"""
                            send_message(chat_id, welcome)
                        
                        elif text == "/signal":
                            # Send typing action
                            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction", json={
                                "chat_id": chat_id,
                                "action": "typing"
                            })
                            
                            result = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                                "chat_id": chat_id,
                                "text": "🔄 *Generating signal...*"
                            }).json()
                            
                            if result.get("ok"):
                                message_id = result["result"]["message_id"]
                                time.sleep(2)
                                pair, signal, confidence, reason = generate_signal()
                                threading.Thread(target=send_signal_and_trade, 
                                               args=(chat_id, message_id, pair, signal, confidence, reason)).start()
                        
                        elif text == "/auto":
                            if not auto_signal_active:
                                auto_signal_active = True
                                send_message(chat_id, f"🔄 Auto signals started (every 3 min)")
                                threading.Thread(target=auto_signal_loop, args=(chat_id,), daemon=True).start()
                            else:
                                send_message(chat_id, "⚠️ Already running")
                        
                        elif text == "/stop":
                            auto_signal_active = False
                            send_message(chat_id, "⏹️ Auto signals stopped")
                        
                        elif text == "/timeframe":
                            tf_buttons = create_timeframe_buttons()
                            send_message(chat_id, "⏱️ *Select Timeframe:*", tf_buttons)
                        
                        elif text == "/stats":
                            stats = f"""📊 *Statistics*

✅ Wins: {statistics['win']}
❌ Losses: {statistics['loss']}
📈 Total: {statistics['total']}
🎯 Win Rate: {statistics['win_rate']:.1f}%

⏱️ TF: {selected_timeframe}"""
                            send_message(chat_id, stats)
                        
                        elif text == "/help":
                            help_text = f"""📚 *Help*

/signal - Get one signal
/auto - Start auto (3 min)
/stop - Stop auto
/timeframe - Change TF
/stats - View stats

⏱️ Current TF: {selected_timeframe}

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
                            selected_timeframe = data.replace("set_tf_", "")
                            edit_message(chat_id, message_id, f"✅ Timeframe set to **{selected_timeframe}**")
            
            time.sleep(1)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

# ======================== START BOT ========================
if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
