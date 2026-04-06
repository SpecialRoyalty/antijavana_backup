from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

# 🔐 Mets ton token en variable d'environnement sur Railway
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ BOT_TOKEN manquant !", flush=True)

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ✅ Route test (très important)
@app.get("/")
async def root():
    print("GET / appelé", flush=True)
    return {"status": "ok"}


# ✅ Health check (optionnel mais utile)
@app.get("/health")
async def health():
    return {"healthy": True}


# ✅ Webhook Telegram
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    print("UPDATE TELEGRAM:", data, flush=True)

    try:
        message = data.get("message")

        if message and "text" in message:
            chat_id = message["chat"]["id"]
            text = message["text"]

            print(f"Message reçu: {text} de {chat_id}", flush=True)

            if text == "/start":
                response = requests.post(
                    f"{API_URL}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": "Bot démarré ✅"
                    }
                )
                print("Réponse envoyée:", response.status_code, response.text, flush=True)

    except Exception as e:
        print("ERREUR:", str(e), flush=True)

    return {"ok": True}
    
    if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
