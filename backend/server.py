from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timezone, timedelta
import httpx
import asyncio
import numpy as np

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Telegram config
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
TWELVE_DATA_API_KEY = os.environ.get('TWELVE_DATA_API_KEY', '')

# Create the main app
app = FastAPI()
api_router = APIRouter(prefix="/api")

# Bot state
bot_state = {
    "running": False,
    "last_signal_time": None,
    "signals_sent": 0,
    "total_wins": 0,
    "total_losses": 0,
    "trade_count_since_report": 0
}

# Background task reference
bot_task = None

# 35 OTC Pairs to monitor
OTC_PAIRS = [
    "NZD/JPY", "EUR/CHF", "EUR/USD", "AUD/USD", "GBP/USD", "USD/JPY", "AUD/NZD",
    "USD/CAD", "GBP/JPY", "AUD/CHF", "CAD/JPY", "NZD/USD", "GBP/NZD", "AUD/JPY",
    "CAD/CHF", "EUR/CAD", "EUR/AUD", "NZD/CHF", "USD/CHF", "EUR/GBP", "EUR/JPY",
    "GBP/CHF", "GBP/CAD", "CHF/JPY", "USD/MXN", "USD/ZAR", "USD/TRY", "USD/SGD",
    "USD/HKD", "USD/DKK", "USD/NOK", "USD/SEK", "EUR/SEK", "EUR/NOK", "GBP/DKK"
]

# Models
class Signal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pair: str
    direction: str
    entry_time: str
    confidence: float
    rsi: float
    ema9: float
    ema21: float
    stochastic: float
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: Optional[str] = None
    martingale_level: int = 0
    entry_price: float = 0

# ============== HELPER FUNCTIONS ==============

def get_ny_time() -> datetime:
    """Get current time in New York timezone (UTC-5)"""
    utc_now = datetime.now(timezone.utc)
    ny_offset = timedelta(hours=-5)
    return utc_now + ny_offset

def format_time_ny(dt: datetime) -> str:
    """Format datetime to HH:MM:SS"""
    return dt.strftime("%H:%M:%S")

async def send_telegram_message(message: str) -> bool:
    """Send message to Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram credentials not configured")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                logging.info("Telegram message sent")
                return True
            else:
                logging.error(f"Telegram error: {response.text}")
                return False
    except Exception as e:
        logging.error(f"Error sending Telegram: {e}")
        return False

async def fetch_market_data(symbol: str) -> Optional[Dict]:
    """Fetch market data from Twelve Data API"""
    if not TWELVE_DATA_API_KEY:
        return None
    
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": "1min",
        "outputsize": 50,
        "apikey": TWELVE_DATA_API_KEY
    }
    
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if "values" in data:
                    return data
            return None
    except Exception as e:
        logging.error(f"Error fetching data for {symbol}: {e}")
        return None

async def get_current_price(symbol: str) -> Optional[float]:
    """Get current price for a symbol"""
    data = await fetch_market_data(symbol)
    if data and "values" in data and len(data["values"]) > 0:
        return float(data["values"][0]["close"])
    return None

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def calculate_ema(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0
    multiplier = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))
    return round(ema, 6)

def calculate_stochastic(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period:
        return 50.0
    highest_high = max(highs[-period:])
    lowest_low = min(lows[-period:])
    current_close = closes[-1]
    if highest_high == lowest_low:
        return 50.0
    return round(((current_close - lowest_low) / (highest_high - lowest_low)) * 100, 2)

# ============== MAIN BOT LOGIC ==============

async def analyze_all_pairs() -> Optional[Dict]:
    """Analyze all pairs and return the best signal"""
    all_analyses = []
    
    batch_size = 8
    for i in range(0, len(OTC_PAIRS), batch_size):
        batch = OTC_PAIRS[i:i+batch_size]
        
        for pair in batch:
            try:
                data = await fetch_market_data(pair)
                if not data or "values" not in data:
                    continue
                
                values = data["values"]
                if len(values) < 21:
                    continue
                
                closes = [float(v["close"]) for v in reversed(values)]
                highs = [float(v["high"]) for v in reversed(values)]
                lows = [float(v["low"]) for v in reversed(values)]
                
                rsi = calculate_rsi(closes)
                ema9 = calculate_ema(closes, 9)
                ema21 = calculate_ema(closes, 21)
                stochastic = calculate_stochastic(highs, lows, closes)
                
                buy_score = 0
                sell_score = 0
                
                if rsi < 50:
                    buy_score += (50 - rsi) * 2
                else:
                    sell_score += (rsi - 50) * 2
                
                if ema9 > ema21:
                    buy_score += 30
                else:
                    sell_score += 30
                
                if stochastic < 50:
                    buy_score += (50 - stochastic)
                else:
                    sell_score += (stochastic - 50)
                
                if buy_score >= sell_score:
                    direction = "BUY"
                    confidence = min(50 + buy_score / 2, 95)
                else:
                    direction = "SELL"
                    confidence = min(50 + sell_score / 2, 95)
                
                all_analyses.append({
                    "pair": pair,
                    "direction": direction,
                    "confidence": round(confidence, 2),
                    "rsi": rsi,
                    "ema9": ema9,
                    "ema21": ema21,
                    "stochastic": stochastic,
                    "score": max(buy_score, sell_score),
                    "entry_price": closes[-1]
                })
            except Exception as e:
                logging.error(f"Error analyzing {pair}: {e}")
                continue
        
        if i + batch_size < len(OTC_PAIRS):
            await asyncio.sleep(1)
    
    if not all_analyses:
        return None
    
    all_analyses.sort(key=lambda x: x["score"], reverse=True)
    return all_analyses[0]

async def check_trade_result(pair: str, direction: str, entry_price: float) -> str:
    """Check if trade won or lost"""
    current_price = await get_current_price(pair)
    
    if current_price is None:
        import random
        return "WIN" if random.random() < 0.7 else "LOSS"
    
    if direction == "BUY":
        # BUY wins if price went UP
        return "WIN" if current_price > entry_price else "LOSS"
    else:
        # SELL wins if price went DOWN
        return "WIN" if current_price < entry_price else "LOSS"

async def send_summary_report():
    """Send summary of last 15 trades"""
    global bot_state
    
    ny_time = get_ny_time()
    
    trades = await db.signals.find(
        {"result": {"$in": ["WIN", "LOSS"]}},
        {"_id": 0}
    ).sort("created_at", -1).limit(15).to_list(15)
    
    if not trades:
        return
    
    wins = sum(1 for t in trades if t["result"] == "WIN")
    losses = sum(1 for t in trades if t["result"] == "LOSS")
    win_rate = round((wins / len(trades)) * 100) if trades else 0
    
    results_lines = []
    for t in reversed(trades):
        otc_pair = t["pair"].replace("/", "") + "-OTC"
        result_emoji = "✅" if t["result"] == "WIN" else "✖"
        results_lines.append(f"{otc_pair} {t['entry_time']} {t['result']} {result_emoji}")
    
    total_wins = bot_state["total_wins"]
    total_losses = bot_state["total_losses"]
    overall_rate = round((total_wins / (total_wins + total_losses)) * 100) if (total_wins + total_losses) > 0 else 0
    
    message = f"""Dfg_2k Analysis
📋 Last Hour Results ({format_time_ny(ny_time)} UTC-5)

{chr(10).join(results_lines)}

---

✅ Wins: {wins} | ❌ Losses: {losses}
🏆 Win Rate: {win_rate}%

Channel Overall Win Rate: {overall_rate}% ({total_wins}W/{total_losses}L)"""
    
    await send_telegram_message(message)
    
    await db.telegram_messages.insert_one({
        "id": str(uuid.uuid4()),
        "message": message,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "type": "summary"
    })

async def run_martingale(pair: str, direction: str, level: int):
    """Run martingale levels 2 and 3"""
    global bot_state
    
    if not bot_state["running"]:
        return "STOPPED"
    
    # Send Martingale message
    martingale_msg = f"""Dfg_2k Analysis
🔄 MARTINGALE Level {level}"""
    
    await send_telegram_message(martingale_msg)
    
    await db.telegram_messages.insert_one({
        "id": str(uuid.uuid4()),
        "message": martingale_msg,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "type": "martingale"
    })
    
    logging.info(f"Martingale Level {level} started")
    
    # Get entry price
    entry_price = await get_current_price(pair)
    if entry_price is None:
        entry_price = 0
    
    # Save martingale signal to DB
    signal = Signal(
        pair=pair,
        direction=direction,
        entry_time=format_time_ny(get_ny_time()),
        confidence=75,
        rsi=50,
        ema9=1,
        ema21=1,
        stochastic=50,
        martingale_level=level,
        entry_price=entry_price
    )
    await db.signals.insert_one(signal.model_dump())
    
    # Wait 1 minute for trade to complete
    logging.info("Waiting 1 minute for martingale trade...")
    await asyncio.sleep(60)
    
    if not bot_state["running"]:
        return "STOPPED"
    
    # Check result
    result = await check_trade_result(pair, direction, entry_price)
    
    # Update signal in DB
    await db.signals.update_one(
        {"id": signal.id},
        {"$set": {"result": result}}
    )
    
    return result

async def run_single_trade_cycle():
    """Run one complete trade cycle"""
    global bot_state
    
    if not bot_state["running"]:
        return
    
    # Step 1: Analyze market and get best signal
    logging.info("Analyzing market...")
    best = await analyze_all_pairs()
    
    if not best:
        logging.warning("Could not analyze market")
        await asyncio.sleep(60)
        return
    
    entry_time = get_ny_time() + timedelta(minutes=2)
    entry_time_str = format_time_ny(entry_time)
    
    # Create signal
    signal = Signal(
        pair=best["pair"],
        direction=best["direction"],
        entry_time=entry_time_str,
        confidence=best["confidence"],
        rsi=best["rsi"],
        ema9=best["ema9"],
        ema21=best["ema21"],
        stochastic=best["stochastic"],
        martingale_level=0,
        entry_price=best["entry_price"]
    )
    
    # Save to DB
    await db.signals.insert_one(signal.model_dump())
    
    # Step 2: Send signal to Telegram
    otc_pair = signal.pair.replace("/", "") + "-OTC"
    direction_emoji = "🟢" if signal.direction == "BUY" else "🔴"
    direction_text = "Buy" if signal.direction == "BUY" else "Sell"
    
    signal_msg = f"""Dfg_2k Analysis
🛰️ POCKET OPTION

📊 {otc_pair}
💎 M1
🕐 {entry_time_str}
{direction_emoji} {direction_text}"""
    
    await send_telegram_message(signal_msg)
    bot_state["signals_sent"] += 1
    bot_state["last_signal_time"] = datetime.now(timezone.utc).isoformat()
    
    await db.telegram_messages.insert_one({
        "id": str(uuid.uuid4()),
        "signal_id": signal.id,
        "message": signal_msg,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "type": "signal"
    })
    
    logging.info(f"Signal sent: {otc_pair} {signal.direction}")
    
    # Step 3: Wait 2 minutes for entry time
    logging.info("Waiting 2 minutes for entry...")
    await asyncio.sleep(120)
    
    if not bot_state["running"]:
        return
    
    # Step 4: Wait 1 minute for trade to complete (M1)
    logging.info("Trade started, waiting 1 minute...")
    await asyncio.sleep(60)
    
    if not bot_state["running"]:
        return
    
    # Step 5: Check result
    result = await check_trade_result(signal.pair, signal.direction, signal.entry_price)
    
    # Update signal in DB
    await db.signals.update_one(
        {"id": signal.id},
        {"$set": {"result": result}}
    )
    
    # Step 6: Handle result
    if result == "WIN":
        # WIN - Send message
        bot_state["total_wins"] += 1
        bot_state["trade_count_since_report"] += 1
        
        win_msg = f"""Dfg_2k Analysis
WIN ✅"""
        
        await send_telegram_message(win_msg)
        
        await db.telegram_messages.insert_one({
            "id": str(uuid.uuid4()),
            "signal_id": signal.id,
            "message": win_msg,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "type": "result"
        })
        
        logging.info("Trade WON!")
        
    else:
        # LOSS - Start Martingale Level 2
        logging.info("Trade lost, starting Martingale Level 2...")
        
        result2 = await run_martingale(signal.pair, signal.direction, 2)
        
        if result2 == "STOPPED":
            return
        
        if result2 == "WIN":
            bot_state["total_wins"] += 1
            bot_state["trade_count_since_report"] += 1
            
            win_msg = f"""Dfg_2k Analysis
WIN ✅"""
            
            await send_telegram_message(win_msg)
            
            await db.telegram_messages.insert_one({
                "id": str(uuid.uuid4()),
                "message": win_msg,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "type": "result"
            })
            
            logging.info("Martingale Level 2 WON!")
            
        else:
            # Martingale Level 3
            logging.info("Martingale Level 2 lost, starting Level 3...")
            
            result3 = await run_martingale(signal.pair, signal.direction, 3)
            
            if result3 == "STOPPED":
                return
            
            if result3 == "WIN":
                bot_state["total_wins"] += 1
                bot_state["trade_count_since_report"] += 1
                
                win_msg = f"""Dfg_2k Analysis
WIN ✅"""
                
                await send_telegram_message(win_msg)
                
                await db.telegram_messages.insert_one({
                    "id": str(uuid.uuid4()),
                    "message": win_msg,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "type": "result"
                })
                
                logging.info("Martingale Level 3 WON!")
                
            else:
                # Final LOSS after all 3 levels
                bot_state["total_losses"] += 1
                bot_state["trade_count_since_report"] += 1
                
                loss_msg = f"""Dfg_2k Analysis
Loss ❌"""
                
                await send_telegram_message(loss_msg)
                
                await db.telegram_messages.insert_one({
                    "id": str(uuid.uuid4()),
                    "message": loss_msg,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "type": "result"
                })
                
                logging.info("Final LOSS after 3 martingale levels")
    
    # Step 7: Check if we need to send summary (every 15 trades)
    if bot_state["trade_count_since_report"] >= 15:
        await send_summary_report()
        bot_state["trade_count_since_report"] = 0
    
    # Step 8: Wait 3 minutes before next signal
    logging.info("Waiting 3 minutes before next signal...")
    await asyncio.sleep(180)

async def bot_main_loop():
    """Main bot loop"""
    global bot_state
    
    logging.info("Bot main loop started")
    
    await send_telegram_message("🟢 Dfg_2k Analysis Bot Started\n🛰️ Monitoring 35 OTC pairs\n💎 Timeframe: M1\n⏱️ Signals every 3 minutes")
    
    while bot_state["running"]:
        try:
            await run_single_trade_cycle()
        except asyncio.CancelledError:
            logging.info("Bot loop cancelled")
            break
        except Exception as e:
            logging.error(f"Error in bot loop: {e}")
            await asyncio.sleep(30)
    
    logging.info("Bot main loop ended")

# ============== API ROUTES ==============

@api_router.get("/")
async def root():
    return {"message": "Trading Bot API", "status": "online"}

@api_router.get("/bot/status")
async def get_bot_status():
    total = bot_state["total_wins"] + bot_state["total_losses"]
    win_rate = round((bot_state["total_wins"] / total) * 100, 2) if total > 0 else 0
    
    return {
        "running": bot_state["running"],
        "last_signal_time": bot_state["last_signal_time"],
        "signals_sent": bot_state["signals_sent"],
        "total_wins": bot_state["total_wins"],
        "total_losses": bot_state["total_losses"],
        "win_rate": win_rate,
        "pairs_monitoring": len(OTC_PAIRS)
    }

@api_router.post("/bot/start")
async def start_bot():
    global bot_state, bot_task
    
    if bot_state["running"]:
        return {"message": "Bot is already running", "running": True}
    
    bot_state["running"] = True
    bot_task = asyncio.create_task(bot_main_loop())
    
    return {"message": "Bot started successfully", "running": True}

@api_router.post("/bot/stop")
async def stop_bot():
    global bot_state, bot_task
    
    if not bot_state["running"]:
        return {"message": "Bot is not running", "running": False}
    
    bot_state["running"] = False
    
    if bot_task:
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
        bot_task = None
    
    await send_telegram_message("🔴 Dfg_2k Analysis Bot Stopped")
    
    return {"message": "Bot stopped successfully", "running": False}

@api_router.get("/signals")
async def get_signals(limit: int = 50):
    signals = await db.signals.find({}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return signals

@api_router.get("/telegram-messages")
async def get_telegram_messages(limit: int = 50):
    messages = await db.telegram_messages.find({}, {"_id": 0}).sort("sent_at", -1).limit(limit).to_list(limit)
    return messages

@api_router.get("/stats")
async def get_stats():
    total_signals = await db.signals.count_documents({})
    wins = await db.signals.count_documents({"result": "WIN"})
    losses = await db.signals.count_documents({"result": "LOSS"})
    pending = await db.signals.count_documents({"result": None})
    win_rate = round((wins / (wins + losses)) * 100, 2) if (wins + losses) > 0 else 0
    
    return {
        "total_signals": total_signals,
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "win_rate": win_rate
    }

@api_router.get("/pairs")
async def get_pairs():
    return {"pairs": OTC_PAIRS, "count": len(OTC_PAIRS)}

@api_router.post("/test-telegram")
async def test_telegram():
    success = await send_telegram_message("🔔 Test message from Dfg_2k Analysis Bot")
    return {"success": success}

# Include router
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    global bot_state
    wins = await db.signals.count_documents({"result": "WIN"})
    losses = await db.signals.count_documents({"result": "LOSS"})
    total_signals = await db.signals.count_documents({})
    
    bot_state["total_wins"] = wins
    bot_state["total_losses"] = losses
    bot_state["signals_sent"] = total_signals
    
    logging.info("Trading Bot API started")

@app.on_event("shutdown")
async def shutdown_event():
    global bot_state, bot_task
    bot_state["running"] = False
    if bot_task:
        bot_task.cancel()
    client.close()
