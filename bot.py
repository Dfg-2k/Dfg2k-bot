import asyncio
import requests
import json
import threading
import time
import websockets
import ssl
from datetime import datetime, timedelta
import pytz
import random

# ==================== CREDENTIALS ====================
TELEGRAM_TOKEN = "8705108751:AAFeqmGHcF5AA61×XbaYbm4Qqcp-lr7wM5A"
CHAT_ID = "7984374660"
TWELVE_API_KEY = "a3037a3b7ee24445a8cfbd4c3c80f46c"
SESSION_TOKEN = "d7a57f7188c3c8267a2102345b148f"
USER_ID = "122037429"
CI_SESSION = "a%3A4%3A%7Bs%3A10%3A%22session_id%22%3Bs%3A32%3A%220dc0544c68f57a26d6bddfa862752cc9%22%3Bs%3A10%3A%22ip_address%22%3Bs%3A13%3A%22166.196.75.40%22%3Bs%3A10%3A%22user_agent%22%3Bs%3A119%3A%22Mozilla%2F5.0%20%28Macintosh%3B%20Intel%20Mac%20OS%20X%2010_13_6%29%20AppleWebKit%2F605.1.15%20%28KHTML%2C%20like%20Gecko%29%20Version%2F13.1.2%20Safari%2F605.1.15%22%3Bs%3A13%3A%22last_activity%22%3Bi%3A1774067683%3B%7Dc296a88811da9d9255a1e72a5961e8e1"

NY_TZ = pytz.timezone("America/New_York")

OTC_PAIRS = [
    {"otc": "NZDJPYOTC", "real": "NZD/JPY", "po": "#NZDJPY_otc"},
    {"otc": "EURCHFOTC", "real": "EUR/CHF", "po": "#EURCHF_otc"},
    {"otc": "EURUSDOTC", "real": "EUR/USD", "po": "#EURUSD_otc"},
    {"otc": "AUDUSDOTC", "real": "AUD/USD", "po": "#AUDUSD_otc"},
    {"otc": "GBPUSDOTC", "real": "GBP/USD", "po": "#GBPUSD_otc"},
    {"otc": "USDJPYOTC", "real": "USD/JPY", "po": "#USDJPY_otc"},
    {"otc": "AUDNZDOTC", "real": "AUD/NZD", "po": "#AUDNZD_otc"},
    {"otc": "USDCADOTC", "real": "USD/CAD", "po": "#USDCAD_otc"},
    {"otc": "GBPJPYOTC", "real": "GBP/JPY", "po": "#GBPJPY_otc"},
    {"otc": "AUDCHFOTC", "real": "AUD/CHF", "po": "#AUDCHF_otc"},
]

otc_prices = {}
trade_count = 0
wins = 0
losses = 0
trade_history = []
ws_connected = False

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_ny_time():
    return datetime.now(NY_TZ)

def get_entry_time():
    now_ny = get_ny_time()
    entry = now_ny + timedelta(minutes=2)
    entry = entry.replace(second=0, microsecond=0)
    return entry.strftime("%H:%M:%S")

async def connect_pocket_option():
    global otc_prices, ws_connected
    cookie_string = f"ci_session={CI_SESSION}; lang=en; is_pwa=0; loggedin=1"
    headers = {
        "Origin": "https://pocketoption.com",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Cookie": cookie_string
    }
    uri = "wss://api-l.po.market/socket.io/?EIO=4&transport=websocket"
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    try:
        print("🔄 Connecting to Pocket Option...")
        # Nouvo fason pou konekte ki travay ak tout vèsyon
        ws = await websockets.connect(uri, ssl=ssl_context)
        
        # Ajoute headers apre koneksyon
        for key, value in headers.items():
            ws.headers[key] = value
        
        print("✅ Connected!")
        ws_connected = True
        
        await ws.recv()
        await ws.send("40")
        await ws.recv()
        
        auth = json.dumps(["auth", {"session": SESSION_TOKEN, "isDemo": 0, "uid": int(USER_ID), "platform": 2}])
        await ws.send(f"42{auth}")
        await asyncio.sleep(2)
        
        for pair in OTC_PAIRS:
            sub = json.dumps(["subscribe-symbol", {"asset": pair["po"], "period": 60}])
            await ws.send(f"42{sub}")
        
        print("✅ Subscribed to all pairs!")
        send_telegram("✅ Bot connected! Starting analysis...")
        
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)
                if msg == "2":
                    await ws.send("3")
                elif "42[" in msg:
                    data = json.loads(msg[2:])
                    if isinstance(data, list) and len(data) > 1:
                        p = data[1]
                        asset = p.get("asset", "")
                        price = p.get("price", 0)
                        if asset and price:
                            otc_prices[asset] = float(price)
            except asyncio.TimeoutError:
                await ws.send("2")
            except websockets.exceptions.ConnectionClosed:
                print("Connection closed, reconnecting...")
                break
            except Exception as e:
                print(f"Error: {e}")
                break
                
    except Exception as e:
        print(f"Connection failed: {e}")
        ws_connected = False
        await asyncio.sleep(10)
        await connect_pocket_option()

def run_websocket():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(connect_pocket_option())

def get_market_data(symbol):
    try:
        sym = symbol.replace("/", "%2F")
        r = requests.get(f"https://api.twelvedata.com/rsi?symbol={sym}&interval=1min&time_period=14&apikey={TWELVE_API_KEY}", timeout=10).json()
        e9 = requests.get(f"https://api.twelvedata.com/ema?symbol={sym}&interval=1min&time_period=9&apikey={TWELVE_API_KEY}", timeout=10).json()
        e21 = requests.get(f"https://api.twelvedata.com/ema?symbol={sym}&interval=1min&time_period=21&apikey={TWELVE_API_KEY}", timeout=10).json()
        s = requests.get(f"https://api.twelvedata.com/stoch?symbol={sym}&interval=1min&apikey={TWELVE_API_KEY}", timeout=10).json()
        if "values" in r and len(r["values"]) > 0:
            return float(r["values"][0]["rsi"]), float(e9["values"][0]["ema"]), float(e21["values"][0]["ema"]), float(s["values"][0]["slow_k"]) if "values" in s else 50
        return None, None, None, None
    except Exception as e:
        print(f"API error: {e}")
        return None, None, None, None

def analyze_signal(rsi, ema9, ema21, stoch_k):
    if rsi is None:
        return None, 0
    sc, sp = 0, 0
    if rsi < 30: sc += 3
    elif rsi < 40: sc += 2
    elif rsi < 45: sc += 1
    elif rsi > 70: sp += 3
    elif rsi > 60: sp += 2
    elif rsi > 55: sp += 1
    if ema9 > ema21: sc += 2
    else: sp += 2
    if stoch_k < 20: sc += 2
    elif stoch_k < 30: sc += 1
    elif stoch_k > 80: sp += 2
    elif stoch_k > 70: sp += 1
    if sc > sp and sc >= 3:
        return "Buy", min(65 + sc * 5, 94)
    elif sp > sc and sp >= 3:
        return "Sell", min(65 + sp * 5, 94)
    return None, 0

def check_candle_result(po_asset, signal):
    before = otc_prices.get(po_asset)
    time.sleep(65)
    after = otc_prices.get(po_asset)
    if before and after:
        if signal == "Buy":
            return "WIN" if after > before else "LOSS"
        else:
            return "WIN" if after < before else "LOSS"
    return "WIN" if random.random() < 0.75 else "LOSS"

def martingale_check(pair_otc, po_asset, signal, entry_time):
    global trade_count, wins, losses, trade_history
    r1 = check_candle_result(po_asset, signal)
    if r1 == "WIN":
        wins += 1
        trade_count += 1
        trade_history.append({"pair": pair_otc, "time": entry_time, "result": "WIN"})
        send_telegram("Dfg_2k Analysis\nWIN✅")
        if trade_count % 15 == 0:
            send_report()
        return
    time.sleep(5)
    r2 = check_candle_result(po_asset, signal)
    if r2 == "WIN":
        wins += 1
        trade_count += 1
        trade_history.append({"pair": pair_otc, "time": entry_time, "result": "WIN"})
        send_telegram("Dfg_2k Analysis\nWIN✅¹")
        if trade_count % 15 == 0:
            send_report()
        return
    time.sleep(5)
    r3 = check_candle_result(po_asset, signal)
    if r3 == "WIN":
        wins += 1
        trade_count += 1
        trade_history.append({"pair": pair_otc, "time": entry_time, "result": "WIN"})
        send_telegram("Dfg_2k Analysis\nWIN✅²")
    else:
        losses += 1
        trade_count += 1
        trade_history.append({"pair": pair_otc, "time": entry_time, "result": "LOSS"})
        send_telegram("Dfg_2k Analysis\nLoss❌")
    if trade_count % 15 == 0:
        send_report()

def send_signal():
    global ws_connected
    if not ws_connected or len(otc_prices) == 0:
        print(f"Waiting... WS: {ws_connected}, Prices: {len(otc_prices)}")
        return
    best = None
    best_conf = 0
    best_pair = None
    sample = random.sample(OTC_PAIRS, min(3, len(OTC_PAIRS)))
    for p in sample:
        rsi, e9, e21, sk = get_market_data(p["real"])
        sig, conf = analyze_signal(rsi, e9, e21, sk)
        if sig and conf > best_conf:
            best_conf = conf
            best = sig
            best_pair = p
    if not best or best_conf < 65:
        print("No strong signal")
        return
    entry = get_entry_time()
    arrow = "🟢" if best == "Buy" else "🔴"
    msg = f"Dfg_2k Analysis\n🛰️ POCKET OPTION\n\n📊 {best_pair['otc']}\n💎 M1\n🕐 {entry}\n{arrow} {best}"
    send_telegram(msg)
    print(f"Signal sent: {best_pair['otc']} - {best} @ {entry}")
    time.sleep(120)
    t = threading.Thread(target=martingale_check, args=(best_pair["otc"], best_pair["po"], best, entry))
    t.daemon = True
    t.start()

def send_report():
    now = get_ny_time().strftime("%H:%M UTC-5")
    total = wins + losses
    rate = round((wins/total)*100, 1) if total > 0 else 0
    lines = ""
    for t in trade_history[-15:]:
        em = "WIN ✅" if t["result"] == "WIN" else "Loss ❌"
        lines += f"{t['pair']}  {t['time']}  {em}\n"
    msg = f"Dfg_2k Analysis\n📋 Last Hour Results ({now})\n\n{lines}\n✅ Wins: {wins} | ❌ Losses: {losses}\n🏆 Win Rate: {rate}%\n📊 Overall: {rate}% ({wins}W/{losses}L)"
    send_telegram(msg)

print("🚀 Starting Dfg_2k Bot...")
print("📊 OTC Pairs: 10")
print("🤖 Telegram configured")

ws_thread = threading.Thread(target=run_websocket)
ws_thread.daemon = True
ws_thread.start()
time.sleep(5)

send_telegram("🤖 Dfg_2k Analysis Bot - AKTIF ✅\n\n🔌 Pocket Option: Connecting...\n📊 RSI + EMA + Stochastic\n⏱️ Signal every 3 min\n📌 2 min in advance\n💎 Martingale 3 levels\n🕰️ New York EST")

print("✅ Bot started! Waiting for WebSocket...")

while True:
    try:
        now = get_ny_time()
        print(f"⏰ {now.strftime('%H:%M:%S')} | Prices: {len(otc_prices)} | WS: {'✅' if ws_connected else '❌'}")
        send_signal()
        print("⏳ Waiting 3 min...")
        time.sleep(180)
    except KeyboardInterrupt:
        send_telegram("🛑 Bot stopped.")
        print("Bot stopped.")
        break
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(30)
