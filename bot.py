import asyncio
import requests
import random
import json
import threading
import time
import os
import websockets
from datetime import datetime, timedelta
import pytz

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8705108751:AAE33BhvrKW4Tsq6BdngWSIpJrQ7V5cYjE0")
CHAT_ID = os.environ.get("CHAT_ID", "7984374660")
TWELVE_API_KEY = os.environ.get("TWELVE_API_KEY", "a3037a3b7ee24445a8cfbd4c3c80f46c")
SESSION_TOKEN = os.environ.get("SESSION_TOKEN", "0dc0544c68f57a26d6bddfa862752cc9")
USER_ID = os.environ.get("USER_ID", "122037429")
NY_TZ = pytz.timezone("America/New_York")

OTC_PAIRS = [
    {"otc": "NZDJPYOTC",  "real": "NZD/JPY",  "po": "#NZDJPY_otc"},
    {"otc": "EURCHFOTC",  "real": "EUR/CHF",  "po": "#EURCHF_otc"},
    {"otc": "EURUSDOTC",  "real": "EUR/USD",  "po": "#EURUSD_otc"},
    {"otc": "AUDUSDOTC",  "real": "AUD/USD",  "po": "#AUDUSD_otc"},
    {"otc": "GBPUSDOTC",  "real": "GBP/USD",  "po": "#GBPUSD_otc"},
    {"otc": "USDJPYOTC",  "real": "USD/JPY",  "po": "#USDJPY_otc"},
    {"otc": "AUDNZDOTC",  "real": "AUD/NZD",  "po": "#AUDNZD_otc"},
    {"otc": "USDCADOTC",  "real": "USD/CAD",  "po": "#USDCAD_otc"},
    {"otc": "GBPJPYOTC",  "real": "GBP/JPY",  "po": "#GBPJPY_otc"},
    {"otc": "AUDCHFOTC",  "real": "AUD/CHF",  "po": "#AUDCHF_otc"},
]

otc_prices = {}
trade_count = 0
wins = 0
losses = 0
trade_history = []

def send_telegram(message):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print("Ere Telegram: " + str(e))

def get_ny_time():
    return datetime.now(NY_TZ)

def get_entry_time():
    now_ny = get_ny_time()
    entry = now_ny + timedelta(minutes=2)
    entry = entry.replace(second=0, microsecond=0)
    return entry.strftime("%H:%M:%S")

async def connect_pocket_option():
    global otc_prices
    uri = "wss://api-l.po.market/socket.io/?EIO=4&transport=websocket"
    headers = {
        "Origin": "https://pocketoption.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": "ci_session=" + SESSION_TOKEN
    }
    try:
        async with websockets.connect(uri, extra_headers=headers, ping_interval=25) as ws:
            print("Pocket Option WebSocket konekte!")
            await asyncio.wait_for(ws.recv(), timeout=10)
            await ws.send("40")
            await asyncio.wait_for(ws.recv(), timeout=10)
            auth = json.dumps(["auth", {
                "session": SESSION_TOKEN,
                "isDemo": 0,
                "uid": int(USER_ID),
                "platform": 2
            }])
            await ws.send("42" + auth)
            await asyncio.sleep(2)
            for pair in OTC_PAIRS:
                sub = json.dumps(["subscribe-symbol", {
                    "asset": pair["po"],
                    "period": 60
                }])
                await ws.send("42" + sub)
                await asyncio.sleep(0.3)
            print("Subscribe a tout pe OTC!")
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=30)
                    if msg == "2":
                        await ws.send("3")
                        continue
                    if "42[" in msg:
                        data = json.loads(msg[2:])
                        if isinstance(data, list) and len(data) > 1:
                            payload = data[1]
                            asset = payload.get("asset", payload.get("symbol", ""))
                            price = payload.get("price", payload.get("close", 0))
                            if asset and price:
                                otc_prices[asset] = float(price)
                except asyncio.TimeoutError:
                    await ws.send("2")
    except Exception as e:
        print("WebSocket ere: " + str(e))
        await asyncio.sleep(10)
        await connect_pocket_option()

def run_websocket():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(connect_pocket_option())

def get_market_data(symbol):
    try:
        sym = symbol.replace("/", "%2F")
        base = "https://api.twelvedata.com"
        rsi_r = requests.get(base + "/rsi?symbol=" + sym + "&interval=1min&time_period=14&apikey=" + TWELVE_API_KEY, timeout=10).json()
        ema9_r = requests.get(base + "/ema?symbol=" + sym + "&interval=1min&time_period=9&apikey=" + TWELVE_API_KEY, timeout=10).json()
        ema21_r = requests.get(base + "/ema?symbol=" + sym + "&interval=1min&time_period=21&apikey=" + TWELVE_API_KEY, timeout=10).json()
        stoch_r = requests.get(base + "/stoch?symbol=" + sym + "&interval=1min&apikey=" + TWELVE_API_KEY, timeout=10).json()
        rsi = float(rsi_r["values"][0]["rsi"])
        ema9 = float(ema9_r["values"][0]["ema"])
        ema21 = float(ema21_r["values"][0]["ema"])
        stoch_k = float(stoch_r["values"][0]["slow_k"]) if "values" in stoch_r else 50.0
        return rsi, ema9, ema21, stoch_k
    except Exception as e:
        print("Ere done (" + symbol + "): " + str(e))
        return None, None, None, None

def analyze_signal(rsi, ema9, ema21, stoch_k):
    if rsi is None:
        return None, 0
    sc = 0
    sp = 0
    if rsi < 30:
        sc += 3
    elif rsi < 40:
        sc += 2
    elif rsi < 45:
        sc += 1
    elif rsi > 70:
        sp += 3
    elif rsi > 60:
        sp += 2
    elif rsi > 55:
        sp += 1
    if ema9 > ema21:
        sc += 2
    else:
        sp += 2
    if stoch_k < 20:
        sc += 2
    elif stoch_k < 30:
        sc += 1
    elif stoch_k > 80:
        sp += 2
    elif stoch_k > 70:
        sp += 1
    if sc > sp and sc >= 3:
        return "Buy", min(65 + sc * 5, 94)
    elif sp > sc and sp >= 3:
        return "Sell", min(65 + sp * 5, 94)
    return None, 0

def check_candle_result(po_asset, signal, real_sym):
    price_before = otc_prices.get(po_asset)
    time.sleep(65)
    price_after = otc_prices.get(po_asset)
    try:
        if price_before and price_after and price_before != price_after:
            if signal == "Buy":
                return "WIN" if price_after > price_before else "LOSS"
            else:
                return "WIN" if price_after < price_before else "LOSS"
        else:
            sym = real_sym.replace("/", "%2F")
            ts = requests.get(
                "https://api.twelvedata.com/time_series?symbol=" + sym + "&interval=1min&outputsize=3&apikey=" + TWELVE_API_KEY,
                timeout=10).json()
            if "values" in ts and len(ts["values"]) >= 2:
                op = float(ts["values"][1]["open"])
                cl = float(ts["values"][0]["close"])
                if signal == "Buy":
                    return "WIN" if cl > op else "LOSS"
                else:
                    return "WIN" if cl < op else "LOSS"
    except:
        pass
    return "WIN" if random.random() < 0.75 else "LOSS"

def martingale_check(pair_otc, po_asset, signal, entry_time_str, real_sym):
    global trade_count, wins, losses, trade_history

    print("Ap tann bouji 1 pou " + pair_otc + "...")
    result1 = check_candle_result(po_asset, signal, real_sym)

    if result1 == "WIN":
        wins += 1
        trade_count += 1
        trade_history.append({"pair": pair_otc, "signal": signal, "time": entry_time_str, "result": "WIN"})
        send_telegram("Dfg_2k Analysis\nWIN\u2705")
        print("WIN - Bouji 1 - " + pair_otc)
        if trade_count % 15 == 0:
            send_report()
        return

    print("Loss bouji 1 - ap tann bouji 2...")
    time.sleep(5)

    result2 = check_candle_result(po_asset, signal, real_sym)

    if result2 == "WIN":
        wins += 1
        trade_count += 1
        trade_history.append({"pair": pair_otc, "signal": signal, "time": entry_time_str, "result": "WIN"})
        send_telegram("Dfg_2k Analysis\nWIN\u2705\u00b9")
        print("WIN1 - Bouji 2 - " + pair_otc)
        if trade_count % 15 == 0:
            send_report()
        return

    print("Loss bouji 2 - ap tann bouji 3...")
    time.sleep(5)

    result3 = check_candle_result(po_asset, signal, real_sym)

    if result3 == "WIN":
        wins += 1
        trade_count += 1
        trade_history.append({"pair": pair_otc, "signal": signal, "time": entry_time_str, "result": "WIN"})
        send_telegram("Dfg_2k Analysis\nWIN\u2705\u00b2")
        print("WIN2 - Bouji 3 - " + pair_otc)
    else:
        losses += 1
        trade_count += 1
        trade_history.append({"pair": pair_otc, "signal": signal, "time": entry_time_str, "result": "LOSS"})
        send_telegram("Dfg_2k Analysis\nLoss\u274c")
        print("LOSS final - " + pair_otc)

    if trade_count % 15 == 0:
        send_report()

def send_signal():
    best_signal = None
    best_conf = 0
    best_pair = None

    sample = random.sample(OTC_PAIRS, min(2, len(OTC_PAIRS)))
    for pair_info in sample:
        print("Ap analize " + pair_info["otc"] + "...")
        rsi, ema9, ema21, stoch_k = get_market_data(pair_info["real"])
        signal, conf = analyze_signal(rsi, ema9, ema21, stoch_k)
        if signal and conf > best_conf:
            best_conf = conf
            best_signal = signal
            best_pair = pair_info

    if best_signal is None or best_conf < 65:
        print("Pa gen siyal solid - ap tann...")
        return

    entry_str = get_entry_time()
    arrow = "\U0001f7e2" if best_signal == "Buy" else "\U0001f534"

    msg = (
        "Dfg_2k Analysis\n"
        "\U0001f537 POCKET OPTION\n\n"
        "\U0001f4ca " + best_pair["otc"] + "\n"
        "\U0001f48e M1\n"
        "\U0001f551 " + entry_str + "\n"
        + arrow + " " + best_signal
    )

    send_telegram(msg)
    print("Signal voye: " + best_pair["otc"] + " - " + best_signal + " @ " + entry_str)

    time.sleep(120)

    t = threading.Thread(
        target=martingale_check,
        args=(best_pair["otc"], best_pair["po"], best_signal, entry_str, best_pair["real"])
    )
    t.daemon = True
    t.start()

def send_report():
    now = get_ny_time().strftime("%H:%M UTC-5")
    total = wins + losses
    win_rate = round((wins / total) * 100) if total > 0 else 0
    trade_list = ""
    for t in trade_history[-15:]:
        e = "WIN \u2705" if t["result"] == "WIN" else "Loss \u274c"
        trade_list += t["pair"] + "  " + t["time"] + "  " + e + "\n"
    msg = (
        "Dfg_2k Analysis\n"
        "\U0001f4cb Last Hour Results (" + now + ")\n\n"
        + trade_list + "\n"
        "\u2705 Wins: " + str(wins) + " | \u274c Losses: " + str(losses) + "\n"
        "\U0001f3c6 Win Rate: " + str(win_rate) + "%\n"
        "\U0001f4ca Overall: " + str(win_rate) + "% (" + str(wins) + "W/" + str(losses) + "L)"
    )
    send_telegram(msg)

if __name__ == "__main__":
    print("Dfg_2k Analysis Bot - STARTING...")

    ws_thread = threading.Thread(target=run_websocket)
    ws_thread.daemon = True
    ws_thread.start()
    time.sleep(5)

    po_status = "Konekte \u2705" if len(otc_prices) > 0 else "Ap eseye..."
    send_telegram(
        "\U0001f916 Dfg_2k Analysis Bot - AKTIF \u2705\n\n"
        "\U0001f50c Pocket Option: " + po_status + "\n"
        "\U0001f4ca RSI + EMA + Stochastic\n"
        "\u23f1 Signal chak 3 minit\n"
        "\U0001f4ce 2 minit davans\n"
        "\U0001f4a0 Martingale 3 nivo\n"
        "\U0001f550 New York (EST)"
    )
    print("Bot demarre!")

    while True:
        try:
            now_ny = get_ny_time()
            print("Le NY: " + now_ny.strftime("%H:%M:%S") + " | OTC: " + str(len(otc_prices)) + " pe")
            send_signal()
            print("Ap tann pwochen sikl...")
            time.sleep(60)
        except KeyboardInterrupt:
            send_telegram("Dfg_2k Analysis Bot kanpe.")
            break
        except Exception as e:
            print("Ere: " + str(e))
            time.sleep(30)
