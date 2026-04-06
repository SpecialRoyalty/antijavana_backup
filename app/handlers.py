from .config import ADMIN_IDS
from .keyboards import admin_keyboard
from .services import (
    upsert_known_chat,
    add_or_ignore_media,
    ensure_single_config,
    ensure_admins_from_env,
    is_admin,
    stats_text,
    set_source_from_last_seen,
    set_backup_from_last_seen,
    set_restore_from_last_seen,
    upload_queued_to_backup,
    restore_uploaded_to_primary,
)
from .telegram_api import send_message, answer_callback_query


def open_admin_panel(db, chat_id: int):
    text = "👑 Panneau admin\n\nChoisis une action :"
    return send_message(chat_id, text, reply_markup=admin_keyboard())


def handle_group_message(db, message: dict):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    chat_title = chat.get("title") or chat.get("username") or "Sans titre"
    chat_type = chat.get("type")

    if chat_id:
        upsert_known_chat(db, chat_id=chat_id, title=chat_title, chat_type=chat_type)

    config = ensure_single_config(db)
    if config.source_chat_id and chat_id != config.source_chat_id:
        return {"ok": True, "action": "ignored_non_source_group"}

    caption = message.get("caption")

    if "video" in message:
        video = message["video"]
        item, created = add_or_ignore_media(
            db=db,
            source_chat_id=chat_id,
            source_message_id=message["message_id"],
            media_type="video",
            file_id=video["file_id"],
            file_unique_id=video["file_unique_id"],
            caption=caption,
            mime_type=video.get("mime_type"),
            file_name=None,
        )
        return {"ok": True, "created": created, "media_id": item.id}

    if "document" in message:
        doc = message["document"]
        item, created = add_or_ignore_media(
            db=db,
            source_chat_id=chat_id,
            source_message_id=message["message_id"],
            media_type="document",
            file_id=doc["file_id"],
            file_unique_id=doc["file_unique_id"],
            caption=caption,
            mime_type=doc.get("mime_type"),
            file_name=doc.get("file_name"),
        )
        return {"ok": True, "created": created, "media_id": item.id}

    return {"ok": True, "action": "ignored_non_media"}


def handle_private_message(db, message: dict):
    user = message.get("from", {})
    user_id = user.get("id")
    text = (message.get("text") or "").strip()

    ensure_admins_from_env(db, ADMIN_IDS)

    if user_id not in ADMIN_IDS and not is_admin(db, user_id):
        return send_message(message["chat"]["id"], "⛔ Accès refusé.")

    if text in ["/start", "start", "menu", "admin", "/admin"]:
        return open_admin_panel(db, message["chat"]["id"])

    return send_message(
        message["chat"]["id"],
        "👑 Bot prêt. Clique ci-dessous pour ouvrir le panneau admin.",
        reply_markup=admin_keyboard(),
    )


def handle_callback(db, callback_query: dict):
    data = callback_query.get("data")
    cb_id = callback_query.get("id")
    message = callback_query.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = callback_query.get("from", {}).get("id")

    ensure_admins_from_env(db, ADMIN_IDS)
    if user_id not in ADMIN_IDS and not is_admin(db, user_id):
        answer_callback_query(cb_id, "Accès refusé")
        return send_message(chat_id, "⛔ Accès refusé.")

    answer_callback_query(cb_id, "OK")

    if data == "panel":
        return open_admin_panel(db, chat_id)

    if data == "stats":
        return send_message(chat_id, stats_text(db), reply_markup=admin_keyboard())

    if data == "set_source":
        ok, msg = set_source_from_last_seen(db)
        return send_message(chat_id, ("✅ " if ok else "❌ ") + msg, reply_markup=admin_keyboard())

    if data == "set_backup":
        ok, msg = set_backup_from_last_seen(db)
        return send_message(chat_id, ("✅ " if ok else "❌ ") + msg, reply_markup=admin_keyboard())

    if data == "set_restore":
        ok, msg = set_restore_from_last_seen(db)
        return send_message(chat_id, ("✅ " if ok else "❌ ") + msg, reply_markup=admin_keyboard())

    if data == "upload_backup":
        ok, msg = upload_queued_to_backup(db)
        return send_message(chat_id, ("✅ " if ok else "❌ ") + msg, reply_markup=admin_keyboard())

    if data == "restore_backup":
        ok, msg = restore_uploaded_to_primary(db)
        return send_message(chat_id, ("✅ " if ok else "❌ ") + msg, reply_markup=admin_keyboard())

    return send_message(chat_id, "Action inconnue.", reply_markup=admin_keyboard())
