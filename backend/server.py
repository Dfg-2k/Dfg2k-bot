from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
import httpx
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
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

# Scheduler for background tasks
scheduler = AsyncIOScheduler()

# Bot state
bot_state = {
    "running": False,
    "last_analysis": None,
    "signals_sent": 0,
    "total_wins": 0,
    "total_losses": 0
}

# 35 OTC Pairs to monitor (unique pairs)
OTC_PAIRS = [
    "NZD/JPY", "EUR/CHF", "EUR/USD", "AUD/USD", "GBP/USD", "USD/JPY", "AUD/NZD",
    "USD/CAD", "GBP/JPY", "AUD/CHF", "CAD/JPY", "NZD/USD", "GBP/NZD", "AUD/JPY",
    "CAD/CHF", "EUR/CAD", "EUR/AUD", "NZD/CHF", "USD/CHF", "EUR/GBP", "EUR/JPY",
    "GBP/CHF", "GBP/CAD", "CHF/JPY", "USD/MXN", "USD/ZAR", "USD/TRY", "USD/SGD",
    "USD/HKD", "USD/DKK", "USD/NOK", "USD/SEK", "EUR/SEK", "EUR/NOK", "GBP/DKK"
]

# Models
class BotConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rsi_oversold: int = 30
    rsi_overbought: int = 70
    stochastic_oversold: int = 20
    stochastic_overbought: int = 80
    min_confidence: int = 65
    analysis_interval_minutes: int = 3
    signal_advance_minutes: int = 2
    martingale_levels: int = 3

class Signal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pair: str
    direction: str  # "BUY" or "SELL"
    entry_time: str
    confidence: float
    rsi: float
    ema9: float
    ema21: float
    stochastic: float
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: Optional[str] = None  # "WIN", "LOSS", or None (pending)
    martingale_level: int = 0
    telegram_sent: bool = False

class TradeResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    signal_id: str
    result: str
    martingale_level: int
    timestamp: str

class BotStats(BaseModel):
    total_signals: int = 0
    total_wins: int = 0
    total_losses: int = 0
    win_rate: float = 0.0
    running: bool = False
    last_analysis: Optional[str] = None

class ConfigUpdate(BaseModel):
    rsi_oversold: Optional[int] = None
    rsi_overbought: Optional[int] = None
    stochastic_oversold: Optional[int] = None
    stochastic_overbought: Optional[int] = None
    min_confidence: Optional[int] = None

# Store current config
current_config = BotConfig()

# Helper Functions
def get_ny_time() -> datetime:
    """Get current time in New York timezone (UTC-5)"""
    utc_now = datetime.now(timezone.utc)
    ny_offset = timedelta(hours=-5)
    return utc_now + ny_offset

def format_time_ny(dt: datetime) -> str:
    """Format datetime to HH:MM:SS in NY timezone"""
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
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                logging.info("Telegram message sent successfully")
                return True
            else:
                logging.error(f"Telegram error: {response.text}")
                return False
    except Exception as e:
        logging.error(f"Error sending Telegram message: {e}")
        return False

async def fetch_market_data(symbol: str) -> Optional[Dict]:
    """Fetch market data from Twelve Data API"""
    if not TWELVE_DATA_API_KEY:
        return None
    
    # Convert pair format for API (e.g., "EUR/USD" -> "EUR/USD")
    url = f"https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": "1min",
        "outputsize": 50,
        "apikey": TWELVE_DATA_API_KEY
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if "values" in data:
                    return data
            return None
    except Exception as e:
        logging.error(f"Error fetching market data for {symbol}: {e}")
        return None

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """Calculate RSI"""
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
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

def calculate_ema(prices: List[float], period: int) -> float:
    """Calculate EMA"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    
    multiplier = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))
    return round(ema, 6)

def calculate_stochastic(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Calculate Stochastic Oscillator %K"""
    if len(closes) < period:
        return 50.0
    
    highest_high = max(highs[-period:])
    lowest_low = min(lows[-period:])
    current_close = closes[-1]
    
    if highest_high == lowest_low:
        return 50.0
    
    stochastic = ((current_close - lowest_low) / (highest_high - lowest_low)) * 100
    return round(stochastic, 2)

def calculate_confidence(rsi: float, ema9: float, ema21: float, stochastic: float, direction: str) -> float:
    """Calculate signal confidence percentage"""
    confidence = 0
    
    if direction == "BUY":
        # RSI contribution (0-30)
        if rsi < 30:
            confidence += 30 * (1 - rsi/30)
        # EMA contribution (0-35)
        if ema9 > ema21:
            ema_diff_pct = min((ema9 - ema21) / ema21 * 100, 1) if ema21 != 0 else 0
            confidence += 35 * ema_diff_pct
        # Stochastic contribution (0-35)
        if stochastic < 20:
            confidence += 35 * (1 - stochastic/20)
    else:  # SELL
        # RSI contribution (0-30)
        if rsi > 70:
            confidence += 30 * ((rsi - 70) / 30)
        # EMA contribution (0-35)
        if ema9 < ema21:
            ema_diff_pct = min((ema21 - ema9) / ema9 * 100, 1) if ema9 != 0 else 0
            confidence += 35 * ema_diff_pct
        # Stochastic contribution (0-35)
        if stochastic > 80:
            confidence += 35 * ((stochastic - 80) / 20)
    
    return min(round(confidence + 50, 2), 100)

async def analyze_pair(pair: str) -> Optional[Signal]:
    """Analyze a single currency pair"""
    data = await fetch_market_data(pair)
    if not data or "values" not in data:
        return None
    
    values = data["values"]
    if len(values) < 21:
        return None
    
    # Extract OHLC data
    closes = [float(v["close"]) for v in reversed(values)]
    highs = [float(v["high"]) for v in reversed(values)]
    lows = [float(v["low"]) for v in reversed(values)]
    
    # Calculate indicators
    rsi = calculate_rsi(closes)
    ema9 = calculate_ema(closes, 9)
    ema21 = calculate_ema(closes, 21)
    stochastic = calculate_stochastic(highs, lows, closes)
    
    # Check for BUY signal
    if rsi < current_config.rsi_oversold and ema9 > ema21 and stochastic < current_config.stochastic_oversold:
        direction = "BUY"
        confidence = calculate_confidence(rsi, ema9, ema21, stochastic, direction)
        if confidence >= current_config.min_confidence:
            entry_time = get_ny_time() + timedelta(minutes=current_config.signal_advance_minutes)
            return Signal(
                pair=pair,
                direction=direction,
                entry_time=format_time_ny(entry_time),
                confidence=confidence,
                rsi=rsi,
                ema9=ema9,
                ema21=ema21,
                stochastic=stochastic
            )
    
    # Check for SELL signal
    if rsi > current_config.rsi_overbought and ema9 < ema21 and stochastic > current_config.stochastic_overbought:
        direction = "SELL"
        confidence = calculate_confidence(rsi, ema9, ema21, stochastic, direction)
        if confidence >= current_config.min_confidence:
            entry_time = get_ny_time() + timedelta(minutes=current_config.signal_advance_minutes)
            return Signal(
                pair=pair,
                direction=direction,
                entry_time=format_time_ny(entry_time),
                confidence=confidence,
                rsi=rsi,
                ema9=ema9,
                ema21=ema21,
                stochastic=stochastic
            )
    
    return None

async def run_analysis():
    """Run analysis on all pairs"""
    global bot_state
    
    if not bot_state["running"]:
        return
    
    logging.info("Running market analysis...")
    bot_state["last_analysis"] = datetime.now(timezone.utc).isoformat()
    
    signals_found = []
    
    # Analyze pairs in batches to respect API rate limits
    batch_size = 8
    for i in range(0, len(OTC_PAIRS), batch_size):
        batch = OTC_PAIRS[i:i+batch_size]
        tasks = [analyze_pair(pair) for pair in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Signal):
                signals_found.append(result)
        
        # Wait to respect rate limits
        if i + batch_size < len(OTC_PAIRS):
            await asyncio.sleep(1)
    
    # Process found signals
    for signal in signals_found:
        # Save to database
        signal_dict = signal.model_dump()
        await db.signals.insert_one(signal_dict)
        
        # Send Telegram message
        otc_pair = signal.pair.replace("/", "") + "-OTC"
        direction_emoji = "🟢" if signal.direction == "BUY" else "🔴"
        direction_text = "Buy" if signal.direction == "BUY" else "Sell"
        
        message = f"""Dfg_2k Analysis
🛰️ POCKET OPTION

📊 {otc_pair}
💎 M1
🕐 {signal.entry_time}
{direction_emoji} {direction_text}"""
        
        sent = await send_telegram_message(message)
        if sent:
            await db.signals.update_one(
                {"id": signal.id},
                {"$set": {"telegram_sent": True}}
            )
            bot_state["signals_sent"] += 1
        
        # Log to telegram_messages collection
        await db.telegram_messages.insert_one({
            "id": str(uuid.uuid4()),
            "signal_id": signal.id,
            "message": message,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "success": sent
        })
    
    logging.info(f"Analysis complete. Found {len(signals_found)} signals.")

async def simulate_trade_results():
    """Simulate trade results for pending signals (for demo purposes)"""
    # Find pending signals older than 5 minutes
    five_mins_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    pending = await db.signals.find({
        "result": None,
        "created_at": {"$lt": five_mins_ago}
    }, {"_id": 0}).to_list(100)
    
    for signal in pending:
        # Simulate result with ~80% win rate
        import random
        martingale = signal.get("martingale_level", 0)
        
        # Higher confidence = higher win probability
        confidence = signal.get("confidence", 65)
        win_prob = min(0.6 + (confidence - 65) * 0.01, 0.9)
        
        if random.random() < win_prob:
            # WIN
            result = "WIN"
            bot_state["total_wins"] += 1
            result_msg = f"WIN ✅{'¹' if martingale == 1 else '²' if martingale == 2 else ''}" if martingale > 0 else "WIN ✅"
        else:
            if martingale < current_config.martingale_levels - 1:
                # Continue to next martingale level
                new_signal = signal.copy()
                new_signal["id"] = str(uuid.uuid4())
                new_signal["martingale_level"] = martingale + 1
                new_signal["result"] = None
                new_signal["created_at"] = datetime.now(timezone.utc).isoformat()
                await db.signals.insert_one(new_signal)
                result = "PENDING"
                result_msg = None
            else:
                # Final loss after 3 martingale levels
                result = "LOSS"
                bot_state["total_losses"] += 1
                result_msg = "Loss ❌"
        
        if result != "PENDING":
            await db.signals.update_one(
                {"id": signal["id"]},
                {"$set": {"result": result}}
            )
            
            if result_msg:
                await send_telegram_message(f"Dfg_2k Analysis\n{result_msg}")

async def send_summary_report():
    """Send summary report every 15 trades"""
    global bot_state
    
    total = bot_state["total_wins"] + bot_state["total_losses"]
    if total > 0 and total % 15 == 0:
        win_rate = round((bot_state["total_wins"] / total) * 100) if total > 0 else 0
        ny_time = get_ny_time()
        
        # Get recent signals
        recent = await db.signals.find(
            {"result": {"$ne": None}},
            {"_id": 0}
        ).sort("created_at", -1).limit(15).to_list(15)
        
        results_lines = []
        for s in reversed(recent):
            otc_pair = s["pair"].replace("/", "") + "-OTC"
            result_text = "WIN" if s["result"] == "WIN" else "LOSS ✖"
            results_lines.append(f"{otc_pair} {s['entry_time']} {result_text}")
        
        message = f"""Dfg_2k Analysis
📋 Last Hour Results ({format_time_ny(ny_time)} UTC-5)

{chr(10).join(results_lines)}

---

✅ Wins: {bot_state['total_wins']} | ❌ Losses: {bot_state['total_losses']}
🏆 Win Rate: {win_rate}%

Channel Overall Win Rate: {win_rate}% ({bot_state['total_wins']}W/{bot_state['total_losses']}L)"""
        
        await send_telegram_message(message)

# API Routes
@api_router.get("/")
async def root():
    return {"message": "Trading Bot API", "status": "online"}

@api_router.get("/bot/status")
async def get_bot_status():
    total = bot_state["total_wins"] + bot_state["total_losses"]
    win_rate = round((bot_state["total_wins"] / total) * 100, 2) if total > 0 else 0
    
    return {
        "running": bot_state["running"],
        "last_analysis": bot_state["last_analysis"],
        "signals_sent": bot_state["signals_sent"],
        "total_wins": bot_state["total_wins"],
        "total_losses": bot_state["total_losses"],
        "win_rate": win_rate,
        "pairs_monitoring": len(OTC_PAIRS)
    }

@api_router.post("/bot/start")
async def start_bot():
    global bot_state
    
    if bot_state["running"]:
        return {"message": "Bot is already running", "running": True}
    
    bot_state["running"] = True
    
    # Schedule analysis every 3 minutes
    scheduler.add_job(
        run_analysis,
        IntervalTrigger(minutes=current_config.analysis_interval_minutes),
        id="market_analysis",
        replace_existing=True
    )
    
    # Schedule result simulation every 5 minutes
    scheduler.add_job(
        simulate_trade_results,
        IntervalTrigger(minutes=5),
        id="trade_results",
        replace_existing=True
    )
    
    if not scheduler.running:
        scheduler.start()
    
    # Run initial analysis
    asyncio.create_task(run_analysis())
    
    await send_telegram_message("🟢 Dfg_2k Analysis Bot Started\n🛰️ Monitoring 35 OTC pairs\n💎 Timeframe: M1")
    
    return {"message": "Bot started successfully", "running": True}

@api_router.post("/bot/stop")
async def stop_bot():
    global bot_state
    
    if not bot_state["running"]:
        return {"message": "Bot is not running", "running": False}
    
    bot_state["running"] = False
    
    try:
        scheduler.remove_job("market_analysis")
        scheduler.remove_job("trade_results")
    except:
        pass
    
    await send_telegram_message("🔴 Dfg_2k Analysis Bot Stopped")
    
    return {"message": "Bot stopped successfully", "running": False}

@api_router.get("/bot/config")
async def get_config():
    return current_config.model_dump()

@api_router.put("/bot/config")
async def update_config(config: ConfigUpdate):
    global current_config
    
    update_data = config.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(current_config, key, value)
    
    return current_config.model_dump()

@api_router.get("/signals")
async def get_signals(limit: int = 50):
    signals = await db.signals.find({}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return signals

@api_router.get("/signals/pending")
async def get_pending_signals():
    signals = await db.signals.find({"result": None}, {"_id": 0}).sort("created_at", -1).to_list(100)
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
    
    # Get signal distribution by pair
    pipeline = [
        {"$group": {"_id": "$pair", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    pair_stats = await db.signals.aggregate(pipeline).to_list(10)
    
    return {
        "total_signals": total_signals,
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "win_rate": win_rate,
        "pair_distribution": pair_stats
    }

@api_router.get("/pairs")
async def get_pairs():
    return {"pairs": OTC_PAIRS, "count": len(OTC_PAIRS)}

@api_router.post("/test-telegram")
async def test_telegram():
    """Send a test message to Telegram"""
    success = await send_telegram_message("🔔 Test message from Dfg_2k Analysis Bot")
    return {"success": success, "message": "Test message sent" if success else "Failed to send message"}

@api_router.post("/analyze-now")
async def analyze_now():
    """Trigger immediate analysis"""
    if not bot_state["running"]:
        return {"error": "Bot is not running. Start the bot first."}
    
    asyncio.create_task(run_analysis())
    return {"message": "Analysis triggered"}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    # Load stats from database
    global bot_state
    wins = await db.signals.count_documents({"result": "WIN"})
    losses = await db.signals.count_documents({"result": "LOSS"})
    total_signals = await db.signals.count_documents({})
    
    bot_state["total_wins"] = wins
    bot_state["total_losses"] = losses
    bot_state["signals_sent"] = total_signals
    
    logging.info("Trading Bot API started")

@app.on_event("shutdown")
async def shutdown_db_client():
    if scheduler.running:
        scheduler.shutdown()
    client.close()
