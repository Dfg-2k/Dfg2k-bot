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

# ======================== KONFIGIRASYON ========================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TWELVE_DATA_API_KEY = os.environ.get('TWELVE_DATA_API_KEY')

# Lis pè pou swiv
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

# ======================== FONKSYON POU JWENN LÈ NEW YORK ========================
def jwenn_le_new_york():
    ny_tz = pytz.timezone('America/New_York')
    le_ny = datetime.now(ny_tz)
    return le_ny

def format_le_ny():
    le_ny = jwenn_le_new_york()
    return le_ny.strftime("%H:%M:%S")

# ======================== FONKSYON POU JWENN DONE AK ANALIZ ========================
def jwenn_done_twelve_data(pair):
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
        response = requests.get(url, params=params)
        data = response.json()
        
        if "values" in data:
            df = pd.DataFrame(data["values"])
            df = df.iloc[::-1]
            df['close'] = pd.to_numeric(df['close'])
            df['high'] = pd.to_numeric(df['high'])
            df['low'] = pd.to_numeric(df['low'])
            df['open'] = pd.to_numeric(df['open'])
            return df
        else:
            return None
    except:
        return None

def kalkile_rsi(data, period=14):
    close = data['close']
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def kalkile_macd(data):
    exp1 = data['close'].ewm(span=12, adjust=False).mean()
    exp2 = data['close'].ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    histogram = macd - signal
    return macd, signal, histogram

def detekte_siyal(data):
    if data is None or len(data) < 20:
        return random.choice(["BUY", "SELL"]), 65, "Done limite"
    
    rsi = kalkile_rsi(data)
    macd, signal, hist = kalkile_macd(data)
    
    dernye_rsi = rsi.iloc[-1] if len(rsi) > 0 else 50
    anvan_rsi = rsi.iloc[-2] if len(rsi) > 1 else 50
    dernye_hist = hist.iloc[-1] if len(hist) > 0 else 0
    anvan_hist = hist.iloc[-2] if len(hist) > 1 else 0
    
    pri_aktuèl = data['close'].iloc[-1]
    pri_anvan = data['close'].iloc[-2] if len(data) > 1 else pri_aktuèl
    
    # Siyal BUY
    if dernye_rsi < 55:
        if dernye_hist > anvan_hist:
            konfyans = int(70 - (dernye_rsi / 2))
            konfyans = max(60, min(90, konfyans))
            return "BUY", konfyans, f"RSI {dernye_rsi:.1f} + MACD ap monte"
        elif pri_aktuèl > pri_anvan:
            return "BUY", 65, f"RSI {dernye_rsi:.1f} + Pri ap monte"
    
    # Siyal SELL
    if dernye_rsi > 45:
        if dernye_hist < anvan_hist:
            konfyans = int(60 + (dernye_rsi / 3))
            konfyans = max(60, min(90, konfyans))
            return "SELL", konfyans, f"RSI {dernye_rsi:.1f} + MACD ap desann"
        elif pri_aktuèl < pri_anvan:
            return "SELL", 65, f"RSI {dernye_rsi:.1f} + Pri ap desann"
    
    # Si pa gen siyal klè
    if dernye_rsi < 50:
        return "BUY", 55, f"RSI {dernye_rsi:.1f} - Tendans pozitif"
    else:
        return "SELL", 55, f"RSI {dernye_rsi:.1f} - Tendans negatif"

def jenere_siyal_vre(pair_chwazi=None):
    if pair_chwazi:
        pair = pair_chwazi
    else:
        pair = random.choice(PAIRS)
    
    data = jwenn_done_twelve_data(pair)
    
    if data is None or len(data) < 20:
        siyal = random.choice(["BUY", "SELL"])
        konfyans = random.randint(60, 80)
        rezon = "Analiz limite"
        return pair, siyal, konfyans, rezon
    
    siyal, konfyans, rezon = detekte_siyal(data)
    return pair, siyal, konfyans, rezon

# ======================== FONKSYON TELEGRAM ========================
def voye_mesaj(chat_id, text, bouton=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if bouton:
        data["reply_markup"] = json.dumps({"inline_keyboard": bouton})
    
    try:
        requests.post(url, json=data)
    except Exception as e:
        print(f"Erè: {e}")

def modifye_mesaj(chat_id, message_id, text, bouton=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if bouton:
        data["reply_markup"] = json.dumps({"inline_keyboard": bouton})
    
    try:
        requests.post(url, json=data)
    except Exception as e:
        print(f"Erè: {e}")

def kreye_bouton_pairs():
    bouton = []
    ranje = []
    
    for i, pair in enumerate(PAIRS):
        ranje.append({"text": pair, "callback_data": f"select_pair_{pair}"})
        if len(ranje) == 2 or i == len(PAIRS) - 1:
            bouton.append(ranje)
            ranje = []
    
    return bouton

def voye_siyal_ak_preparasyon(chat_id, message_id, pair, siyal, konfyans, rezon):
    le_kounye_a = jwenn_le_new_york()
    le_antre = le_kounye_a + timedelta(minutes=1)
    le_kounye_a_str = le_kounye_a.strftime("%H:%M:%S")
    le_antre_str = le_antre.strftime("%H:%M:%S")
    
    emoji_siyal = "🟢" if siyal == "BUY" else "🔴"
    
    mesaj_preparasyon = f"""⚠️ *AVÈTISMAN SIYAL* ⚠️

━━━━━━━━━━━━━━━━━━━
**{pair}**
{emoji_siyal} Siyal: *{siyal}*
📊 Konfyans: {konfyans}%
📌 Rezon: {rezon}
━━━━━━━━━━━━━━━━━━━

🕐 *Lè New York kounye a:* {le_kounye_a_str}
⏳ *Lè pou antre:* {le_antre_str}

━━━━━━━━━━━━━━━━━━━
🔥 *PREPARE KOUNYE A!*
📱 Louvri Pocket Option
💰 Prepare montan w ap mete

*Map voye konte a nan 1 minit...* ⏱️"""
    
    modifye_mesaj(chat_id, message_id, mesaj_preparasyon)
    time.sleep(60)
    
    for i in range(60, 0, -1):
        le_kounye_a = jwenn_le_new_york()
        le_antre_str = (le_kounye_a + timedelta(seconds=i)).strftime("%H:%M:%S")
        
        text = f"""🚨 *DFG2K SIYAL TRADING* 🚨

━━━━━━━━━━━━━━━━━━━
**{pair}**
{emoji_siyal} Siyal: *{siyal}*
📊 Konfyans: {konfyans}%
📌 Rezon: {rezon}
━━━━━━━━━━━━━━━━━━━

⏳ *Antre nan:* {i}s
🕐 *Lè New York:* {le_kounye_a.strftime("%H:%M:%S")}
━━━━━━━━━━━━━━━━━━━

💡 *RETE KALM EPI SWIV PLAN AN*"""
        
        modifye_mesaj(chat_id, message_id, text)
        time.sleep(1)
    
    le_fen = jwenn_le_new_york()
    
    text_final = f"""✅ *DFG2K SIYAL TRADING* ✅

━━━━━━━━━━━━━━━━━━━
**{pair}**
{emoji_siyal} Siyal: *{siyal}*
📊 Konfyans: {konfyans}%
📌 Rezon: {rezon}
━━━━━━━━━━━━━━━━━━━

🕐 *Lè New York:* {le_fen.strftime("%H:%M:%S")}
━━━━━━━━━━━━━━━━━━━

🔥 *ESKE OU ANTRE?* 🔥"""
    
    bouton = [[
        {"text": "✅ WIN", "callback_data": f"win_{pair}"},
        {"text": "❌ LOSS", "callback_data": f"loss_{pair}"}
    ]]
    
    modifye_mesaj(chat_id, message_id, text_final, bouton)

# ======================== JESYON KOMAN ========================
last_update_id = 0
statistik = {"win": 0, "loss": 0, "total": 0}

# Flask server pou Koyeb
from flask import Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 DFG2K Bot ap mache 24/7!"

def run_bot():
    global last_update_id, statistik
    print("🤖 Bot la ap kouri...")
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            response = requests.get(url, params={
                "offset": last_update_id + 1,
                "timeout": 30
            }).json()
            
            if "result" in response:
                for update in response["result"]:
                    last_update_id = update["update_id"]
                    
                    if "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"]["text"]
                        
                        if text == "/start":
                            voye_mesaj(chat_id, "🎯 BYENVENI NAN DFG2K BOT!\n\n/siyal - jwenn siyal")
                        
                        elif text == "/siyal":
                            voye_mesaj(chat_id, "🔄 Ap chèche siyal...")
                            time.sleep(2)
                            
                            pair, siyal, konfyans, rezon = jenere_siyal_vre()
                            emoji = "🟢" if siyal == "BUY" else "🔴"
                            
                            result = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                                "chat_id": chat_id,
                                "text": f"📊 NOUVO SIYAL\n\n{emoji} {siyal}\n{pair}\n{konfyans}%\n{rezon}",
                                "parse_mode": "Markdown"
                            }).json()
                            
                            if result.get("ok"):
                                message_id = result["result"]["message_id"]
                                threading.Thread(target=voye_siyal_ak_preparasyon, 
                                               args=(chat_id, message_id, pair, siyal, konfyans, rezon)).start()
                    
                    elif "callback_query" in update:
                        cb = update["callback_query"]
                        chat_id = cb["message"]["chat"]["id"]
                        message_id = cb["message"]["message_id"]
                        data = cb["data"]
                        
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                                     json={"callback_query_id": cb["id"]})
                        
                        if data.startswith("win_"):
                            statistik["win"] += 1
                            statistik["total"] += 1
                            modifye_mesaj(chat_id, message_id, f"✅ WIN!")
                        elif data.startswith("loss_"):
                            statistik["loss"] += 1
                            statistik["total"] += 1
                            modifye_mesaj(chat_id, message_id, f"❌ LOSS")
            
            time.sleep(1)
        except Exception as e:
            print(f"Erè: {e}")
            time.sleep(5)

# Kòmanse bot la nan yon thread
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
