import requests
import time
from flask import Flask
import threading

TELEGRAM_TOKEN = "8615131640:AAHGQiYyP5uNqc6zU1QooJShcwlfqcwvur8"
last_id = 0

app = Flask(__name__)

@app.route('/')
def home():
    return "Test Bot OK"

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text})
        print(f"Sent: {r.status_code}")
    except Exception as e:
        print(f"Error: {e}")

def run_bot():
    global last_id
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            r = requests.get(url, params={"offset": last_id + 1, "timeout": 30}).json()
            
            for update in r.get("result", []):
                last_id = update["update_id"]
                chat_id = update["message"]["chat"]["id"]
                text = update["message"]["text"]
                print(f"✅ Got: {text}")
                
                if text == "/start":
                    send_message(chat_id, "✅ Test OK!")
                elif text == "/test":
                    send_message(chat_id, "✅ Working!")
                    
        except Exception as e:
            print(f"❌ Error: {e}")
        time.sleep(1)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)
