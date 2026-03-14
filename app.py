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

# ======================== STATISTIK ========================
statistik = {"win": 0, "loss": 0, "total": 0}
siyal_aktif = {}  # Pour suivre les signaux en cours

# ======================== LIS MOUN KI GEN DWA ========================
AUTHORIZED_USERS = [
    123456789,  # Mete ID ou isit la
]

def verifye_dwa(chat_id):
    """Tcheke si moun nan gen dwa itilize bot la"""
    if chat_id not in AUTHORIZED_USERS:
        print(f"🚫 Aksè refize pou ID: {chat_id}")
        return False
    return True

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
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if "values" in data:
            df = pd.DataFrame(data["values"])
            df = df.iloc[::-1]
            df['close'] = pd.to_numeric(df['close'])
            df['high'] = pd.to_numeric(df['high'])
            df['low'] = pd.to_numeric(df['low'])
            df['open'] = pd.to_numeric(df['open'])
            return df
        elif "code" in data and data["code"] == 429:
            return "limit"
        else:
            return None
    except Exception as e:
        print(f"❌ Erè API: {e}")
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
    
    if data == "limit":
        siyal = random.choice(["BUY", "SELL"])
        konfyans = 50
        rezon = "API limit depase - Siyal oaza"
        return pair, siyal, konfyans, rezon
    elif data is None or len(data) < 20:
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
        print(f"Erè lè voye mesaj: {e}")

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
        print(f"Erè lè modifye mesaj: {e}")

def voye_imaj(chat_id, foto, caption=""):
    """Voye yon imaj ak opsyon caption"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    data = {
        "chat_id": chat_id,
        "photo": foto,
        "caption": caption,
        "parse_mode": "Markdown"
    }
    
    try:
        requests.post(url, json=data)
    except Exception as e:
        print(f"Erè lè voye imaj: {e}")

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
    # Lè kounye a (New York)
    le_kounye_a = jwenn_le_new_york()
    le_antre = le_kounye_a + timedelta(minutes=1)
    le_kounye_a_str = le_kounye_a.strftime("%H:%M:%S")
    le_antre_str = le_antre.strftime("%H:%M:%S")
    le_fen = le_antre + timedelta(minutes=1)
    le_fen_str = le_fen.strftime("%H:%M:%S")
    
    emoji_siyal = "🟢" if siyal == "BUY" else "🔴"
    
    # Estoke enfòmasyon siyal la
    siyal_id = f"{chat_id}_{message_id}"
    siyal_aktif[siyal_id] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "pair": pair,
        "siyal": siyal,
        "le_antre": le_antre_str,
        "le_fen": le_fen_str,
        "konfyans": konfyans
    }
    
    # PREMYE MESAJ: Avètisman 1 minit anvan
    mesaj_preparasyon = f"""⚠️ *AVÈTISMAN SIYAL* ⚠️

━━━━━━━━━━━━━━━━━━━
**{pair}**
{emoji_siyal} Siyal: *{siyal}*
📊 Konfyans: {konfyans}%
📌 Rezon: {rezon}
━━━━━━━━━━━━━━━━━━━

🕐 *Lè New York kounye a:* {le_kounye_a_str}
⏳ *Lè pou antre:* {le_antre_str}
⌛️ *Lè pou fèmen:* {le_fen_str}

━━━━━━━━━━━━━━━━━━━
🔥 *PREPARE KOUNYE A!*
📱 Louvri Pocket Option
💰 Prepare montan w ap mete

*Map voye konte a nan 1 minit...* ⏱️"""
    
    modifye_mesaj(chat_id, message_id, mesaj_preparasyon)
    time.sleep(60)
    
    # DEZYÈM MESAJ: Kòmanse konte a (60 segonn)
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
⌛️ *Lè pou antre:* {le_antre_str}
━━━━━━━━━━━━━━━━━━━

💡 *RETE KALM EPI SWIV PLAN AN*"""
        
        modifye_mesaj(chat_id, message_id, text)
        time.sleep(1)
    
    # TWAZYÈM MESAJ: Apre konte a fini (mande rezilta)
    le_fen = jwenn_le_new_york()
    
    text_final = f"""⏰ *TRADE FÈMEN* ⏰

━━━━━━━━━━━━━━━━━━━
**{pair}**
{emoji_siyal} Siyal: *{siyal}*
📊 Konfyans: {konfyans}%
━━━━━━━━━━━━━━━━━━━

🕐 *Lè fèmen:* {le_fen.strftime("%H:%M:%S")}
━━━━━━━━━━━━━━━━━━━

🔥 *KISA REZILTA A?* 🔥

Klike anba a pou rapòte:"""
    
    bouton = [[
        {"text": "✅ WIN", "callback_data": f"win_{pair}_{message_id}"},
        {"text": "❌ LOSS", "callback_data": f"loss_{pair}_{message_id}"}
    ]]
    
    modifye_mesaj(chat_id, message_id, text_final, bouton)

# ======================== JESYON KOMAN ========================
last_update_id = 0

# Flask server pou Koyeb
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 DFG2K Bot ap mache 24/7!"

def run_bot():
    global last_update_id, statistik, siyal_aktif
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
                    
                    # Tcheke si se yon mesaj
                    if "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"]["text"]
                        
                        # Verifye dwa
                        if not verifye_dwa(chat_id):
                            continue
                        
                        if text == "/start":
                            mesaj_byenveni = f"""🎯 *BYENVENI NAN DFG2K SIYAL BOT* 🎯

Mwen se yon bot ki bay siyal trading an tan reyèl pou **Pocket Option** ak lòt plateforme.

━━━━━━━━━━━━━━━━━━━
*📊 KOMAN DISPONIB:*
/siyal - Jwenn yon siyal imedyat
/swiv - Kòmanse swiv siyal otomatik
/estatistik - Wè pèfòmans bot la
/ede - Jwenn èd

━━━━━━━━━━━━━━━━━━━
*💡 KIJAN LI MARCHE?*
1️⃣ Tape /siyal
2️⃣ M ap bay yon siyal ak nivo konfyans
3️⃣ Apre 1 minit, konfime si se WIN oswa LOSS

━━━━━━━━━━━━━━━━━━━
🕐 *Lè New York:* {format_le_ny()}
━━━━━━━━━━━━━━━━━━━
👑 Devlope pa @Dfg2k"""
                            
                            voye_mesaj(chat_id, mesaj_byenveni)
                        
                        elif text == "/siyal":
                            voye_mesaj(chat_id, "🔄 Ap chèche siyal...")
                            time.sleep(2)
                            
                            pair, siyal, konfyans, rezon = jenere_siyal_vre()
                            emoji = "🟢" if siyal == "BUY" else "🔴"
                            
                            result = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                                "chat_id": chat_id,
                                "text": f"""📊 *NOUVO SIYAL DETECTE*

━━━━━━━━━━━━━━━━━━━
**{pair}**
{emoji} Siyal: *{siyal}*
📈 Konfyans: {konfyans}%
📌 Rezon: {rezon}
━━━━━━━━━━━━━━━━━━━

⏰ *Map voye detay yo...* 🔄""",
                                "parse_mode": "Markdown"
                            }).json()
                            
                            if result.get("ok"):
                                message_id = result["result"]["message_id"]
                                threading.Thread(target=voye_siyal_ak_preparasyon, 
                                               args=(chat_id, message_id, pair, siyal, konfyans, rezon)).start()
                        
                        elif text == "/swiv":
                            voye_mesaj(chat_id, """⚙️ *FONKSYON AN DEVELOPMENT*

Pou kounye a, ou ka itilize /siyal pou jwenn siyal manyèlman.

*Vèsyon Pwochen an pral gen:*
✅ Siyal otomatik chak 30 minit
✅ Notifikasyon an tan reyèl

Mèsi paske w ap itilize DFG2K Bot! 🙏""")
                        
                        elif text == "/estatistik":
                            win_rate = (statistik["win"] / statistik["total"] * 100) if statistik["total"] > 0 else 0
                            mesaj_stat = f"""📊 *ESTATISTIK BOT LA*

━━━━━━━━━━━━━━━━━━━
✅ Win: {statistik['win']}
❌ Loss: {statistik['loss']}
📊 Total: {statistik['total']}
📈 Win Rate: {win_rate:.1f}%
━━━━━━━━━━━━━━━━━━━

🕐 *Lè New York:* {format_le_ny()}
━━━━━━━━━━━━━━━━━━━

*Kontinye fè konfyans nan siyal yo!* 💪"""
                            voye_mesaj(chat_id, mesaj_stat)
                        
                        elif text == "/ede":
                            mesaj_ede = f"""📚 *ÈD AK SIPO*

━━━━━━━━━━━━━━━━━━━
*KOMAN YO:*
/siyal - Jwenn siyal imedyat
/swiv - Kòmanse swiv otomatik
/estatistik - Wè pèfòmans

━━━━━━━━━━━━━━━━━━━
*KOU MANJE:*
1️⃣ Tape /siyal pou jwenn siyal
2️⃣ Antre trade a nan 60s
3️⃣ Apre 1 minit, di si se WIN oswa LOSS
4️⃣ Gade estatistik ou amelyore!

━━━━━━━━━━━━━━━━━━━
*KONTAK ADMIN:*
👤 @Dfg2k

Mèsi paske w ap itilize bot sa! 🙏"""
                            voye_mesaj(chat_id, mesaj_ede)
                    
                    # Tcheke si se yon repons bouton (WIN/LOSS)
                    elif "callback_query" in update:
                        cb = update["callback_query"]
                        chat_id = cb["message"]["chat"]["id"]
                        message_id = cb["message"]["message_id"]
                        data = cb["data"]
                        
                        # Reponn pou retire chajman an
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                                     json={"callback_query_id": cb["id"]})
                        
                        if data.startswith("win_"):
                            parts = data.split("_")
                            pair = parts[1]
                            siyal_id = f"{chat_id}_{parts[2]}"
                            
                            statistik["win"] += 1
                            statistik["total"] += 1
                            
                            siyal_info = siyal_aktif.get(siyal_id, {})
                            le_antre = siyal_info.get("le_antre", "N/A")
                            le_fen = siyal_info.get("le_fen", "N/A")
                            
                            mesaj_konfimasyon = f"""✅ *WIN KONFIRME* ✅

━━━━━━━━━━━━━━━━━━━
**{pair}**
━━━━━━━━━━━━━━━━━━━
📊 Rezilta: *WIN* 🎉
⏰ Lè antre: {le_antre}
⏰ Lè fèmen: {le_fen}
━━━━━━━━━━━━━━━━━━━
📈 Win rate: {statistik['win']/statistik['total']*100:.1f}%
━━━━━━━━━━━━━━━━━━━

Felisitasyon! 🎉"""
                            
                            modifye_mesaj(chat_id, message_id, mesaj_konfimasyon)
                            
                            # Retire siyal la nan lis aktif
                            if siyal_id in siyal_aktif:
                                del siyal_aktif[siyal_id]
                        
                        elif data.startswith("loss_"):
                            parts = data.split("_")
                            pair = parts[1]
                            siyal_id = f"{chat_id}_{parts[2]}"
                            
                            statistik["loss"] += 1
                            statistik["total"] += 1
                            
                            siyal_info = siyal_aktif.get(siyal_id, {})
                            le_antre = siyal_info.get("le_antre", "N/A")
                            le_fen = siyal_info.get("le_fen", "N/A")
                            
                            mesaj_konfimasyon = f"""❌ *LOSS KONFIRME* ❌

━━━━━━━━━━━━━━━━━━━
**{pair}**
━━━━━━━━━━━━━━━━━━━
📊 Rezilta: *LOSS* 😢
⏰ Lè antre: {le_antre}
⏰ Lè fèmen: {le_fen}
━━━━━━━━━━━━━━━━━━━
📈 Win rate: {statistik['win']/statistik['total']*100:.1f}%
━━━━━━━━━━━━━━━━━━━

Pa dekouraje, pwochen an ap pi bon! 💪"""
                            
                            modifye_mesaj(chat_id, message_id, mesaj_konfimasyon)
                            
                            # Retire siyal la nan lis aktif
                            if siyal_id in siyal_aktif:
                                del siyal_aktif[siyal_id]
            
            time.sleep(1)
        except Exception as e:
            print(f"Erè: {e}")
            time.sleep(5)

# Kòmanse bot la nan yon thread
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
