import os
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
)
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

# =========================
# CONFIG RAILWAY
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
MAIN_GROUP_ID = int(os.getenv("MAIN_GROUP_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "/tmp/bot.db")

# =========================
# TEXTES + IMAGES
# =========================

START_PHOTO_URL = "https://ton-site.com/start.jpg"
AD_PHOTO_URL = "https://ton-site.com/pub.jpg"
SHARE_AD_PHOTO_URL = "https://ton-site.com/partage.jpg"

START_TEXT = """Bienvenue 👋

Ce bot permet de demander l’accès au groupe exclusif.

Réponds au formulaire, puis un admin analysera ta demande.
Merci d’envoyer uniquement du contenu autorisé, légal et consenti.
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

# =========================
# STATUTS
# =========================

WAITING = "waiting"
PENDING_MEDIA = "pending_media"
UNDER_REVIEW = "under_review"
APPROVED = "approved"
BANNED = "banned"
REFUSED = "refused"

# =========================
# LOGS
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# =========================
# DATABASE
# =========================

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


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def inc(key: str, n: int = 1):
    with db() as con:
        con.execute("INSERT OR IGNORE INTO stats(key, value) VALUES(?, 0)", (key,))
        con.execute("UPDATE stats SET value = value + ? WHERE key = ?", (n, key))


def set_user(user_id: int, **fields):
    with db() as con:
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
        if fields:
            fields["updated_at"] = now_iso()
            sql = ", ".join([f"{k}=?" for k in fields])
            con.execute(f"UPDATE users SET {sql} WHERE user_id=?", (*fields.values(), user_id))


def get_user(user_id: int):
    with db() as con:
        return con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# =========================
# SECURITE / HELPERS
# =========================

def admin_only(user_id: int) -> bool:
    return is_admin(user_id)


def anti_spam(context: ContextTypes.DEFAULT_TYPE, user_id: int, seconds: int = 2) -> bool:
    if is_admin(user_id):
        return False

    now = datetime.now(timezone.utc).timestamp()
    last_actions = context.application.bot_data.setdefault("last_actions", {})
    last = last_actions.get(user_id, 0)

    if now - last < seconds:
        return True

    last_actions[user_id] = now
    return False


async def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    if "bot_username" not in context.application.bot_data:
        me = await context.bot.get_me()
        context.application.bot_data["bot_username"] = me.username
    return context.application.bot_data["bot_username"]


async def safe_reply_photo(message, photo_url: str, caption: str, reply_markup=None):
    if photo_url and photo_url.startswith("http"):
        try:
            return await message.reply_photo(
                photo=photo_url,
                caption=caption,
                reply_markup=reply_markup,
            )
        except BadRequest:
            logger.warning("Image invalide ou inaccessible : %s", photo_url)

    return await message.reply_text(
        caption + "\n\n⚠️ Image non chargée. Vérifie l’URL dans le code.",
        reply_markup=reply_markup,
    )


async def safe_send_message(context, chat_id: int, text: str, reply_markup=None):
    try:
        return await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
        )
    except Forbidden:
        logger.warning("Impossible d’envoyer un message à %s", chat_id)
    except TelegramError as e:
        logger.warning("Erreur Telegram send_message : %s", e)


def share_button():
    url = "https://t.me/share/url?url=&text=" + quote_plus(SHARE_TEXT)
    return InlineKeyboardButton("🔁 Je partage ce groupe", url=url)


def admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Vérifier configuration", callback_data="admin:check_config")],
        [InlineKeyboardButton("📢 Afficher la pub", callback_data="admin:show_ad")],
        [InlineKeyboardButton("🖼 Publicité", callback_data="admin:share_ad")],
        [InlineKeyboardButton("📊 Statistiques", callback_data="admin:stats")],
        [InlineKeyboardButton("➕ Ajouter mot interdit", callback_data="admin:add_word")],
        [InlineKeyboardButton("📣 Broadcast groupe", callback_data="admin:broadcast")],
    ])


# =========================
# COMMANDES
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    if anti_spam(context, user.id):
        return

    set_user(user.id, username=user.username or "")
    row = get_user(user.id)

    if is_admin(user.id):
        await message.reply_text("Panel admin :", reply_markup=admin_panel())
        return

    if row and row["status"] in (WAITING, UNDER_REVIEW, APPROVED, BANNED):
        if row["status"] == WAITING:
            await message.reply_text(WAITLIST_TEXT)
        elif row["status"] == UNDER_REVIEW:
            await message.reply_text(UNDER_REVIEW_TEXT)
        elif row["status"] == APPROVED:
            await message.reply_text("✅ Vous êtes déjà admis.")
        elif row["status"] == BANNED:
            await message.reply_text(BANNED_TEXT)
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇫🇷 Je suis francophone", callback_data="user:fr")],
        [InlineKeyboardButton("🌍 Je suis international", callback_data="user:intl")],
    ])

    await safe_reply_photo(message, START_PHOTO_URL, START_TEXT, keyboard)


async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not is_admin(user.id):
        await update.message.reply_text("Accès refusé.")
        return

    await update.message.reply_text("Panel admin :", reply_markup=admin_panel())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Action annulée.")


# =========================
# CALLBACKS ADMIN + USER
# =========================

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    data = q.data

    if anti_spam(context, user_id):
        await q.message.reply_text("Patiente quelques secondes avant de recliquer.")
        return

    if data.startswith("admin:"):
        if not admin_only(user_id):
            await q.message.reply_text("Accès refusé.")
            return

        action = data.split(":", 1)[1]

        if action == "check_config":
            lines = ["⚙️ Vérification configuration\n"]

            if BOT_TOKEN:
                lines.append("✅ BOT_TOKEN présent")
            else:
                lines.append("❌ BOT_TOKEN manquant")

            if ADMIN_IDS:
                lines.append(f"✅ Admins configurés : {len(ADMIN_IDS)}")
            else:
                lines.append("❌ ADMIN_IDS manquant")

            if MAIN_GROUP_ID:
                lines.append(f"✅ MAIN_GROUP_ID présent : {MAIN_GROUP_ID}")
            else:
                lines.append("❌ MAIN_GROUP_ID manquant")

            if MAIN_GROUP_ID:
                try:
                    chat = await context.bot.get_chat(MAIN_GROUP_ID)
                    bot_member = await context.bot.get_chat_member(MAIN_GROUP_ID, context.bot.id)

                    lines.append(f"✅ Groupe principal trouvé : {chat.title}")

                    if bot_member.status in ("administrator", "creator"):
                        lines.append("✅ Bot admin dans le groupe principal")
                    else:
                        lines.append("❌ Bot présent mais pas admin dans le groupe principal")

                    rights = getattr(bot_member, "can_delete_messages", False)
                    if rights:
                        lines.append("✅ Droit suppression messages OK")
                    else:
                        lines.append("⚠️ Le bot n’a peut-être pas le droit de supprimer les messages")

                except Exception as e:
                    lines.append("❌ Impossible d’accéder au groupe principal")
                    lines.append(f"Détail : {e}")

            current_chat = q.message.chat
            lines.append("")
            if current_chat.id == MAIN_GROUP_ID:
                lines.append("ℹ️ Vous êtes actuellement dans le groupe principal.")
            elif current_chat.type in ("group", "supergroup"):
                lines.append("✅ Ce chat peut servir de groupe secondaire pour afficher la pub.")
            else:
                lines.append("ℹ️ Vous êtes en privé. Pour publier la pub dans un groupe secondaire, ajoute le bot dans ce groupe et fais /panel dedans.")

            await q.message.reply_text("\n".join(lines))
            return

        if action == "show_ad":
            bot_username = await get_bot_username(context)

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔐 Je rejoins le groupe exclusif",
                    url=f"https://t.me/{bot_username}?start=join"
                )],
                [share_button()],
            ])

            await safe_reply_photo(q.message, AD_PHOTO_URL, AD_TEXT, keyboard)
            inc("ads_shown")
            return

        if action == "share_ad":
            keyboard = InlineKeyboardMarkup([[share_button()]])
            await safe_reply_photo(q.message, SHARE_AD_PHOTO_URL, SHARE_PANEL_TEXT, keyboard)
            inc("share_panels_shown")
            return

        if action == "stats":
            with db() as con:
                users = con.execute("SELECT status, COUNT(*) c FROM users GROUP BY status").fetchall()
                stats = con.execute("SELECT key, value FROM stats").fetchall()
                words = con.execute("SELECT COUNT(*) c FROM forbidden_words").fetchone()["c"]

            lines = ["📊 Statistiques\n"]
            lines.append("Utilisateurs :")
            for r in users:
                lines.append(f"- {r['status']}: {r['c']}")

            lines.append("")
            lines.append("Actions :")
            for s in stats:
                lines.append(f"- {s['key']}: {s['value']}")

            lines.append("")
            lines.append(f"Mots interdits : {words}")

            await q.message.reply_text("\n".join(lines))
            return

        if action == "add_word":
            context.user_data["mode"] = "add_word"
            await q.message.reply_text("Envoie le mot interdit à ajouter. /cancel pour annuler.")
            return

        if action == "broadcast":
            context.user_data["mode"] = "broadcast"
            await q.message.reply_text("Envoie le message à broadcaster dans le groupe principal. /cancel pour annuler.")
            return

    row = get_user(user_id)

    if row and row["status"] in (WAITING, UNDER_REVIEW, BANNED, APPROVED):
        await q.message.reply_text("Votre statut actuel ne permet pas de recommencer.")
        return

    if data == "user:intl":
        set_user(user_id, status=WAITING, lang="international")
        inc("waitlist")
        await q.edit_message_text(WAITLIST_TEXT)
        return

    if data == "user:fr":
        set_user(user_id, lang="fr")
        await q.edit_message_text(
            "Choisissez une option :",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Je possède du contenu exclusif autorisé", callback_data="user:has_content")],
                [InlineKeyboardButton("🤝 Je ne possède pas de contenu exclusif mais je peux contribuer", callback_data="user:no_content")],
            ])
        )
        return

    if data == "user:no_content":
        set_user(user_id, status=WAITING, has_content=0)
        inc("waitlist")
        await q.edit_message_text(WAITLIST_TEXT)
        return

    if data == "user:has_content":
        set_user(user_id, has_content=1)
        await q.edit_message_text(
            "Quel type de contenu possédez-vous ?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Contenu autorisé sur créatrice connue", callback_data="user:type_known")],
                [InlineKeyboardButton("Contenu exclusif AMA autorisé", callback_data="user:type_ama")],
            ])
        )
        return

    if data in ("user:type_known", "user:type_ama"):
        set_user(
            user_id,
            status=PENDING_MEDIA,
            content_type=data.replace("user:type_", "")
        )
        await q.edit_message_text(
            "Envoyez maintenant 1 média autorisé, légal et consenti.\n\n"
            "Il sera transmis à l’admin pour analyse."
        )
        return


# =========================
# CALLBACK REVIEW ADMIN
# =========================

async def review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.message.reply_text("Accès refusé.")
        return

    try:
        _, action, target_id, sub_id = q.data.split(":")
        target_id = int(target_id)
    except ValueError:
        await q.message.reply_text("Action invalide.")
        return

    if action == "ban":
        set_user(target_id, status=BANNED)
        inc("banned")
        await safe_send_message(context, target_id, BANNED_TEXT)
        await q.message.reply_text("Utilisateur banni/refusé définitivement.")
        return

    if action == "refuse":
        context.user_data["mode"] = "refuse_reason"
        context.user_data["refuse_user_id"] = target_id
        await q.message.reply_text("Écris la raison du refus. /cancel pour annuler.")
        return

    if action == "approve":
        if not MAIN_GROUP_ID:
            await q.message.reply_text("MAIN_GROUP_ID manquant.")
            return

        try:
            expire = datetime.now(timezone.utc) + timedelta(minutes=3)

            invite = await context.bot.create_chat_invite_link(
                chat_id=MAIN_GROUP_ID,
                expire_date=expire,
                member_limit=1,
                name=f"access_{target_id}",
            )

            set_user(target_id, status=APPROVED)
            inc("approved")

            await safe_send_message(
                context,
                target_id,
                "✅ Accès validé.\n\n"
                "Ce lien est unique et expire dans 3 minutes :\n"
                f"{invite.invite_link}\n\n"
                f"{GROUP_RULES_TEXT}"
            )

            await q.message.reply_text("Accès accordé et lien envoyé.")
        except TelegramError as e:
            await q.message.reply_text(f"Erreur création lien : {e}")
        return


# =========================
# MEDIA UTILISATEUR
# =========================

async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    if anti_spam(context, user.id):
        return

    row = get_user(user.id)

    if not row or row["status"] != PENDING_MEDIA:
        return

    file_id = None
    media_type = None

    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        media_type = "video"
    elif message.document:
        file_id = message.document.file_id
        media_type = "document"
    else:
        await message.reply_text("Merci d’envoyer une photo, vidéo ou document.")
        return

    with db() as con:
        cur = con.execute(
            "INSERT INTO submissions(user_id, file_id, media_type) VALUES(?,?,?)",
            (user.id, file_id, media_type)
        )
        sub_id = cur.lastrowid

    set_user(user.id, status=UNDER_REVIEW)
    inc("submissions")

    await message.reply_text(UNDER_REVIEW_TEXT)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Bannir l’utilisateur", callback_data=f"review:ban:{user.id}:{sub_id}")],
        [InlineKeyboardButton("❌ Refuser l’accès", callback_data=f"review:refuse:{user.id}:{sub_id}")],
        [InlineKeyboardButton("✅ Donner l’accès", callback_data=f"review:approve:{user.id}:{sub_id}")],
    ])

    caption = (
        "Nouvelle demande\n"
        f"Utilisateur : @{user.username or 'sans_username'}\n"
        f"ID : {user.id}\n"
        f"Type : {row['content_type']}"
    )

    for admin in ADMIN_IDS:
        try:
            if media_type == "photo":
                await context.bot.send_photo(admin, file_id, caption=caption, reply_markup=keyboard)
            elif media_type == "video":
                await context.bot.send_video(admin, file_id, caption=caption, reply_markup=keyboard)
            else:
                await context.bot.send_document(admin, file_id, caption=caption, reply_markup=keyboard)
        except TelegramError as e:
            logger.warning("Impossible d’envoyer le média à l’admin %s : %s", admin, e)


# =========================
# TEXTES ADMIN + MODERATION
# =========================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message
    text = message.text or ""

    if anti_spam(context, user.id):
        return

    if is_admin(user.id) and context.user_data.get("mode") == "add_word":
        word = text.lower().strip()

        if len(word) < 2:
            await message.reply_text("Mot trop court.")
            return

        with db() as con:
            con.execute("INSERT OR IGNORE INTO forbidden_words(word) VALUES(?)", (word,))

        context.user_data.clear()
        await message.reply_text(f"Mot interdit ajouté : {word}")
        return

    if is_admin(user.id) and context.user_data.get("mode") == "broadcast":
        context.user_data.clear()

        if not MAIN_GROUP_ID:
            await message.reply_text("MAIN_GROUP_ID manquant.")
            return

        await safe_send_message(context, MAIN_GROUP_ID, text)
        inc("broadcasts")
        await message.reply_text("Broadcast envoyé.")
        return

    if is_admin(user.id) and context.user_data.get("mode") == "refuse_reason":
        target_id = context.user_data.get("refuse_user_id")
        context.user_data.clear()

        if not target_id:
            await message.reply_text("Utilisateur introuvable.")
            return

        set_user(target_id, status=REFUSED, refusal_reason=text)
        inc("refused")

        await safe_send_message(
            context,
            target_id,
            "Votre accès est refusé pour la raison suivante :\n\n"
            f"{text}\n\n"
            "Vous pouvez recommencer le formulaire avec /start."
        )

        await message.reply_text("Raison envoyée à l’utilisateur.")
        return

    if update.effective_chat and update.effective_chat.id == MAIN_GROUP_ID:
        with db() as con:
            words = [r["word"] for r in con.execute("SELECT word FROM forbidden_words").fetchall()]

        lowered = text.lower()

        if any(w and w in lowered for w in words):
            try:
                await message.delete()

                await update.effective_chat.restrict_member(
                    user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=datetime.now(timezone.utc) + timedelta(minutes=10),
                )

                inc("restricted")

            except TelegramError as e:
                logger.warning("Erreur modération : %s", e)


# =========================
# SUPPRESSION ARRIVEES / SORTIES
# =========================

async def delete_join_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if not msg:
        return

    if update.effective_chat.id != MAIN_GROUP_ID:
        return

    if msg.new_chat_members or msg.left_chat_member:
        try:
            await msg.delete()
            inc("join_leave_deleted")
        except TelegramError as e:
            logger.warning("Impossible de supprimer arrivée/sortie : %s", e)


# =========================
# ERROR HANDLER
# =========================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Erreur non gérée :", exc_info=context.error)


# =========================
# MAIN
# =========================

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN manquant")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("cancel", cancel))

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

    app.add_error_handler(error_handler)

    logger.info("Bot lancé.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
