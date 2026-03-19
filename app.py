# Ajoute sa nan konmansman an, apre import yo
print("=" * 50)
print("🤖 BOT LA AP DEMARE...")
print(f"📱 Telegram Token: {TELEGRAM_TOKEN[:10]}...")
print("=" * 50)

# Teste yon mesaj bay tèt ou (ranplase ak ID ou)
def send_test_message():
    try:
        my_chat_id = 123456789  # Mete ID Telegram ou a
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": my_chat_id, "text": "✅ Bot ap mache!"}
        r = requests.post(url, json=data, timeout=10)
        if r.status_code == 200:
            print("✅ Mesaj tès voye!")
        else:
            print(f"❌ Erè: {r.text}")
    except Exception as e:
        print(f"❌ Erè: {e}")

# Rele li apre koneksyon an
send_test_message()
