from fastapi import FastAPI, Request
import os
import requests

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN")

@app.get("/")
def home():
    return {"status": "bot running"}

@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    print(data)
    return {"ok": True}
