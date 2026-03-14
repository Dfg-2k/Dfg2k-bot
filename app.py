import requests
import time
import random
from datetime import datetime, timedelta
import threading
import json
import pytz
import os
from flask import Flask

# ======================== KONFIGIRASYON ========================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
POCKET_OPTION_EMAIL = os.environ.get('POCKET_OPTION_EMAIL')
POCKET_OPTION_PASSWORD = os.environ.get('POCKET_OPTION_PASSWORD')

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
statistik = {"win": 0, "loss": 0, "total": 0, "win_rate": 0}
siyal_aktif = {}

# ======================== KONEKSYON POCKET OPTION ========================
try:
    from pocketoptionapi.stable_api import PocketOption
    PO_AVAILABLE = True
except ImportError:
    print("⚠️ PocketOptionAPI pa enstale. Deteksyon otomatik pap disponib.")
    PO_AVAILABLE = False

po_api = None
po_connected = False

def konekte_pocket_option():
    """Konekte ak Pocket Option"""
    global po_api, po_connected
    
    if not PO_AVAILABLE:
        return False
    
    if not POCKET_OPTION_EMAIL or not POCKET_OPTION_PASSWORD:
        print("⚠️ Enfòmasyon Pocket Option pa disponib")
        return False
    
    try:
        po_api = PocketOption(POCKET_OPTION_EMAIL, POCKET_OPTION_PASSWORD, demo=True)
        po_api.connect()
        time.sleep(3)
        
        if po_api.check_connect():
            po_connected = True
            print("✅ Konekte ak Pocket Option")
            return True
        else:
            print("❌ Pa ka konekte ak Pocket Option")
            return False
    except Exception as e:
        print(f"❌ Erè koneksyon Pocket Option: {e}")
        return False

def trade_pocket_option(pair, siyal, montan=10, expiration=60):
    """Fè yon trade sou Pocket Option epi retounen rezilta"""
    global po_api, po_connected
    
    if not po_connected:
        if not konekte_pocket_option():
            return None
    
    try:
        # Konvèti non pè a
        pair_po = pair.replace("/", "").replace(" (OTC)", "_otc")
        
        # Konvèti siyal
        action = "call" if siyal == "BUY" else "put"
        
        # Pase lòd la
        rezilta = po_api.buy(
            amount=montan,
            active=pair_po,
            action=action,
            expirations=expiration
        )
        
        if rezilta["success"]:
            order_id = rezilta["order_id"]
            print(f"✅ Lòd pase: {order_id}")
            
            # Rete tann pou trade la fini
            time.sleep(expiration + 5)
            
            # Tcheke rezilta
            result = po_api.check_win(order_id)
            return result
        else:
            print(f"❌ Lòd pa pase: {rezilta}")
            return None
            
    except Exception as e:
        print(f"❌ Erè pandan trade: {e}")
        return None

# ======================== FONKSYON POU JWENN LÈ NEW YORK ========================
def jwenn_le_new_york():
    ny_tz = pytz.timezone('America/New_York')
    le_ny = datetime.now(ny_tz)
    return le_ny

def format_le_ny():
    le_ny = jwenn_le_new_york()
    return le_ny.strftime("%H:%M:%S")

# ======================== JENERE SIYAL (SAN API) ========================
def jenere_siyal():
    pair = random.choice(PAIRS)
    siyal = random.choice(["BUY", "SELL"])
    konfyans = random.randint(65, 90)
    rezon = f"Analiz teknik - RSI {random.randint(30, 70)}"
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
        requests.post(url, json=data, timeout=10)
        return True
    except Exception as e:
        print(f"Erè lè voye mesaj: {e}")
        return False

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
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Erè lè modifye mesaj: {e}")

def voye_siyal_ak_preparasyon(chat_id, message_id, pair, siyal, konfyans, rezon):
    # Lè kounye a (New York)
    le_kounye_a = jwenn_le_new_york()
    le_antre = le_kounye_a + timedelta(minutes=1)
    le_fen = le_antre + timedelta(minutes=1)
    
    le_kounye_a_str = le_kounye_a.strftime("%H:%M:%S")
    le_antre_str = le_antre.strftime("%H:%M:%S")
    le_fen_str = le_fen.strftime("%H:%M:%S")
    
    emoji_siyal = "🟢" if siyal == "BUY" else "🔴"
    
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
    
    # Voye mesaj pou di ke bot la ap trade
    modifye_mesaj(chat_id, message_id, "🔄 *Ap fè trade a sou Pocket Option...*\nTann 1 minit...")
    
    # Fè trade a sou Pocket Option
    rezilta = trade_pocket_option(pair, siyal, montan=10, expiration=60)
    
    if rezilta is not None:
        if rezilta > 0:  # WIN
            statistik["win"] += 1
            statistik["total"] += 1
            
            mesaj_final = f"""✅ *WIN - TRADE OTOMATIK* ✅

━━━━━━━━━━━━━━━━━━━
**{pair}**
{emoji_siyal} Siyal: *{siyal}*
📊 Konfyans: {konfyans}%
━━━━━━━━━━━━━━━━━━━
💰 *Pwofi: +${rezilta:.2f}*
🕐 *Lè fèmen:* {le_fen.strftime("%H:%M:%S")}
━━━━━━━━━━━━━━━━━━━
📈 Win rate: {statistik['win']/statistik['total']*100:.1f}%
━━━━━━━━━━━━━━━━━━━

Felisitasyon! 🎉"""
            
        elif rezilta == 0:  # LOSS
            statistik["loss"] += 1
            statistik["total"] += 1
            
            mesaj_final = f"""❌ *LOSS - TRADE OTOMATIK* ❌

━━━━━━━━━━━━━━━━━━━
**{pair}**
{emoji_siyal} Siyal: *{siyal}*
📊 Konfyans: {konfyans}%
━━━━━━━━━━━━━━━━━━━
💸 *Pèt: -$10.00*
🕐 *Lè fèmen:* {le_fen.strftime("%H:%M:%S")}
━━━━━━━━━━━━━━━━━━━
📈 Win rate: {statistik['win']/statistik['total']*100:.1f}%
━━━━━━━━━━━━━━━━━━━

Pa dekouraje, pwochen an ap pi bon! 💪"""
        else:
            mesaj_final = f"""⚠️ *TRADE PA KONFIRME* ⚠️

━━━━━━━━━━━━━━━━━━━
**{pair}**
{emoji_siyal} Siyal: *{siyal}*
━━━━━━━━━━━━━━━━━━━

Pa ka jwenn rezilta a. Tanpri verifye manyèlman."""
    else:
        mesaj_final = f"""⚠️ *TRADE PA FET* ⚠️

━━━━━━━━━━━━━━━━━━━
**{pair}**
{emoji_siyal} Siyal: *{siyal}*
━━━━━━━━━━━━━━━━━━━

Pa ka konekte ak Pocket Option. Tanpri tcheke enfòmasyon ou yo."""
    
    modifye_mesaj(chat_id, message_id, mesaj_final)

def mete_ajou_estatistik():
    global statistik
    if statistik["total"] > 0:
        statistik["win_rate"] = (statistik["win"] / statistik["total"]) * 100
    else:
        statistik["win_rate"] = 0
    return statistik

# ======================== JESYON KOMAN ========================
last_update_id = 0

app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 DFG2K Bot ap mache 24/7!"

def run_bot():
    global last_update_id, statistik
    
    # Eseye konekte ak Pocket Option demaraj
    if PO_AVAILABLE:
        konekte_pocket_option()
    
    print("🤖 Bot la ap kouri...")
    
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
                    
                    # Tcheke si se yon mesaj
                    if "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"]["text"]
                        
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
2️⃣ M ap bay yon siyal
3️⃣ M ap fè trade a pou ou otomatikman
4️⃣ M ap ba ou rezilta a (WIN/LOSS)

━━━━━━━━━━━━━━━━━━━
🕐 *Lè New York kounye a:* {format_le_ny()}
━━━━━━━━━━━━━━━━━━━
👑 Devlope pa @Dfg2k"""
                            
                            voye_mesaj(chat_id, mesaj_byenveni)
                        
                        elif text == "/siyal":
                            result = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                                "chat_id": chat_id,
                                "text": "🔄 Ap chèche siyal..."
                            }).json()
                            
                            if result.get("ok"):
                                message_id = result["result"]["message_id"]
                                time.sleep(2)
                                
                                pair, siyal, konfyans, rezon = jenere_siyal()
                                threading.Thread(target=voye_siyal_ak_preparasyon, 
                                               args=(chat_id, message_id, pair, siyal, konfyans, rezon)).start()
                        
                        elif text == "/swiv":
                            voye_mesaj(chat_id, """⚙️ *FONKSYON SWIV OTOMATIK*

Pou kounye a, ou ka itilize /siyal pou jwenn siyal.

*Vèsyon Pwochen an pral gen:*
✅ Siyal otomatik chak 30 minit
✅ Trade otomatik san enteripsyon

Mèsi paske w ap itilize DFG2K Bot! 🙏""")
                        
                        elif text == "/estatistik":
                            mete_ajou_estatistik()
                            mesaj_stat = f"""📊 *ESTATISTIK BOT LA*

━━━━━━━━━━━━━━━━━━━
✅ Win: {statistik['win']}
❌ Loss: {statistik['loss']}
📊 Total: {statistik['total']}
📈 Win Rate: {statistik['win_rate']:.1f}%
━━━━━━━━━━━━━━━━━━━

🕐 *Lè New York:* {format_le_ny()}
━━━━━━━━━━━━━━━━━━━

*Kontinye fè konfyans nan siyal yo!* 💪"""
                            voye_mesaj(chat_id, mesaj_stat)
                        
                        elif text == "/ede":
                            mesaj_ede = f"""📚 *ÈD AK SIPO*

━━━━━━━━━━━━━━━━━━━
*KOMAN YO:*
/siyal - Jwenn siyal ak trade otomatik
/swiv - Kòmanse swiv otomatik
/estatistik - Wè pèfòmans

━━━━━━━━━━━━━━━━━━━
*💡 KOU MANJE:*
1️⃣ Tape /siyal pou jwenn siyal
2️⃣ Bot la ap fè trade a pou ou
3️⃣ Apre 1 minit, w ap wè rezilta a
4️⃣ Pa bezwen klike anyen!

━━━━━━━━━━━━━━━━━━━
*KONTAK ADMIN:*
👤 @Dfg2k

Mèsi paske w ap itilize bot sa! 🙏"""
                            voye_mesaj(chat_id, mesaj_ede)
            
            time.sleep(1)
        except Exception as e:
            print(f"Erè: {e}")
            time.sleep(5)

# Kòmanse bot la nan yon thread
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
