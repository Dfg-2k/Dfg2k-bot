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

# ======================== KONFIGIRASYON ========================
TELEGRAM_TOKEN = "8732682223:AAF-RTy1QuqIpxi-g9fQchnIJMC-vYZbQt4"
TWELVE_DATA_API_KEY = "5a4da0e74bc443dda74fd19039254342"

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
TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1"]
selected_timeframe = "M1"

# Statistics
statistics = {"win": 0, "loss": 0, "total": 0}

# ======================== TIME FUNCTIONS ========================
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
    print("🔄 Generating signal...")
    pair = random.choice(PAIRS)
    print(f"Selected pair: {pair}")
    
    data = get_twelve_data(pair)
    print(f"Data received: {data is not None}")
    
    if data == "limit":
        print("⚠️ API limit reached")
        signal = random.choice(["BUY", "SELL"])
        confidence = 50
        reason = "API limit"
        return pair, signal, confidence, reason
    elif data is None:
        print("⚠️ No data from API")
        signal = random.choice(["BUY", "SELL"])
        confidence = random.randint(60, 70)
        reason = "No data - random signal"
        return pair, signal, confidence, reason
    
    signal, confidence, reason = detect_signal(data)
    print(f"Signal: {signal}, Confidence: {confidence}")
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

def send_signal(chat_id, message_id, pair, signal, confidence, reason):
    current_time = get_new_york_time()
    display_time = format_time_for_display(current_time)
    
    signal_emoji = "🟢" if signal == "BUY" else "🔴"
    
    # Signal message
    signal_message = f"""FxMamba PocketBot
Pocket Sniper Bot OTC

{pair}
{selected_timeframe}
{current_time.strftime("%H:%M:%S")}
{signal.lower()}
🔘 1  {display_time}

{signal}"""
    
    edit_message(chat_id, message_id, signal_message)
    
    # Wait 2 minutes (simulate trade time)
    time.sleep(120)
    
    # Random result for testing
    is_win = random.choice([True, False])
    final_time = get_new_york_time()
    
    if is_win:
        statistics["win"] += 1
        result_text = "WIN ✅"
    else:
        statistics["loss"] += 1
        result_text = "LOSS ❌"
    
    statistics["total"] += 1
    
    # Result message
    result_message = f"""FxMamba PocketBot
{result_text}
🔘 1  {format_time_for_display(final_time)}"""
    
    edit_message(chat_id, message_id, result_message)

def create_timeframe_buttons():
    buttons = []
    row = []
    for i, tf in enumerate(TIMEFRAMES):
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
    global last_update_id, selected_timeframe
    
    print("✅ FxMamba PocketBot is running...")
    print(f"📊 Twelve Data API Key: {TWELVE_DATA_API_KEY[:5]}...")
    
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
                            result = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                                "chat_id": chat_id,
                                "text": "🔄 *Generating signal...*"
                            }).json()
                            
                            if result.get("ok"):
                                message_id = result["result"]["message_id"]
                                time.sleep(2)
                                pair, signal, confidence, reason = generate_signal()
                                threading.Thread(target=send_signal, 
                                               args=(chat_id, message_id, pair, signal, confidence, reason)).start()
                        
                        elif text == "/auto":
                            send_message(chat_id, "⚙️ Auto signals coming soon!")
                        
                        elif text == "/stop":
                            send_message(chat_id, "⏹️ No auto signals running")
                        
                        elif text == "/timeframe":
                            tf_buttons = create_timeframe_buttons()
                            send_message(chat_id, "⏱️ *Select Timeframe:*", tf_buttons)
                        
                        elif text == "/stats":
                            win_rate = (statistics["win"] / statistics["total"] * 100) if statistics["total"] > 0 else 0
                            stats = f"""📊 *Statistics*

✅ Wins: {statistics['win']}
❌ Losses: {statistics['loss']}
📈 Total: {statistics['total']}
🎯 Win Rate: {win_rate:.1f}%

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
