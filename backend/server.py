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

# 35 OTC Pairs to monitor - using standard forex pairs (same prices)
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
    open_price: float = 0
    close_price: float = 0

# ============== HELPER FUNCTIONS ==============

def get_ny_time() -> datetime:
    utc_now = datetime.now(timezone.utc)
    ny_offset = timedelta(hours=-5)
    return utc_now + ny_offset

def format_time_ny(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S")

async def send_telegram_message(message: str) -> bool:
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

async def get_quote_price(symbol: str) -> Optional[Dict]:
    """Get real-time quote with bid/ask from Twelve Data"""
    if not TWELVE_DATA_API_KEY:
        return None
    
    url = "https://api.twelvedata.com/quote"
    params = {
        "symbol": symbol,
        "apikey": TWELVE_DATA_API_KEY
    }
    
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if "close" in data:
                    return {
                        "price": float(data["close"]),
                        "open": float(data.get("open", data["close"])),
                        "high": float(data.get("high", data["close"])),
                        "low": float(data.get("low", data["close"])),
                        "change": float(data.get("change", 0)),
                        "percent_change": float(data.get("percent_change", 0))
                    }
            return None
    except Exception as e:
        logging.error(f"Error getting quote for {symbol}: {e}")
        return None

async def get_realtime_price(symbol: str) -> Optional[float]:
    """Get real-time price"""
    if not TWELVE_DATA_API_KEY:
        return None
    
    url = "https://api.twelvedata.com/price"
    params = {
        "symbol": symbol,
        "apikey": TWELVE_DATA_API_KEY
    }
    
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if "price" in data:
                    return float(data["price"])
            return None
    except Exception as e:
        logging.error(f"Error getting price for {symbol}: {e}")
        return None

async def get_latest_candle(symbol: str) -> Optional[Dict]:
    """Get the most recent completed 1-minute candle"""
    if not TWELVE_DATA_API_KEY:
        return None
    
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": "1min",
        "outputsize": 2,
        "apikey": TWELVE_DATA_API_KEY
    }
    
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if "values" in data and len(data["values"]) >= 2:
                    # values[0] = current incomplete candle
                    # values[1] = last complete candle
                    candle = data["values"][1]
                    return {
                        "open": float(candle["open"]),
                        "high": float(candle["high"]),
                        "low": float(candle["low"]),
                        "close": float(candle["close"]),
                        "datetime": candle["datetime"]
                    }
            return None
    except Exception as e:
        logging.error(f"Error getting candle for {symbol}: {e}")
        return None

async def fetch_analysis_data(symbol: str) -> Optional[Dict]:
    """Fetch data for analysis"""
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
                data = await fetch_analysis_data(pair)
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
                    "score": max(buy_score, sell_score)
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

async def wait_for_candle_close_and_check(pair: str, direction: str) -> Dict:
    """
    Wait for the current M1 candle to close then check if it was green or red.
    - BUY wins if candle is GREEN (close > open)
    - SELL wins if candle is RED (close < open)
    """
    logging.info(f"Waiting 60 seconds for M1 candle to complete for {pair}...")
    
    # Wait for candle to complete
    await asyncio.sleep(60)
    
    # Get the last completed candle
    candle = await get_latest_candle(pair)
    
    if candle is None:
        logging.error(f"Could not get candle data for {pair}")
        # Fallback to price comparison
        return {"result": "UNKNOWN", "open": 0, "close": 0}
    
    open_price = candle["open"]
    close_price = candle["close"]
    
    logging.info(f"Candle completed - {pair}: Open={open_price}, Close={close_price}")
    
    # Determine result based on candle color
    if direction == "BUY":
        # BUY wins if candle is GREEN (close > open)
        if close_price > open_price:
            result = "WIN"
            logging.info(f"BUY WIN - GREEN candle: {open_price} -> {close_price}")
        elif close_price < open_price:
            result = "LOSS"
            logging.info(f"BUY LOSS - RED candle: {open_price} -> {close_price}")
        else:
            # Doji candle (open == close) - consider as loss to be safe
            result = "LOSS"
            logging.info(f"BUY LOSS - DOJI candle: {open_price} = {close_price}")
    else:  # SELL
        # SELL wins if candle is RED (close < open)
        if close_price < open_price:
            result = "WIN"
            logging.info(f"SELL WIN - RED candle: {open_price} -> {close_price}")
        elif close_price > open_price:
            result = "LOSS"
            logging.info(f"SELL LOSS - GREEN candle: {open_price} -> {close_price}")
        else:
            # Doji candle
            result = "LOSS"
            logging.info(f"SELL LOSS - DOJI candle: {open_price} = {close_price}")
    
    return {
        "result": result,
        "open": open_price,
        "close": close_price
    }

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

async def run_martingale(pair: str, direction: str, level: int) -> Dict:
    """Run martingale - wait for next candle and check color"""
    global bot_state
    
    if not bot_state["running"]:
        return {"result": "STOPPED", "open": 0, "close": 0}
    
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
    
    logging.info(f"Martingale Level {level} - waiting for candle...")
    
    # Wait for candle to complete and check result
    trade_result = await wait_for_candle_close_and_check(pair, direction)
    
    if not bot_state["running"]:
        return {"result": "STOPPED", "open": 0, "close": 0}
    
    # Save to DB
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
        open_price=trade_result["open"],
        close_price=trade_result["close"],
        result=trade_result["result"]
    )
    await db.signals.insert_one(signal.model_dump())
    
    return trade_result

async def run_single_trade_cycle():
    """Run one complete trade cycle"""
    global bot_state
    
    if not bot_state["running"]:
        return
    
    # Step 1: Analyze market
    logging.info("Analyzing market...")
    best = await analyze_all_pairs()
    
    if not best:
        logging.warning("Could not analyze market, retrying in 60s...")
        await asyncio.sleep(60)
        return
    
    entry_time = get_ny_time() + timedelta(minutes=2)
    entry_time_str = format_time_ny(entry_time)
    
    # Step 2: Send signal
    otc_pair = best["pair"].replace("/", "") + "-OTC"
    direction_emoji = "🟢" if best["direction"] == "BUY" else "🔴"
    direction_text = "Buy" if best["direction"] == "BUY" else "Sell"
    
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
        "message": signal_msg,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "type": "signal"
    })
    
    logging.info(f"Signal sent: {otc_pair} {best['direction']}")
    
    # Step 3: Wait 2 minutes for entry time
    logging.info("Waiting 2 minutes for entry time...")
    await asyncio.sleep(120)
    
    if not bot_state["running"]:
        return
    
    # Step 4: Wait for candle to complete and check result
    logging.info("Trade starting - waiting for M1 candle to complete...")
    trade_result = await wait_for_candle_close_and_check(best["pair"], best["direction"])
    
    if not bot_state["running"]:
        return
    
    # Save signal to DB
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
        open_price=trade_result.get("open", 0),
        close_price=trade_result.get("close", 0),
        result=trade_result["result"] if trade_result["result"] != "UNKNOWN" else "LOSS"
    )
    await db.signals.insert_one(signal.model_dump())
    
    # Step 5: Handle result
    if trade_result["result"] == "WIN":
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
        
        logging.info("TRADE WON!")
        
    else:
        # LOSS - Start Martingale Level 2
        logging.info("Trade lost, starting Martingale Level 2...")
        
        result2 = await run_martingale(best["pair"], best["direction"], 2)
        
        if result2["result"] == "STOPPED":
            return
        
        if result2["result"] == "WIN":
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
            
            result3 = await run_martingale(best["pair"], best["direction"], 3)
            
            if result3["result"] == "STOPPED":
                return
            
            if result3["result"] == "WIN":
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
                # Final LOSS
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
    
    # Step 6: Check if we need summary
    if bot_state["trade_count_since_report"] >= 15:
        await send_summary_report()
        bot_state["trade_count_since_report"] = 0
    
    # Step 7: Wait 3 minutes before next signal
    logging.info("Waiting 3 minutes before next signal...")
    await asyncio.sleep(180)

async def bot_main_loop():
    """Main bot loop"""
    global bot_state
    
    logging.info("Bot main loop started")
    
    await send_telegram_message("🟢 Dfg_2k Analysis Bot Started\n🛰️ Monitoring 35 OTC pairs\n💎 Timeframe: M1\n⏱️ Signals every 3 minutes\n📊 Checking candle colors for WIN/LOSS")
    
    while bot_state["running"]:
        try:
            await run_single_trade_cycle()
        except asyncio.CancelledError:
            logging.info("Bot loop cancelled")
            break
        except Exception as e:
            logging.error(f"Error in bot loop: {e}")
            import traceback
            traceback.print_exc()
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

@api_router.get("/test-candle/{pair}")
async def test_candle(pair: str):
    """Test endpoint to check latest candle"""
    candle = await get_latest_candle(pair.replace("-", "/"))
    return {"pair": pair, "candle": candle}

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
