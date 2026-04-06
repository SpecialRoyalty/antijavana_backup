import os
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from .db import Base, engine, SessionLocal
from .models import Admin
from .handlers import (
    show_admin_panel,
    handle_callback,
    handle_any_group_message,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ADMIN_IDS = os.getenv("ADMIN_IDS", "")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN manquant")

if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL manquant")

app = FastAPI()
telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()


def seed_admins():
    db = SessionLocal()
    try:
        raw_ids = [x.strip() for x in ADMIN_IDS.split(",") if x.strip()]
        for raw_id in raw_ids:
            tg_id = int(raw_id)
            exists = db.query(Admin).filter(Admin.telegram_user_id == tg_id).first()
            if not exists:
                db.add(Admin(telegram_user_id=tg_id, full_name=f"Admin {tg_id}"))
        db.commit()
    finally:
        db.close()


@app.on_event("startup")
async def on_startup():
    Base.metadata.create_all(bind=engine)
    seed_admins()

    telegram_app.add_handler(CallbackQueryHandler(handle_callback))
    telegram_app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & (filters.VIDEO | filters.Document.ALL),
            handle_any_group_message,
        )
    )
    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"(?i)^panel$"),
            show_admin_panel,
        )
    )

    await telegram_app.initialize()
    await telegram_app.bot.set_webhook(url=f"{WEBHOOK_URL}/telegram/webhook")


@app.on_event("shutdown")
async def on_shutdown():
    await telegram_app.bot.delete_webhook(drop_pending_updates=False)
    await telegram_app.shutdown()


@app.get("/")
async def root():
    return {"ok": True, "service": "telegram-backup-bot"}

from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    print("UPDATE TELEGRAM:", data, flush=True)
    return {"ok": True}
