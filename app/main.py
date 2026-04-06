from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import requests

app = FastAPI(title="Telegram Railway Bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None


@app.get("/")
async def root():
    return {"status": "ok", "message": "Railway bot is running"}


@app.get("/health")
async def health():
    return {"healthy": True}


@app.get("/set-webhook")
async def set_webhook():
    if not BOT_TOKEN:
        return JSONResponse(status_code=500, content={"ok": False, "error": "BOT_TOKEN missing"})
    if not BASE_URL:
        return JSONResponse(status_code=500, content={"ok": False, "error": "BASE_URL missing"})

    webhook_url = f"{BASE_URL.rstrip('/')}/webhook"
    response = requests.post(f"{TELEGRAM_API}/setWebhook", data={"url": webhook_url}, timeout=20)
    return JSONResponse(status_code=response.status_code, content=response.json())


@app.get("/get-webhook-info")
async def get_webhook_info():
    if not BOT_TOKEN:
        return JSONResponse(status_code=500, content={"ok": False, "error": "BOT_TOKEN missing"})

    response = requests.get(f"{TELEGRAM_API}/getWebhookInfo", timeout=20)
    return JSONResponse(status_code=response.status_code, content=response.json())


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    print("UPDATE TELEGRAM:", data, flush=True)

    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN missing"}

    message = data.get("message") or data.get("edited_message")
    if not message:
        return {"ok": True}

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text", "")

    if not chat_id:
        return {"ok": True}

    reply_text = None
    if text == "/start":
        reply_text = "Bot démarré ✅"
    elif text == "/ping":
        reply_text = "pong 🏓"
    elif text:
        reply_text = f"Tu as écrit : {text}"

    if reply_text:
        try:
            response = requests.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": reply_text},
                timeout=20,
            )
            print("SEND STATUS:", response.status_code, response.text, flush=True)
        except Exception as exc:
            print("SEND ERROR:", str(exc), flush=True)

    return {"ok": True}
