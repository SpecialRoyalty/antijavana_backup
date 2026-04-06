import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Settings, get_settings
from .db import Database

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("telegram-backup-bot")

settings: Settings = get_settings()
db = Database(settings.database_url)
telegram_app: Optional[Application] = None


async def is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id in settings.admin_user_ids)


async def require_admin(update: Update) -> bool:
    if await is_admin(update):
        return True
    if update.effective_message:
        await update.effective_message.reply_text("Commande réservée à l’admin.")
    return False


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Bot backup prêt.\n"
        "Commandes :\n"
        "/status\n"
        "/bindtarget (à lancer dans le nouveau groupe)\n"
        "/publish_last 50\n"
        "/publish_since 2026-04-01\n"
        "/publish_all"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update):
        return
    target = await db.get_setting("target_chat_id")
    total = await db.count_backups()
    await update.effective_message.reply_text(
        f"Source: {settings.source_chat_id}\n"
        f"Backup: {settings.backup_chat_id}\n"
        f"Target actuel: {target or 'non défini'}\n"
        f"Vidéos/documents sauvegardés: {total}"
    )


async def cmd_bindtarget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update):
        return
    chat = update.effective_chat
    if chat is None or chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        await update.effective_message.reply_text("Lance /bindtarget dans le nouveau groupe cible.")
        return
    await db.set_setting("target_chat_id", str(chat.id))
    await update.effective_message.reply_text(f"Groupe cible enregistré: {chat.id}")


async def publish_rows(update: Update, rows: list, label: str) -> None:
    if not await require_admin(update):
        return

    target_chat_id = await db.get_setting("target_chat_id")
    if not target_chat_id:
        await update.effective_message.reply_text(
            "Aucun groupe cible. Ajoute le bot au nouveau groupe puis lance /bindtarget dedans."
        )
        return

    target_chat_id_int = int(target_chat_id)
    bot = update.get_bot()
    sent = 0
    failed = 0

    if not rows:
        await update.effective_message.reply_text(f"Aucun média à republier pour: {label}")
        return

    await update.effective_message.reply_text(
        f"Republish en cours vers {target_chat_id_int} : {len(rows)} élément(s)."
    )

    for row in rows:
        try:
            await bot.copy_message(
                chat_id=target_chat_id_int,
                from_chat_id=row["backup_chat_id"],
                message_id=row["backup_message_id"],
            )
            sent += 1
        except Exception:
            logger.exception("Échec republish backup_message_id=%s", row["backup_message_id"])
            failed += 1

    await update.effective_message.reply_text(
        f"Republish terminé. Envoyés: {sent} | Échecs: {failed}"
    )


async def cmd_publish_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update):
        return
    try:
        limit = int(context.args[0]) if context.args else 50
    except ValueError:
        await update.effective_message.reply_text("Usage: /publish_last 50")
        return
    limit = max(1, min(limit, 500))
    rows = await db.list_backups_desc(limit)
    rows.reverse()
    await publish_rows(update, rows, f"last {limit}")


async def cmd_publish_since(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update):
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /publish_since 2026-04-01")
        return
    start_date = context.args[0]
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        await update.effective_message.reply_text("Format attendu: YYYY-MM-DD")
        return
    rows = await db.list_backups_since(start_date)
    await publish_rows(update, rows, f"since {start_date}")


async def cmd_publish_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update):
        return
    rows = await db.list_all_backups()
    await publish_rows(update, rows, "all")


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return

    if chat.id != settings.source_chat_id:
        return

    media_kind = None
    file_unique_id = None

    if message.video:
        media_kind = "video"
        file_unique_id = message.video.file_unique_id
    elif message.document and (message.document.mime_type or "").startswith("video/"):
        media_kind = "video_document"
        file_unique_id = message.document.file_unique_id
    else:
        return

    try:
        copied = await context.bot.copy_message(
            chat_id=settings.backup_chat_id,
            from_chat_id=chat.id,
            message_id=message.message_id,
        )
    except Exception:
        logger.exception("Impossible de copier le message %s vers le backup", message.message_id)
        return

    await db.add_backup(
        {
            "source_chat_id": chat.id,
            "source_message_id": message.message_id,
            "backup_chat_id": settings.backup_chat_id,
            "backup_message_id": copied.message_id,
            "media_kind": media_kind,
            "media_group_id": message.media_group_id,
            "caption": message.caption,
            "file_unique_id": file_unique_id,
            "sent_by_user_id": message.from_user.id if message.from_user else None,
            "message_date": message.date,
        }
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app

    await db.connect()
    await db.init()

    telegram_app = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .updater(None)
        .build()
    )

    telegram_app.add_handler(CommandHandler("start", cmd_start))
    telegram_app.add_handler(CommandHandler("status", cmd_status))
    telegram_app.add_handler(CommandHandler("bindtarget", cmd_bindtarget))
    telegram_app.add_handler(CommandHandler("publish_last", cmd_publish_last))
    telegram_app.add_handler(CommandHandler("publish_since", cmd_publish_since))
    telegram_app.add_handler(CommandHandler("publish_all", cmd_publish_all))
    telegram_app.add_handler(
        MessageHandler(filters.Chat(settings.source_chat_id) & (filters.VIDEO | filters.Document.VIDEO), handle_media)
    )

    await telegram_app.initialize()
    await telegram_app.start()

    webhook_url = settings.webhook_url
    if not webhook_url:
        railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        if railway_domain:
            webhook_url = f"https://{railway_domain}/telegram/webhook/{settings.webhook_path_secret}"

    if webhook_url:
        await telegram_app.bot.set_webhook(
            url=webhook_url,
            secret_token=settings.telegram_secret_token,
            allowed_updates=["message", "edited_message", "channel_post", "edited_channel_post"],
        )
        logger.info("Webhook configuré: %s", webhook_url)
    else:
        logger.warning("WEBHOOK_URL / RAILWAY_PUBLIC_DOMAIN absent: webhook non configuré automatiquement.")

    try:
        yield
    finally:
        if telegram_app:
            await telegram_app.bot.delete_webhook(drop_pending_updates=False)
            await telegram_app.stop()
            await telegram_app.shutdown()
        await db.close()


app = FastAPI(title="telegram-backup-bot", lifespan=lifespan)


@app.get("/")
async def root() -> dict:
    return {"ok": True, "service": "telegram-backup-bot"}


@app.post("/telegram/webhook/{path_secret}")
async def telegram_webhook(
    path_secret: str,
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    if path_secret != settings.webhook_path_secret:
        raise HTTPException(status_code=404, detail="Not found")

    if settings.telegram_secret_token and x_telegram_bot_api_secret_token != settings.telegram_secret_token:
        raise HTTPException(status_code=401, detail="Invalid Telegram secret token")

    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}
