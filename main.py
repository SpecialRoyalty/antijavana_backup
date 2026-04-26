import os
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
MAIN_GROUP_ID = int(os.getenv("MAIN_GROUP_ID", "0"))

DB_PATH = os.getenv("DB_PATH", "/tmp/bot.db")

START_PHOTO_URL = "https://ton-site.com/start.jpg"
AD_PHOTO_URL = "https://ton-site.com/pub.jpg"
SHARE_AD_PHOTO_URL = "https://ton-site.com/partage.jpg"

START_TEXT = """Bienvenue 👋

Ce bot permet de demander l’accès au groupe exclusif.
Réponds au formulaire, puis un admin analysera ta demande.
"""

AD_TEXT = """Rejoins le groupe exclusif 🔐

Clique sur le bouton ci-dessous pour commencer ta demande d’accès.
"""

SHARE_TEXT = "Rejoins ce groupe Telegram exclusif 🔥"

SHARE_PANEL_TEXT = """Aidez-nous à faire grandir le groupe 💪

Partagez ce groupe à vos contacts ou dans vos groupes Telegram.
"""

WAITLIST_TEXT = "Vous êtes sur la liste d’attente."
UNDER_REVIEW_TEXT = "Votre demande est en cours d’analyse."
BANNED_TEXT = "L’accès au groupe ne vous sera pas attribué."

GROUP_RULES_TEXT = """Règles du groupe :
- Participer
- Être de bonne humeur
"""

WAITING = "waiting"
PENDING_MEDIA = "pending_media"
UNDER_REVIEW = "under_review"
APPROVED = "approved"
BANNED = "banned"
REFUSED = "refused"


def db():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            status TEXT DEFAULT 'new',
            lang TEXT,
            has_content INTEGER DEFAULT 0,
            content_type TEXT,
            refusal_reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS forbidden_words (
            word TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_id TEXT,
            media_type TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0
        );
        """)


def inc(key: str, n: int = 1):
    with db() as con:
        con.execute("INSERT OR IGNORE INTO stats(key, value) VALUES(?, 0)", (key,))
        con.execute("UPDATE stats SET value = value + ? WHERE key = ?", (n, key))


def set_user(user_id: int, **fields):
    with db() as con:
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
        if fields:
            fields["updated_at"] = datetime.utcnow().isoformat()
            sql = ", ".join([f"{k}=?" for k in fields])
            con.execute(f"UPDATE users SET {sql} WHERE user_id=?", (*fields.values(), user_id))


def get_user(user_id: int):
    with db() as con:
        return con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Afficher la pub", callback_data="admin:show_ad")],
        [InlineKeyboardButton("🖼 Publicité", callback_data="admin:share_ad")],
        [InlineKeyboardButton("📊 Statistiques", callback_data="admin:stats")],
        [InlineKeyboardButton("➕ Ajouter mot interdit", callback_data="admin:add_word")],
        [InlineKeyboardButton("📣 Broadcast groupe", callback_data="admin:broadcast")],
    ])


def share_button():
    url = "https://t.me/share/url?url=&text=" + quote_plus(SHARE_TEXT)
    return InlineKeyboardButton("🔁 Je partage ce groupe", url=url)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    set_user(user.id, username=user.username or "")
    row = get_user(user.id)

    if is_admin(user.id):
        await update.message.reply_text("Panel admin :", reply_markup=admin_panel())
        return

    if row and row["status"] in (WAITING, UNDER_REVIEW, APPROVED, BANNED):
        if row["status"] == WAITING:
            await update.message.reply_text(WAITLIST_TEXT)
        elif row["status"] == UNDER_REVIEW:
            await update.message.reply_text(UNDER_REVIEW_TEXT)
        elif row["status"] == APPROVED:
            await update.message.reply_text("✅ Vous êtes déjà admis.")
        elif row["status"] == BANNED:
            await update.message.reply_text(BANNED_TEXT)
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇫🇷 Je suis francophone", callback_data="user:fr")],
        [InlineKeyboardButton("🌍 Je suis international", callback_data="user:intl")],
    ])

    if START_PHOTO_URL:
        await update.message.reply_photo(START_PHOTO_URL, caption=START_TEXT, reply_markup=keyboard)
    else:
        await update.message.reply_text(START_TEXT, reply_markup=keyboard)


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    data = q.data

    if data.startswith("admin:"):
        if not is_admin(user_id):
            await q.message.reply_text("Accès refusé.")
            return

        action = data.split(":", 1)[1]

        if action == "show_ad":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔐 Je rejoins le groupe exclusif",
                    url=f"https://t.me/{context.bot.username}?start=join"
                )],
                [share_button()],
            ])

            if AD_PHOTO_URL:
                await q.message.reply_photo(AD_PHOTO_URL, caption=AD_TEXT, reply_markup=keyboard)
            else:
                await q.message.reply_text(AD_TEXT, reply_markup=keyboard)

        elif action == "share_ad":
            keyboard = InlineKeyboardMarkup([[share_button()]])

            if SHARE_AD_PHOTO_URL:
                await q.message.reply_photo(
                    SHARE_AD_PHOTO_URL,
                    caption=SHARE_PANEL_TEXT,
                    reply_markup=keyboard
                )
            else:
                await q.message.reply_text(SHARE_PANEL_TEXT, reply_markup=keyboard)

        elif action == "stats":
            with db() as con:
                rows = con.execute("SELECT status, COUNT(*) c FROM users GROUP BY status").fetchall()
                stats = con.execute("SELECT key, value FROM stats").fetchall()

            lines = ["📊 Statistiques"]
            lines += [f"{r['status']}: {r['c']}" for r in rows]
            lines += [f"{s['key']}: {s['value']}" for s in stats]

            await q.message.reply_text("\n".join(lines))

        elif action == "add_word":
            context.user_data["mode"] = "add_word"
            await q.message.reply_text("Envoie le mot interdit à ajouter.")

        elif action == "broadcast":
            context.user_data["mode"] = "broadcast"
            await q.message.reply_text("Envoie le message à broadcaster dans le groupe principal.")

        return

    row = get_user(user_id)

    if row and row["status"] in (WAITING, UNDER_REVIEW, BANNED, APPROVED):
        await q.message.reply_text("Votre statut actuel ne permet pas de recommencer.")
        return

    if data == "user:intl":
        set_user(user_id, status=WAITING, lang="international")
        inc("waitlist")
        await q.edit_message_text(WAITLIST_TEXT)

    elif data == "user:fr":
        set_user(user_id, lang="fr")
        await q.edit_message_text(
            "Choisissez une option :",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Je possède du contenu exclusif", callback_data="user:has_content")],
                [InlineKeyboardButton("🤝 Je ne possède pas de contenu exclusif mais je peux contribuer", callback_data="user:no_content")],
            ])
        )

    elif data == "user:no_content":
        set_user(user_id, status=WAITING, has_content=0)
        inc("waitlist")
        await q.edit_message_text(WAITLIST_TEXT)

    elif data == "user:has_content":
        set_user(user_id, has_content=1)
        await q.edit_message_text(
            "Quel type de contenu possédez-vous ?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Contenu autorisé sur créatrice connue", callback_data="user:type_known")],
                [InlineKeyboardButton("Contenu exclusif AMA autorisé", callback_data="user:type_ama")],
            ])
        )

    elif data in ("user:type_known", "user:type_ama"):
        set_user(
            user_id,
            status=PENDING_MEDIA,
            content_type=data.replace("user:type_", "")
        )
        await q.edit_message_text(
            "Envoyez maintenant 1 média autorisé. Il sera transmis à l’admin pour analyse."
        )


async def review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.message.reply_text("Accès refusé.")
        return

    _, action, target_id, sub_id = q.data.split(":")
    target_id = int(target_id)

    if action == "ban":
        set_user(target_id, status=BANNED)
        inc("banned")
        await context.bot.send_message(target_id, BANNED_TEXT)
        await q.message.reply_text("Utilisateur banni/refusé définitivement.")

    elif action == "refuse":
        context.user_data["mode"] = "refuse_reason"
        context.user_data["refuse_user_id"] = target_id
        await q.message.reply_text("Écris la raison du refus.")

    elif action == "approve":
        expire = datetime.now(timezone.utc) + timedelta(minutes=3)

        invite = await context.bot.create_chat_invite_link(
            chat_id=MAIN_GROUP_ID,
            expire_date=expire,
            member_limit=1,
            name=f"access_{target_id}",
        )

        set_user(target_id, status=APPROVED)
        inc("approved")

        await context.bot.send_message(
            target_id,
            "✅ Accès validé.\n\n"
            "Ce lien est unique et expire dans 3 minutes :\n"
            f"{invite.invite_link}\n\n"
            f"{GROUP_RULES_TEXT}"
        )

        await q.message.reply_text("Accès accordé et lien envoyé.")


async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    row = get_user(user.id)

    if not row or row["status"] != PENDING_MEDIA:
        return

    file_id = None
    media_type = None

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        media_type = "photo"
    elif update.message.video:
        file_id = update.message.video.file_id
        media_type = "video"
    elif update.message.document:
        file_id = update.message.document.file_id
        media_type = "document"
    else:
        await update.message.reply_text("Merci d’envoyer une photo, vidéo ou document.")
        return

    with db() as con:
        cur = con.execute(
            "INSERT INTO submissions(user_id, file_id, media_type) VALUES(?,?,?)",
            (user.id, file_id, media_type)
        )
        sub_id = cur.lastrowid

    set_user(user.id, status=UNDER_REVIEW)
    inc("submissions")

    await update.message.reply_text(UNDER_REVIEW_TEXT)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Bannir l’utilisateur", callback_data=f"review:ban:{user.id}:{sub_id}")],
        [InlineKeyboardButton("❌ Refuser l’accès", callback_data=f"review:refuse:{user.id}:{sub_id}")],
        [InlineKeyboardButton("✅ Donner l’accès", callback_data=f"review:approve:{user.id}:{sub_id}")],
    ])

    caption = (
        f"Nouvelle demande\n"
        f"Utilisateur : @{user.username or user.id}\n"
        f"ID : {user.id}\n"
        f"Type : {row['content_type']}"
    )

    for admin in ADMIN_IDS:
        if media_type == "photo":
            await context.bot.send_photo(admin, file_id, caption=caption, reply_markup=keyboard)
        elif media_type == "video":
            await context.bot.send_video(admin, file_id, caption=caption, reply_markup=keyboard)
        else:
            await context.bot.send_document(admin, file_id, caption=caption, reply_markup=keyboard)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text or ""

    if is_admin(user_id) and context.user_data.get("mode") == "add_word":
        with db() as con:
            con.execute(
                "INSERT OR IGNORE INTO forbidden_words(word) VALUES(?)",
                (text.lower().strip(),)
            )

        context.user_data.clear()
        await update.message.reply_text("Mot interdit ajouté.")
        return

    if is_admin(user_id) and context.user_data.get("mode") == "broadcast":
        context.user_data.clear()
        await context.bot.send_message(MAIN_GROUP_ID, text)
        await update.message.reply_text("Broadcast envoyé.")
        return

    if is_admin(user_id) and context.user_data.get("mode") == "refuse_reason":
        target_id = context.user_data["refuse_user_id"]

        set_user(target_id, status=REFUSED, refusal_reason=text)
        context.user_data.clear()

        await context.bot.send_message(
            target_id,
            f"Votre accès est refusé pour la raison suivante :\n\n{text}\n\n"
            "Vous pouvez recommencer le formulaire avec /start."
        )

        await update.message.reply_text("Raison envoyée à l’utilisateur.")
        return

    if update.effective_chat and update.effective_chat.id == MAIN_GROUP_ID:
        with db() as con:
            words = [r["word"] for r in con.execute("SELECT word FROM forbidden_words").fetchall()]

        if any(w and w in text.lower() for w in words):
            try:
                await update.message.delete()
                await update.effective_chat.restrict_member(user_id, permissions={})
                inc("restricted")
            except Exception:
                pass


async def delete_join_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if msg and (msg.new_chat_members or msg.left_chat_member):
        try:
            await msg.delete()
        except Exception:
            pass


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN manquant")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(review_callback, pattern=r"^review:"))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
        delete_join_leave
    ))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, media_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    await app.run_polling(drop_pending_updates=True)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN manquant")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(review_callback, pattern=r"^review:"))
    app.add_handler(CallbackQueryHandler(callbacks))

    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
        delete_join_leave
    ))

    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.Document.ALL,
        media_handler
    ))

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        text_handler
    ))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
