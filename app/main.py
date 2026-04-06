import os
import requests
from fastapi import FastAPI, Request
from .db import Base, engine, SessionLocal
from .models import Admin
from .admin_panel import admin_main_menu, known_chats_menu
from .services import (
    ensure_single_config,
    ensure_admin,
    is_admin,
    upsert_known_chat,
    set_last_seen_chat,
    create_media_if_not_exists,
    get_stats,
    get_known_group_chats,
    get_chat_by_id,
    set_source_chat,
    set_backup_chat,
    set_restore_chat,
    get_queued_media,
    get_uploaded_media,
    mark_media_uploaded,
    mark_media_restored,
)

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
ADMIN_IDS = os.getenv("ADMIN_IDS", "")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_single_config(db)

        if ADMIN_IDS.strip():
            for raw_id in ADMIN_IDS.split(","):
                raw_id = raw_id.strip()
                if raw_id:
                    try:
                        ensure_admin(db, int(raw_id), None)
                    except ValueError:
                        pass
    finally:
        db.close()


@app.get("/")
async def root():
    return {"status": "ok", "message": "Railway bot is running"}


@app.get("/set-webhook")
async def set_webhook():
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN missing"}

    if not BASE_URL:
        return {"ok": False, "error": "BASE_URL missing"}

    webhook_url = f"{BASE_URL}/webhook"
    r = requests.post(f"{API_URL}/setWebhook", json={"url": webhook_url}, timeout=30)
    return r.json()


def send_message(chat_id: int, text: str, reply_markup: dict | None = None):
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    return requests.post(f"{API_URL}/sendMessage", json=payload, timeout=60)


def edit_message_text(chat_id: int, message_id: int, text: str, reply_markup: dict | None = None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    return requests.post(f"{API_URL}/editMessageText", json=payload, timeout=60)


def answer_callback_query(callback_query_id: str, text: str = ""):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text

    return requests.post(f"{API_URL}/answerCallbackQuery", json=payload, timeout=60)


def copy_message(chat_id: int, from_chat_id: int, message_id: int):
    payload = {
        "chat_id": chat_id,
        "from_chat_id": from_chat_id,
        "message_id": message_id,
    }
    return requests.post(f"{API_URL}/copyMessage", json=payload, timeout=120)


def build_stats_text(stats: dict) -> str:
    source_line = stats["source_chat_title"] or stats["source_chat_id"] or "Non défini"
    backup_line = stats["backup_chat_title"] or stats["backup_chat_id"] or "Non défini"
    restore_line = stats["restore_chat_title"] or stats["restore_chat_id"] or "Non défini"

    return (
        "📊 Statistiques du bot\n\n"
        f"En attente : {stats['queued']}\n"
        f"Déjà envoyés au backup : {stats['uploaded']}\n"
        f"Déjà restaurés : {stats['restored']}\n\n"
        f"Groupe source : {source_line}\n"
        f"Groupe backup : {backup_line}\n"
        f"Nouveau principal : {restore_line}"
    )


def handle_private_message(db, message: dict):
    from_user = message.get("from", {})
    user_id = from_user.get("id")
    username = from_user.get("username")
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if not user_id:
        return

    if text == "/start":
        if is_admin(db, user_id):
            send_message(
                chat_id,
                "👑 Panneau admin",
                reply_markup=admin_main_menu()
            )
        else:
            send_message(chat_id, "✅ Bot démarré, mais tu n'es pas admin.")
        return

    if text == "/admin":
        if is_admin(db, user_id):
            send_message(
                chat_id,
                "👑 Panneau admin",
                reply_markup=admin_main_menu()
            )
        else:
            send_message(chat_id, "❌ Accès refusé.")
        return


def handle_group_message(db, message: dict):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    chat_title = chat.get("title")
    chat_type = chat.get("type")
    message_id = message.get("message_id")

    if not chat_id:
        return

    upsert_known_chat(db, chat_id, chat_title, chat_type)
    set_last_seen_chat(db, chat_id, chat_title)

    # On ne stocke que les groupes source
    stats = get_stats(db)
    source_chat_id = stats.get("source_chat_id")

    if source_chat_id is None or int(source_chat_id) != int(chat_id):
        return

    if "video" in message:
        media = message["video"]
        create_media_if_not_exists(
            db=db,
            source_chat_id=chat_id,
            source_message_id=message_id,
            media_type="video",
            file_id=media["file_id"],
            file_unique_id=media["file_unique_id"],
            caption=message.get("caption"),
        )
        return

    if "document" in message:
        media = message["document"]
        create_media_if_not_exists(
            db=db,
            source_chat_id=chat_id,
            source_message_id=message_id,
            media_type="document",
            file_id=media["file_id"],
            file_unique_id=media["file_unique_id"],
            caption=message.get("caption"),
        )
        return


def do_upload_backup(db, admin_chat_id: int):
    stats = get_stats(db)
    backup_chat_id = stats.get("backup_chat_id")

    if not backup_chat_id:
        send_message(admin_chat_id, "❌ Aucun groupe backup défini.")
        return

    queued_items = get_queued_media(db)
    if not queued_items:
        send_message(admin_chat_id, "ℹ️ Aucun média en attente.")
        return

    sent_count = 0

    for item in queued_items:
        r = copy_message(
            chat_id=int(backup_chat_id),
            from_chat_id=int(item.source_chat_id),
            message_id=int(item.source_message_id),
        )

        try:
            data = r.json()
        except Exception:
            data = {"ok": False}

        if data.get("ok"):
            backup_message_id = data.get("result", {}).get("message_id")
            mark_media_uploaded(db, item, backup_message_id)
            sent_count += 1

    send_message(admin_chat_id, f"✅ Upload terminé. {sent_count} média(s) envoyé(s) au backup.")


def do_restore_backup(db, admin_chat_id: int):
    stats = get_stats(db)
    restore_chat_id = stats.get("restore_chat_id")
    backup_chat_id = stats.get("backup_chat_id")

    if not restore_chat_id:
        send_message(admin_chat_id, "❌ Aucun nouveau groupe principal défini.")
        return

    if not backup_chat_id:
        send_message(admin_chat_id, "❌ Aucun groupe backup défini.")
        return

    uploaded_items = get_uploaded_media(db)
    if not uploaded_items:
        send_message(admin_chat_id, "ℹ️ Aucun média uploaded à restaurer.")
        return

    restored_count = 0

    for item in uploaded_items:
        if not item.backup_message_id:
            continue

        r = copy_message(
            chat_id=int(restore_chat_id),
            from_chat_id=int(backup_chat_id),
            message_id=int(item.backup_message_id),
        )

        try:
            data = r.json()
        except Exception:
            data = {"ok": False}

        if data.get("ok"):
            restored_message_id = data.get("result", {}).get("message_id")
            mark_media_restored(db, item, restored_message_id)
            restored_count += 1

    send_message(admin_chat_id, f"✅ Restauration terminée. {restored_count} média(s) restauré(s).")


def handle_callback(db, callback_query: dict):
    callback_id = callback_query["id"]
    data = callback_query["data"]
    from_user = callback_query.get("from", {})
    user_id = from_user.get("id")
    message = callback_query["message"]
    private_chat_id = message["chat"]["id"]
    message_id = message["message_id"]

    if not user_id or not is_admin(db, user_id):
        answer_callback_query(callback_id, "Accès refusé")
        return

    if data == "admin_menu":
        answer_callback_query(callback_id, "Menu admin")
        edit_message_text(
            private_chat_id,
            message_id,
            "👑 Panneau admin",
            reply_markup=admin_main_menu()
        )
        return

    if data == "pick_source":
        chats = [(c.chat_id, c.title or str(c.chat_id)) for c in get_known_group_chats(db)]
        text, markup = known_chats_menu(chats, "set_source", "Choisis le groupe source :")
        answer_callback_query(callback_id, "Choix du groupe source")
        edit_message_text(private_chat_id, message_id, text, reply_markup=markup)
        return

    if data == "pick_backup":
        chats = [(c.chat_id, c.title or str(c.chat_id)) for c in get_known_group_chats(db)]
        text, markup = known_chats_menu(chats, "set_backup", "Choisis le groupe backup :")
        answer_callback_query(callback_id, "Choix du groupe backup")
        edit_message_text(private_chat_id, message_id, text, reply_markup=markup)
        return

    if data == "pick_restore":
        chats = [(c.chat_id, c.title or str(c.chat_id)) for c in get_known_group_chats(db)]
        text, markup = known_chats_menu(chats, "set_restore", "Choisis le nouveau groupe principal :")
        answer_callback_query(callback_id, "Choix du nouveau principal")
        edit_message_text(private_chat_id, message_id, text, reply_markup=markup)
        return

    if data.startswith("set_source:"):
        target_chat_id = int(data.split(":")[1])
        known = get_chat_by_id(db, target_chat_id)
        if known:
            set_source_chat(db, known.chat_id, known.title or str(known.chat_id))
            answer_callback_query(callback_id, "Groupe source enregistré")
            edit_message_text(
                private_chat_id,
                message_id,
                f"✅ Groupe source défini : {known.title or known.chat_id}",
                reply_markup=admin_main_menu()
            )
        return

    if data.startswith("set_backup:"):
        target_chat_id = int(data.split(":")[1])
        known = get_chat_by_id(db, target_chat_id)
        if known:
            set_backup_chat(db, known.chat_id, known.title or str(known.chat_id))
            answer_callback_query(callback_id, "Groupe backup enregistré")
            edit_message_text(
                private_chat_id,
                message_id,
                f"✅ Groupe backup défini : {known.title or known.chat_id}",
                reply_markup=admin_main_menu()
            )
        return

    if data.startswith("set_restore:"):
        target_chat_id = int(data.split(":")[1])
        known = get_chat_by_id(db, target_chat_id)
        if known:
            set_restore_chat(db, known.chat_id, known.title or str(known.chat_id))
            answer_callback_query(callback_id, "Nouveau principal enregistré")
            edit_message_text(
                private_chat_id,
                message_id,
                f"✅ Nouveau groupe principal défini : {known.title or known.chat_id}",
                reply_markup=admin_main_menu()
            )
        return

    if data == "show_stats":
        stats = get_stats(db)
        answer_callback_query(callback_id, "Statistiques")
        edit_message_text(
            private_chat_id,
            message_id,
            build_stats_text(stats),
            reply_markup=admin_main_menu()
        )
        return

    if data == "upload_backup":
        answer_callback_query(callback_id, "Upload en cours...")
        do_upload_backup(db, private_chat_id)
        return

    if data == "restore_backup":
        answer_callback_query(callback_id, "Restauration en cours...")
        do_restore_backup(db, private_chat_id)
        return


@app.post("/webhook")
async def webhook(request: Request):
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN missing"}

    update = await request.json()

    db = SessionLocal()
    try:
        if "message" in update:
            message = update["message"]
            chat = message.get("chat", {})
            chat_type = chat.get("type")

            if chat_type == "private":
                handle_private_message(db, message)
            elif chat_type in ["group", "supergroup"]:
                handle_group_message(db, message)

        elif "callback_query" in update:
            handle_callback(db, update["callback_query"])

    except Exception as e:
        print("WEBHOOK ERROR:", str(e), flush=True)
    finally:
        db.close()

    return {"ok": True}
