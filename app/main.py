from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

@app.get("/")
async def root():
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {"healthy": True}

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    print("UPDATE TELEGRAM:", data, flush=True)

    try:
        message = data.get("message")
        if message and "text" in message and API_URL:
            chat_id = message["chat"]["id"]
            text = message["text"]

            if text == "/start":
                r = requests.post(
                    f"{API_URL}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": "Bot démarré ✅"
                    }
                )
                print("SEND:", r.status_code, r.text, flush=True)

    except Exception as e:
        print("ERREUR:", str(e), flush=True)

    return {"ok": True}
