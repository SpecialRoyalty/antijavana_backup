from datetime import datetime
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from .db import SessionLocal
from .models import Admin, KnownChat, BotConfig, MediaItem, TransferLog


def get_or_create_config(db):
    config = db.query(BotConfig).first()
    if not config:
        config = BotConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def is_admin(user_id: int) -> bool:
    db = SessionLocal()
    try:
        admin = (
            db.query(Admin)
            .filter(Admin.telegram_user_id == user_id, Admin.is_active.is_(True))
            .first()
        )
        return admin is not None
    finally:
        db.close()


def save_known_chat(chat):
    db = SessionLocal()
    try:
        existing = db.query(KnownChat).filter(KnownChat.chat_id == chat.id).first()
        title = chat.title or f"Chat {chat.id}"

        if existing:
            existing.title = title
            existing.chat_type = chat.type
            existing.updated_at = datetime.utcnow()
        else:
            db.add(
                KnownChat(
                    chat_id=chat.id,
                    title=title,
                    chat_type=chat.type,
                )
            )
        db.commit()
    finally:
        db.close()


def admin_main_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Définir groupe source", callback_data="menu:set_source")],
            [InlineKeyboardButton("Définir groupe backup", callback_data="menu:set_backup")],
            [InlineKeyboardButton("Voir les stats", callback_data="menu:stats")],
            [InlineKeyboardButton("Téléverser vers backup", callback_data="menu:upload_backup")],
            [InlineKeyboardButton("Choisir nouveau principal", callback_data="menu:set_restore_target")],
            [InlineKeyboardButton("Restaurer backup → principal", callback_data="menu:restore_to_new_source")],
            [InlineKeyboardButton("Actualiser", callback_data="menu:refresh")],
        ]
    )


async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    text = "Panneau admin du bot"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=admin_main_keyboard())
    else:
        await update.effective_message.reply_text(text, reply_markup=admin_main_keyboard())


async def handle_any_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat:
        return

    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    save_known_chat(chat)

    db = SessionLocal()
    try:
        config = get_or_create_config(db)

        if config.source_chat_id != chat.id:
            return

        media_kind = None
        file_id = None
        file_unique_id = None
        caption = message.caption or ""

        if message.video:
            media_kind = "video"
            file_id = message.video.file_id
            file_unique_id = message.video.file_unique_id
        elif message.document:
            media_kind = "document"
            file_id = message.document.file_id
            file_unique_id = message.document.file_unique_id
        else:
            return

        exists = db.query(MediaItem).filter(MediaItem.telegram_unique_id == file_unique_id).first()
        if exists:
            return

        item = MediaItem(
            source_chat_id=chat.id,
            source_message_id=message.message_id,
            media_kind=media_kind,
            telegram_file_id=file_id,
            telegram_unique_id=file_unique_id,
            caption=caption,
            status="queued",
        )
        db.add(item)
        db.commit()

    except IntegrityError:
        db.rollback()
    finally:
        db.close()


def build_chat_selection_keyboard(prefix: str):
    db = SessionLocal()
    try:
        chats = (
            db.query(KnownChat)
            .filter(KnownChat.chat_type.in_(["group", "supergroup"]))
            .order_by(KnownChat.title.asc())
            .all()
        )

        rows = []
        for c in chats:
            rows.append(
                [InlineKeyboardButton(c.title[:60], callback_data=f"{prefix}:{c.chat_id}")]
            )

        rows.append([InlineKeyboardButton("Retour", callback_data="menu:home")])
        return InlineKeyboardMarkup(rows)
    finally:
        db.close()


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    if not user or not is_admin(user.id):
        await query.edit_message_text("Accès refusé.")
        return

    data = query.data or ""

    if data == "menu:home" or data == "menu:refresh":
        await query.edit_message_text("Panneau admin du bot", reply_markup=admin_main_keyboard())
        return

    if data == "menu:set_source":
        await query.edit_message_text(
            "Choisis le groupe source :",
            reply_markup=build_chat_selection_keyboard("setsource")
        )
        return

    if data == "menu:set_backup":
        await query.edit_message_text(
            "Choisis le groupe backup :",
            reply_markup=build_chat_selection_keyboard("setbackup")
        )
        return

    if data == "menu:set_restore_target":
        await query.edit_message_text(
            "Choisis le nouveau groupe principal :",
            reply_markup=build_chat_selection_keyboard("setrestore")
        )
        return

    if data.startswith("setsource:"):
        chat_id = int(data.split(":")[1])
        db = SessionLocal()
        try:
            config = get_or_create_config(db)
            config.source_chat_id = chat_id
            config.updated_by = user.id
            config.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()

        await query.edit_message_text(
            f"Groupe source défini : `{chat_id}`",
            reply_markup=admin_main_keyboard(),
            parse_mode="Markdown"
        )
        return

    if data.startswith("setbackup:"):
        chat_id = int(data.split(":")[1])
        db = SessionLocal()
        try:
            config = get_or_create_config(db)
            config.backup_chat_id = chat_id
            config.updated_by = user.id
            config.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()

        await query.edit_message_text(
            f"Groupe backup défini : `{chat_id}`",
            reply_markup=admin_main_keyboard(),
            parse_mode="Markdown"
        )
        return

    if data.startswith("setrestore:"):
        chat_id = int(data.split(":")[1])
        db = SessionLocal()
        try:
            config = get_or_create_config(db)
            config.restore_target_chat_id = chat_id
            config.updated_by = user.id
            config.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()

        await query.edit_message_text(
            f"Nouveau principal défini : `{chat_id}`",
            reply_markup=admin_main_keyboard(),
            parse_mode="Markdown"
        )
        return

    if data == "menu:stats":
        db = SessionLocal()
        try:
            config = get_or_create_config(db)
            queued_count = db.query(func.count(MediaItem.id)).filter(MediaItem.status == "queued").scalar() or 0
            uploaded_count = db.query(func.count(MediaItem.id)).filter(MediaItem.status == "uploaded").scalar() or 0
            restored_count = db.query(func.count(MediaItem.id)).filter(MediaItem.restored_at.isnot(None)).scalar() or 0

            text = (
                "Stats du bot\n\n"
                f"Source active : {config.source_chat_id}\n"
                f"Backup actif : {config.backup_chat_id}\n"
                f"Nouveau principal : {config.restore_target_chat_id}\n\n"
                f"Médias en attente : {queued_count}\n"
                f"Médias déjà téléversés : {uploaded_count}\n"
                f"Médias déjà restaurés : {restored_count}"
            )
        finally:
            db.close()

        await query.edit_message_text(text, reply_markup=admin_main_keyboard())
        return

    if data == "menu:upload_backup":
        db = SessionLocal()
        try:
            config = get_or_create_config(db)

            if not config.backup_chat_id:
                await query.edit_message_text(
                    "Aucun groupe backup défini.",
                    reply_markup=admin_main_keyboard()
                )
                return

            items = (
                db.query(MediaItem)
                .filter(MediaItem.status == "queued")
                .order_by(MediaItem.created_at.asc())
                .all()
            )

            total = len(items)
            success = 0

            for item in items:
                try:
                    sent = await context.bot.copy_message(
                        chat_id=config.backup_chat_id,
                        from_chat_id=item.source_chat_id,
                        message_id=item.source_message_id
                    )
                    item.status = "uploaded"
                    item.uploaded_to_chat_id = config.backup_chat_id
                    item.uploaded_message_id = sent.message_id
                    item.uploaded_at = datetime.utcnow()
                    success += 1
                    db.commit()
                except Exception:
                    db.rollback()

            db.add(
                TransferLog(
                    action="upload_to_backup",
                    from_chat_id=config.source_chat_id,
                    to_chat_id=config.backup_chat_id,
                    count_total=total,
                    count_success=success,
                    triggered_by=user.id,
                )
            )
            db.commit()

        finally:
            db.close()

        await query.edit_message_text(
            f"Téléversement terminé.\nSuccès : {success}/{total}",
            reply_markup=admin_main_keyboard()
        )
        return

    if data == "menu:restore_to_new_source":
        db = SessionLocal()
        try:
            config = get_or_create_config(db)

            if not config.backup_chat_id or not config.restore_target_chat_id:
                await query.edit_message_text(
                    "Backup ou nouveau principal non défini.",
                    reply_markup=admin_main_keyboard()
                )
                return

            items = (
                db.query(MediaItem)
                .filter(
                    MediaItem.status == "uploaded",
                    MediaItem.uploaded_to_chat_id == config.backup_chat_id
                )
                .order_by(MediaItem.uploaded_at.asc())
                .all()
            )

            total = len(items)
            success = 0

            for item in items:
                if item.restored_to_chat_id == config.restore_target_chat_id:
                    continue

                try:
                    sent = await context.bot.copy_message(
                        chat_id=config.restore_target_chat_id,
                        from_chat_id=config.backup_chat_id,
                        message_id=item.uploaded_message_id
                    )
                    item.restored_to_chat_id = config.restore_target_chat_id
                    item.restored_message_id = sent.message_id
                    item.restored_at = datetime.utcnow()
                    success += 1
                    db.commit()
                except Exception:
                    db.rollback()

            db.add(
                TransferLog(
                    action="restore_to_source",
                    from_chat_id=config.backup_chat_id,
                    to_chat_id=config.restore_target_chat_id,
                    count_total=total,
                    count_success=success,
                    triggered_by=user.id,
                )
            )
            db.commit()

        finally:
            db.close()

        await query.edit_message_text(
            f"Restauration terminée.\nSuccès : {success}/{total}",
            reply_markup=admin_main_keyboard()
        )
        return
