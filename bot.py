“””
Dfg Sniper Bot OTC — Siyal REYÈL via BinaryOptionsToolsV2
Estrateji: RSI + EMA crossover + Chandèl pattern (otomatik)
Lè: New York UTC-5
“””

import os
import asyncio
import logging
import random
import threading
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

try:
from BinaryOptionsToolsV2.pocketoption import PocketOptionAsync
BOT_REAL = True
except ImportError:
BOT_REAL = False

logging.basicConfig(format=”%(asctime)s %(levelname)s %(message)s”, level=logging.INFO)
logger = logging.getLogger(**name**)

# ══════════════════════════════════════════════════════════════════════════════

# MINI WEB SERVER — pou Render plan gratis

# ══════════════════════════════════════════════════════════════════════════════

class HealthHandler(BaseHTTPRequestHandler):
def do_GET(self):
self.send_response(200)
self.end_headers()
self.wfile.write(b”Dfg Sniper Bot OTC - Running!”)
def log_message(self, format, *args):
pass  # silenye log yo

def start_web_server():
port = int(os.getenv(“PORT”, 8000))
server = HTTPServer((“0.0.0.0”, port), HealthHandler)
logger.info(f”Web server ap kouri sou pò {port}”)
server.serve_forever()

# ══════════════════════════════════════════════════════════════════════════════

# CONFIG

# ══════════════════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN = os.getenv(
“TELEGRAM_BOT_TOKEN”,
“8615131640:AAHGQiYyP5uNqc6zU1QooJShcwlfqcwvur8”
)
POCKET_SSID = os.getenv(
“POCKET_OPTION_SSID”,
‘42[“auth”, {“sessionToken”:“610648e6d940f217a9e05b179aac75ad”,’
‘“uid”:“124162892”,“lang”:“en”,“currentUrl”:“cabinet”,“isChart”:1}]’
)
NY_TZ = timezone(timedelta(hours=-5))
OTC_PAIRS = [
“EURUSD_otc”,“GBPUSD_otc”,“USDJPY_otc”,“AUDUSD_otc”,“USDCAD_otc”,
“USDCHF_otc”,“NZDUSD_otc”,“EURGBP_otc”,“EURJPY_otc”,“GBPJPY_otc”,
“AUDCAD_otc”,“EURCAD_otc”,
]
TRADE_AMOUNT = 1

# ══════════════════════════════════════════════════════════════════════════════

# STATE

# ══════════════════════════════════════════════════════════════════════════════

chat_state: dict = {}

def get_state(chat_id):
if chat_id not in chat_state:
chat_state[chat_id] = {“trades”: [], “total_win”: 0, “total_loss”: 0, “auto_running”: False}
return chat_state[chat_id]

# ══════════════════════════════════════════════════════════════════════════════

# ANALIZ TEKNIK

# ══════════════════════════════════════════════════════════════════════════════

def calc_rsi(prices, period=14):
if len(prices) < period + 1:
return 50.0
gains, losses = [], []
for i in range(1, len(prices)):
d = prices[i] - prices[i-1]
gains.append(max(d, 0))
losses.append(max(-d, 0))
ag = sum(gains[-period:]) / period
al = sum(losses[-period:]) / period
if al == 0:
return 100.0
return 100 - (100 / (1 + ag/al))

def calc_ema(prices, period):
if len(prices) < period:
return prices[-1] if prices else 0
k = 2 / (period + 1)
ema = prices[0]
for p in prices[1:]:
ema = p * k + ema * (1 - k)
return ema

def detect_candle_pattern(candles):
if len(candles) < 2:
return None
po, ph, pl, pc = candles[-2]
co, ch, cl, cc = candles[-1]
body = abs(cc - co)
rng  = ch - cl or 0.0001
if body / rng < 0.1:
return None
if pc < po and cc > co and co <= pc and cc >= po:
return “call”
if pc > po and cc < co and co >= pc and cc <= po:
return “put”
return None

def decide_direction(candles, closes):
rsi   = calc_rsi(closes)
ema5  = calc_ema(closes, 5)
ema20 = calc_ema(closes, 20)
cpat  = detect_candle_pattern(candles)
sc = sp = 0
reasons = []
if rsi < 30:
sc += 2; reasons.append(f”RSI={rsi:.1f}↓CALL”)
elif rsi > 70:
sp += 2; reasons.append(f”RSI={rsi:.1f}↑PUT”)
else:
reasons.append(f”RSI={rsi:.1f}”)
if ema5 > ema20:
sc += 1; reasons.append(“EMA5>EMA20→CALL”)
else:
sp += 1; reasons.append(“EMA5<EMA20→PUT”)
if cpat == “call”:
sc += 2; reasons.append(“Bullish Engulf→CALL”)
elif cpat == “put”:
sp += 2; reasons.append(“Bearish Engulf→PUT”)
direction = “call” if sc >= sp else “put”
tf = “M1” if (rsi < 30 or rsi > 70) else “M5”
return direction, tf, “ | “.join(reasons)

# ══════════════════════════════════════════════════════════════════════════════

# POCKET OPTION

# ══════════════════════════════════════════════════════════════════════════════

async def get_candles_and_decide(pair):
if not BOT_REAL:
d = random.choice([“call”,“put”])
return d, “M5”, “Demo mode”
try:
api = PocketOptionAsync(POCKET_SSID)
await api.connect()
raw = await api.get_candles(pair, 60, 50)
await api.close()
if not raw or len(raw) < 10:
d = random.choice([“call”,“put”])
return d, “M1”, “Pa ase done”
candles = [[c[“open”],c[“high”],c[“low”],c[“close”]] for c in raw]
closes  = [c[“close”] for c in raw]
return decide_direction(candles, closes)
except Exception as e:
logger.error(f”get_candles ere: {e}”)
d = random.choice([“call”,“put”])
return d, “M1”, f”Ere: {e.**class**.**name**}”

async def execute_trade(pair, direction, tf):
if not BOT_REAL:
profit = round(random.uniform(0.7,1.8),2) if random.random()<0.68 else -TRADE_AMOUNT
return {“profit”: profit, “result”: “WIN ✅” if profit>0 else “LOSS ❌”}
tf_map = {“M1”:60,“M5”:300,“M15”:900,“M30”:1800,“H1”:3600}
duration = tf_map.get(tf, 60)
try:
api = PocketOptionAsync(POCKET_SSID)
await api.connect()
trade_id, _ = await api.buy(asset=pair, amount=TRADE_AMOUNT, action=direction, expiration=duration)
await asyncio.sleep(duration + 5)
res = await api.check_win(trade_id)
await api.close()
profit = res.get(“profit”, 0)
return {“profit”: profit, “result”: “WIN ✅” if profit>0 else “LOSS ❌”}
except Exception as e:
logger.error(f”execute_trade ere: {e}”)
return {“profit”: 0, “result”: “LOSS ❌”}

# ══════════════════════════════════════════════════════════════════════════════

# MESAJ

# ══════════════════════════════════════════════════════════════════════════════

def ny_now():
return datetime.now(NY_TZ)

def fp(pair):
return pair.replace(”_otc”,”-OTC”).upper()

def signal_msg(pair, tf, entry_time, direction, sig_time, reason):
arrow = “📈 CALL ✅” if direction==“call” else “📉 PUT 🔻”
return (
f”🎯 *Dfg Sniper Bot OTC*\n📊 POCKET OPTION\n\n”
f”💱 *Pair:* `{fp(pair)}`\n”
f”⏱ *Timeframe:* `{tf}`\n”
f”🕐 *Entry Time:* `{entry_time}`\n”
f”📊 *Signal:* *{arrow}*\n\n”
f”🧠 *Analiz:* `{reason}`\n\n”
f”━━━━━━━━━━━━━━\n”
f”📌 How to start Trading\n0️⃣ 1️⃣  `{sig_time}`”
)

def result_msg(pair, tf, entry_time, result, profit, le):
ps = f”+${abs(profit):.2f}” if profit>0 else f”-${abs(profit):.2f}”
return (
f”# 🤖 Dfg Sniper Bot OTC\n”
f”## Last Hour Results ({le} UTC-5)\n\n”
f”### `{fp(pair)}` | `{tf}` | `{entry_time}` | *{result}*\n”
f”💰 Profit: `{ps}`”
)

def report_msg(trades, total_w, total_l):
last15 = trades[-15:]
lines  = [f”`{fp(t['pair'])}` | `{t['tf']}` | `{t['time']}` | *{t[‘result’]}*” for t in last15]
w15    = sum(1 for t in last15 if “WIN” in t[“result”])
l15    = len(last15)-w15
wr15   = round(w15/len(last15)*100) if last15 else 0
total  = total_w+total_l
wrt    = round(total_w/total*100) if total else 0
return (
f”📊 *Dfg Sniper Bot OTC — Last 15 Trades*\n\n”
+ “\n”.join(lines)
+ f”\n\n━━━━━━━━━━━━━━\n”
f”📈 Wins: *{w15}* | Losses: *{l15}*\n”
f”🎯 Win Rate (last 15): *{wr15}%*\n\n”
f”📡 Channel Overall Win Rate: *{wrt}%* ({total_w}W/{total_l}L)”
)

# ══════════════════════════════════════════════════════════════════════════════

# KORE

# ══════════════════════════════════════════════════════════════════════════════

async def run_one_trade(bot, chat_id, state):
pair = random.choice(OTC_PAIRS)
direction, tf, reason = await get_candles_and_decide(pair)
now        = ny_now()
entry_time = (now + timedelta(minutes=1)).strftime(”%H:%M”)
sig_time   = now.strftime(”%H:%M”)
await bot.send_message(chat_id, signal_msg(pair,tf,entry_time,direction,sig_time,reason), parse_mode=“Markdown”)
await asyncio.sleep(60)
tr     = await execute_trade(pair, direction, tf)
result = tr[“result”]
profit = tr[“profit”]
now_ny = ny_now().strftime(”%H:%M”)
await bot.send_message(chat_id, result_msg(pair,tf,entry_time,result,profit,now_ny), parse_mode=“Markdown”)
state[“trades”].append({“pair”:pair,“tf”:tf,“time”:entry_time,“result”:result})
if “WIN” in result: state[“total_win”]  += 1
else:               state[“total_loss”] += 1
if len(state[“trades”]) % 15 == 0:
await bot.send_message(chat_id, report_msg(state[“trades”],state[“total_win”],state[“total_loss”]), parse_mode=“Markdown”)

# ══════════════════════════════════════════════════════════════════════════════

# KÒMAND

# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
mode = “🟢 REYEL (Pocket Option konekte)” if BOT_REAL else “🟡 DEMO”
await update.message.reply_text(
f”👋 *Byenveni nan Dfg Sniper Bot OTC!*\n\n”
f”🔌 Mod: {mode}\n\n”
f”📋 *Komand yo:*\n”
f”/signal  — Siyal reyal kounye a\n”
f”/auto    — Siyal otomatik chak 3 minit\n”
f”/stop    — Kanpe siyal otomatik\n”
f”/stats   — Estatistik ou yo\n”
f”/report  — Denye 15 trade\n”
f”/help    — Afiche ed\n\n”
f”Komanse ak /signal oubyen /auto!”, parse_mode=“Markdown”)

async def cmd_help(update, ctx): await cmd_start(update, ctx)

async def cmd_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
chat_id = update.effective_chat.id
await update.message.reply_text(“🔍 *Ap analiz mache a…* ⏳”, parse_mode=“Markdown”)
await run_one_trade(ctx.bot, chat_id, get_state(chat_id))

async def auto_job(ctx: ContextTypes.DEFAULT_TYPE):
chat_id = ctx.job.chat_id
state   = get_state(chat_id)
if state[“auto_running”]:
await run_one_trade(ctx.bot, chat_id, state)

async def cmd_auto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
chat_id = update.effective_chat.id
state   = get_state(chat_id)
if state[“auto_running”]:
await update.message.reply_text(“Deja kouri! Tape /stop pou kanpe.”)
return
state[“auto_running”] = True
for j in ctx.job_queue.get_jobs_by_name(f”auto_{chat_id}”): j.schedule_removal()
ctx.job_queue.run_repeating(auto_job, interval=180, first=5, chat_id=chat_id, name=f”auto_{chat_id}”)
await update.message.reply_text(“✅ *Siyal otomatik komanse!*\nTape /stop pou kanpe.”, parse_mode=“Markdown”)

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
chat_id = update.effective_chat.id
state   = get_state(chat_id)
if not state[“auto_running”]:
await update.message.reply_text(“Pa gen siyal otomatik k ap kouri.”)
return
state[“auto_running”] = False
for j in ctx.job_queue.get_jobs_by_name(f”auto_{chat_id}”): j.schedule_removal()
await update.message.reply_text(“🛑 *Siyal otomatik kanpe.*”, parse_mode=“Markdown”)

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
chat_id = update.effective_chat.id
state   = get_state(chat_id)
total   = state[“total_win”]+state[“total_loss”]
wr      = round(state[“total_win”]/total*100) if total else 0
await update.message.reply_text(
f”📊 *Estatistik — Dfg Sniper Bot OTC*\n\n”
f”✅ Wins:     *{state[‘total_win’]}*\n”
f”❌ Losses:   *{state[‘total_loss’]}*\n”
f”📈 Total:    *{total}*\n”
f”🎯 Win Rate: *{wr}%*”, parse_mode=“Markdown”)

async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
chat_id = update.effective_chat.id
state   = get_state(chat_id)
if not state[“trades”]:
await update.message.reply_text(“Pa gen trade toujou. Komanse ak /signal!”)
return
await update.message.reply_text(report_msg(state[“trades”],state[“total_win”],state[“total_loss”]), parse_mode=“Markdown”)

# ══════════════════════════════════════════════════════════════════════════════

# MAIN

# ══════════════════════════════════════════════════════════════════════════════

def main():
# Kouri web server nan yon thread separe
web_thread = threading.Thread(target=start_web_server, daemon=True)
web_thread.start()

```
app = Application.builder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start",  cmd_start))
app.add_handler(CommandHandler("help",   cmd_help))
app.add_handler(CommandHandler("signal", cmd_signal))
app.add_handler(CommandHandler("auto",   cmd_auto))
app.add_handler(CommandHandler("stop",   cmd_stop))
app.add_handler(CommandHandler("stats",  cmd_stats))
app.add_handler(CommandHandler("report", cmd_report))
logger.info("Dfg Sniper Bot OTC — Siyal REYAL aktive!")
app.run_polling(drop_pending_updates=True)
```

if **name** == “**main**”:
main()
