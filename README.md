# Dfg_2k Analysis Trading Bot

Automated trading signal bot for Pocket Option with Telegram notifications.

## Features

- 📊 Monitors 35 OTC currency pairs
- 📈 Technical analysis using RSI, EMA9, EMA21, Stochastic
- 📱 Sends signals via Telegram every 3 minutes
- 🔄 Martingale system (3 levels)
- 📋 Summary reports every 15 trades
- ✅ Automatic WIN/LOSS detection based on candle colors

## Deployment

### Railway (Recommended for 24/7)

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app)
3. Create new project from GitHub repo
4. Add environment variables:

```
TELEGRAM_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TWELVE_DATA_API_KEY=your_api_key
MONGO_URL=mongodb+srv://...
DB_NAME=trading_bot
```

### Local Development

```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --reload --port 8001
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| TELEGRAM_TOKEN | Bot token from @BotFather |
| TELEGRAM_CHAT_ID | Your Telegram chat ID |
| TWELVE_DATA_API_KEY | API key from twelvedata.com |
| MONGO_URL | MongoDB connection string |
| DB_NAME | Database name |

## API Endpoints

- `GET /api/bot/status` - Get bot status
- `POST /api/bot/start` - Start the bot
- `POST /api/bot/stop` - Stop the bot
- `GET /api/signals` - Get recent signals
- `GET /api/stats` - Get statistics

## Signal Format

```
Dfg_2k Analysis
🛰️ POCKET OPTION

📊 EURUSD-OTC
💎 M1
🕐 14:32:00
🟢 Buy
```

## Result Format

```
Dfg_2k Analysis
WIN ✅
```

or

```
Dfg_2k Analysis
Loss ❌
```

## Martingale

```
Dfg_2k Analysis
🔄 MARTINGALE Level 2
```

## License

Private - All rights reserved
