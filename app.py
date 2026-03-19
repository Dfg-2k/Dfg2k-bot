import requests
import time
import threading
from flask import Flask
import os

TELEGRAM_TOKEN = "8732682223:AAF-RTy1QuqIpxi-g9fQchnIJMC-vYZbQt4"
last_update_id = 0

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Error: {e}")

def run_bot():
    global last_update_id
    print("Bot is running...")
    
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
                    
                    if "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"]["text"]
                        
                        if text == "/start":
                            send_message(chat_id, "✅ Bot is working!")
                        elif text == "/test":
                            send_message(chat_id, "✅ Test successful!")
            
            time.sleep(1)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
