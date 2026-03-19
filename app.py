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
TELEGRAM_TOKEN = "8615131640:AAHGQiYyP5uNqc6zUlQooJShcwlfqcwvur8"
FCS_API_KEY = "28GdysVWgjHLVCAzVjqi9xF"
POCKET_OPTION_SSID = "42[\"auth\",{\"sessionToken\":\"610648e6d940f217a9e05b179aac75ad\",\"uid\":\"124162892\",\"lang\":\"en\",\"currentUrl\":\"cabinet\",\"isChart\":1}]"

# Trading pairs list (ajoute tout pè yo)
PAIRS = [
    "AUDCAD-OTC", "AUDCHF-OTC", "AUDJPY-OTC", "AUDNZD-OTC", "AUDUSD-OTC",
    "CADCHF-OTC", "CADJPY-OTC", "CHFJPY-OTC", "EURAUD-OTC", "EURCAD-OTC",
    "EURCHF-OTC", "EURGBP-OTC", "EURJPY-OTC", "EURNZD-OTC", "EURUSD-OTC",
    "GBPAUD-OTC", "GBPCAD-OTC", "GBPCHF-OTC", "GBPJPY-OTC", "GBPUSD-OTC",
    "NZDCAD-OTC", "NZDCHF-OTC", "NZDJPY-OTC", "NZDUSD-OTC", "USDCAD-OTC",
    "USDCHF-OTC", "USDCNH-OTC", "USDJPY-OTC", "USDMXN-OTC", "USDNOK-OTC",
    "USDSEK-OTC", "USDSGD-OTC", "USDZAR-OTC", "XAGUSD-OTC", "XAUUSD-OTC",
    "BTCUSD-OTC", "ETHUSD-OTC", "LTCUSD-OTC", "RIPPLE-OTC", "YERUSD-OTC",
    "MADUSD-OTC", "LBPUSD-OTC", "TNDUSD-OTC", "ZARUSD-OTC", "UAHUSD-OTC",
    "NGNUSD-OTC", "USDVND-OTC"
]

# Timeframes
TIMEFRAMES = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}
selected_timeframe = "M1"

# ======================== STATISTICS ========================
statistics = {
    "win": 0,
    "loss": 0,
    "total": 0,
    "win_rate": 0,
    "trades": deque(maxlen=15)  # Kenbe dènye 15 trade yo
}
auto_signal_active = False

# ======================== POCKET OPTION ========================
try:
    from BinaryOptionsToolsV2.pocketoption import PocketOption
    PO_AVAILABLE = True
    print("✅ BinaryOptionsToolsV2 enstale byen.")
except ImportError:
    print("❌ BinaryOptionsToolsV2 pa enstale. Trade otomatik pap disponib.")
    PO_AVAILABLE = False

po_client = None

def connect_pocket_option():
    """Konekte ak Pocket Option"""
    global po_client
    if not PO_AVAILABLE or not POCKET_OPTION_SSID:
        return False
    try:
        print("🔄 Ap konekte ak Pocket Option...")
        po_client = PocketOption(ssid=POCKET_OPTION_SSID)
        balance = po_client.balance()
        print(f"✅ Konekte byen. Balans: ${balance}")
        return True
    except Exception as e:
        print(f"❌ Erè koneksyon Pocket Option: {e}")
        po_client = None
        return False

def pocket_option_trade(pair, direction, amount=10):
    """Fè yon trade sou Pocket Option"""
    global po_client
    if not po_client:
        if not connect_pocket_option():
            return None

    try:
        asset = pair.replace("-OTC", "_otc")
        action = "call" if direction == "BUY" else "put"
        duration = TIMEFRAMES[selected_timeframe]

        print(f"🔄 Ap achte {action} sou {asset} pou {duration}s...")
        
        if action == "call":
            trade_id, deal_data = po_client.buy(asset=asset, amount=amount, time=duration)
        else:
            trade_id, deal_data = po_client.sell(asset=asset, amount=amount, time=duration)
            
        print(f"✅ Lòd pase. ID: {trade_id}")
        time.sleep(duration + 5)
        
        result = po_client.check_win(trade_id)
        print(f"📊 Rezilta trade: {result}")
        return result['result']

    except Exception as e:
        print(f"❌ Erè pandan trade: {e}")
        po_client = None
        return None

# ======================== NEW YORK TIME ========================
def get_new_york_time():
    return datetime.now(pytz.timezone('America/New_York'))

def format_ny_time():
    return get_new_york_time().strftime("%H:%M:%S")

def format_time_for_display(dt):
    return dt.strftime("%I:%M %p").lower()

# ======================== FCS API ========================
def get_fcs_data(pair):
    """Jwenn done mache nan FCS API"""
    try:
        symbol = pair.replace("-OTC", "").replace("/", "")
        url = f"https://api-v4.fcsapi.com/forex/quote/{symbol}?access_key={FCS_API_KEY}"
        
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get('status') and data.get('response'):
            quote = data['response'][0]
            df = pd.DataFrame([{
                'close': float(quote['c']),
                'high': float(quote['h']),
                'low': float(quote['l']),
                'open': float(quote['o'])
            }])
            return df
        else:
            return None
    except Exception as e:
        print(f"❌ Erè FCS API: {e}")
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
    if data is None or len(data) < 1:
        return random.choice(["BUY", "SELL"]), 60, "Limited data"
    
    try:
        last_price = data['close'].iloc[-1]
        open_price = data['open'].iloc[-1]
        
        if len(data) > 14:
            rsi = calculate_rsi(data)
            last_rsi = rsi.iloc[-1] if len(rsi) > 0 else 50
        else:
            last_rsi = 50
        
        if last_rsi < 40:
            return "BUY", 75, f"RSI {last_rsi:.1f} (oversold)"
        elif last_rsi > 60:
            return "SELL", 75, f"RSI {last_rsi:.1f} (overbought)"
        else:
            if last_price > open_price:
                return "BUY", 55, f"Price rising"
            else:
                return "SELL", 55, f"Price falling"
    except Exception as e:
        return random.choice(["BUY", "SELL"]), 60, "Analysis error"

def generate_signal():
    """Jenere siyal ki baze sou done FCS API"""
    pair = random.choice(PAIRS)
    print(f"🔄 Generating signal for {pair}...")
    
    data = get_fcs_data(pair)
    
    if data is None:
        print("⚠️ No data, using random")
        signal = random.choice(["BUY", "SELL"])
        confidence = 50
        reason = "API unavailable"
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
    except Exception as e:
        print(f"Error: {e}")

def edit_message(chat_id, message_id, text, buttons=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    data = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if buttons:
        data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Error: {e}")

def send_trade_report(chat_id):
    """Voye rapò dènye 15 trade yo"""
    if len(statistics["trades"]) == 0:
        send_message(chat_id, "📊 *No trades yet*")
        return
    
    report = "📊 *Dfg Sniper Bot OTC - Last 15 Trades*\n\n"
    
    for i, trade in enumerate(statistics["trades"], 1):
        report += f"{trade['pair']} {trade['time']} {trade['result']}\n"
    
    report += f"\n---\n"
    report += f"📈 **Wins & Losses:** {statistics['win']}\n"
    report += f"🎯 **Win Rate:** {statistics['win_rate']:.0f}%\n"
    report += f"\n**Channel Overall Win Rate:** {statistics['win_rate']:.0f}% ({statistics['win']}W/{statistics['loss']}L)"
    
    send_message(chat_id, report)

def send_signal_and_trade(chat_id, message_id, pair, signal, confidence, reason):
    """Voye siyal epi trade"""
    current_time = get_new_york_time()
    entry_time = current_time + timedelta(minutes=1)  # 1 minit anvan
    entry_time_str = entry_time.strftime("%H:%M:%S")
    
    # PREMYE MESAJ: Siyal la
    signal_message = f"""Dfg Sniper Bot OTC
POCKET OPTION

{pair}
{selected_timeframe}
{entry_time_str}
{signal.lower()}

How to start Trading
0 1 {format_time_for_display(current_time)}"""
    
    edit_message(chat_id, message_id, signal_message)
    
    # Rete tann 1 minit pou antre
    time.sleep(60)
    
    # Fè trade a
    result = pocket_option_trade(pair, signal)
    final_time = get_new_york_time()
    
    # Mete ajou estatistik
    if result == 'win':
        result_text = "WIN"
        statistics["win"] += 1
    elif result == 'loss':
        result_text = "LOSS ✖"
        statistics["loss"] += 1
    elif result == 'draw':
        result_text = "DRAW"
        statistics["total"] -= 1
    else:
        result_text = "FAILED"
        statistics["total"] -= 1
    
    if result in ['win', 'loss']:
        statistics["total"] += 1
        # Ajoute nan istwa trade yo
        statistics["trades"].append({
            "pair": pair,
            "time": final_time.strftime("%H:%M:%S"),
            "result": result_text
        })
    
    statistics["win_rate"] = (statistics["win"] / statistics["total"] * 100) if statistics["total"] > 0 else 0
    
    # DEZYÈM MESAJ: Rezilta a
    result_message = f"""# Dfg Sniper Bot OTC
## Last Hour Results ({final_time.strftime('%H:%M')} UTC-5)

{f'### {pair} {final_time.strftime("%H:%M:%S")} {result_text}'}"""
    
    edit_message(chat_id, message_id, result_message)
    
    # Si rive 15 trade, voye rapò
    if len(statistics["trades"]) >= 15:
        send_trade_report(chat_id)

def auto_signal_loop(chat_id):
    """Loop otomatik chak 3 minit"""
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
        
        time.sleep(180)  # 3 minit

def create_timeframe_buttons():
    buttons = []
    row = []
    tf_list = list(TIMEFRAMES.keys())
    for i, tf in enumerate(tf_list):
        row.append({"text": tf, "callback_data": f"set_tf_{tf}"})
        if len(row) == 3 or i == len(tf_list) - 1:
            buttons.append(row)
            row = []
    return buttons

# ======================== COMMAND HANDLING ========================
last_update_id = 0
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Dfg Sniper Bot OTC is running!"

def run_bot():
    global last_update_id, selected_timeframe, auto_signal_active

    print("=" * 50)
    print("🤖 Dfg Sniper Bot OTC ap demare...")
    print("=" * 50)

    if PO_AVAILABLE:
        connect_pocket_option()

    print(f"📊 FCS API Key: {FCS_API_KEY[:5]}...")
    print(f"📱 Telegram Token: {TELEGRAM_TOKEN[:10]}...")
    print("=" * 50)

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
                            welcome = f"""🎯 *Welcome to Dfg Sniper Bot OTC*

*Commands:*
/signal - Get one signal
/auto - Start auto signals (3 min)
/stop - Stop auto signals
/timeframe - Change timeframe
/stats - View statistics
/report - Last 15 trades report
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

                        elif text == "/report":
                            send_trade_report(chat_id)

                        elif text == "/help":
                            help_text = f"""📚 *Help*

/signal - Get one signal + trade
/auto - Start auto (3 min)
/stop - Stop auto
/timeframe - Change TF
/stats - View stats
/report - Last 15 trades

⏱️ Current TF: {selected_timeframe}"""
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
