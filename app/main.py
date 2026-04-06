from fastapi import FastAPI, Request
from .config import BOT_TOKEN, BASE_URL, ADMIN_IDS
from .db import Base, engine, SessionLocal
from .models import Admin, BotConfig, MediaItem, KnownChat
from .handlers import handle_group_message, handle_private_message, handle_callback
from .services import ensure_single_config, ensure_admins_from_env
from .telegram_api import set_webhook, get_me

app = FastAPI(title="Telegram Backup Bot")


Base.metadata.create_all(bind=engine)


@app.on_event("startup")
def startup():
    db = SessionLocal()
    try:
        ensure_single_config(db)
        ensure_admins_from_env(db, ADMIN_IDS)
    finally:
        db.close()


@app.get("/")
async def root():
    return {"status": "ok", "message": "Railway bot is running"}


@app.get("/health")
async def health():
    return {"healthy": True}


@app.get("/set-webhook")
async def setup_webhook():
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN missing"}
    if not BASE_URL:
        return {"ok": False, "error": "BASE_URL missing"}

    webhook_url = f"{BASE_URL}/webhook"
    me = get_me()
    result = set_webhook(webhook_url)
    return {
        "ok": result.get("ok", False),
        "webhook_url": webhook_url,
        "me": me,
        "telegram": result,
    }


@app.get("/debug/config")
async def debug_config():
    db = SessionLocal()
    try:
        config = ensure_single_config(db)
        return {
            "source_chat_id": config.source_chat_id,
            "source_chat_title": config.source_chat_title,
            "backup_chat_id": config.backup_chat_id,
            "backup_chat_title": config.backup_chat_title,
            "restore_chat_id": config.restore_chat_id,
            "restore_chat_title": config.restore_chat_title,
            "last_seen_chat_id": config.last_seen_chat_id,
            "last_seen_chat_title": config.last_seen_chat_title,
            "admin_ids_from_env": sorted(list(ADMIN_IDS)),
        }
    finally:
        db.close()


@app.get("/debug/media")
async def debug_media(limit: int = 50):
    db = SessionLocal()
    try:
        items = db.query(MediaItem).order_by(MediaItem.id.desc()).limit(limit).all()
        return {
            "count": len(items),
            "items": [
                {
                    "id": x.id,
                    "source_chat_id": x.source_chat_id,
                    "source_message_id": x.source_message_id,
                    "media_type": x.media_type,
                    "file_unique_id": x.file_unique_id,
                    "status": x.status,
                    "backup_message_id": x.backup_message_id,
                    "restored_message_id": x.restored_message_id,
                    "created_at": x.created_at.isoformat() if x.created_at else None,
                }
                for x in items
            ],
        }
    finally:
        db.close()


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    db = SessionLocal()
    try:
        if "callback_query" in data:
            result = handle_callback(db, data["callback_query"])
            return {"ok": True, "kind": "callback", "result": result}

        if "message" in data:
            message = data["message"]
            chat_type = message.get("chat", {}).get("type")

            if chat_type in ("group", "supergroup"):
                result = handle_group_message(db, message)
                return {"ok": True, "kind": "group_message", "result": result}

            if chat_type == "private":
                result = handle_private_message(db, message)
                return {"ok": True, "kind": "private_message", "result": result}

        return {"ok": True, "ignored": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()
