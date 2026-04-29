import os
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
MAIN_GROUP_ID = int(os.getenv("MAIN_GROUP_ID", "0"))
SECONDARY_GROUP_ID = int(os.getenv("SECONDARY_GROUP_ID", "0"))

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

USER_REPLY_DELAY = 1

BROADCAST_USER_DELAY = float(os.getenv("BROADCAST_USER_DELAY", "0.15"))
BROADCAST_RETRY_DELAY = int(os.getenv("BROADCAST_RETRY_DELAY", "3"))
BROADCAST_MAX_RETRIES = int(os.getenv("BROADCAST_MAX_RETRIES", "2"))

START_PHOTO_URL = "https://files.catbox.moe/j24fx2.jpg"
AD_PHOTO_URL = "https://files.catbox.moe/pkztzh.jpg"
SHARE_AD_PHOTO_URL = "https://files.catbox.moe/7sw1q5.jpg"

START_TEXT = """
🚪 Accès à un cercle privé

Tu es sur le point de rejoindre un groupe sélectif et confidentiel.

Ici, on ne cherche pas du contenu banal.  
On veut de la qualité, de la rareté, et de l’engagement réel :

✨ Contenu exclusif
🔥 Participation active et sérieuse
🚫 Zéro recyclage, zéro déjà-vu

⚠️ Attention : les places sont très limitées.  
Chaque candidature est examinée avec soin avant validation.

👉 À toi de jouer. Choisis ton profil :
"""

AD_TEXT = """🔐 Rejoins un groupe vraiment exclusif

Marre de ceux qui demandent sans poster ?
Marre de voir toujours les mêmes contenus ?

👉 Ici, seuls les vrais apportent de la valeur.

Accès réservé à ceux qui ont de vraies exclusivités ou qui investissent régulièrement dans du contenu privé.

✔ Échange 100% exclusif
✔ Aucun média qui a déjà tourné
✔ Communauté active et qualitative

⚠️ 200 places maximum

👇 Rejoins-nous maintenant"""

SHARE_TEXT = """🔐 Accès au groupe exclusif

👉 Clique ici pour obtenir ton accès :
https://t.me/ExcluGroup_bot?start=join

⚠️ Accès limité — validation requise"""

SHARE_PANEL_TEXT = """🚀 Fais grandir une communauté

Plus le groupe grandit, plus les exclusivités deviennent rares et intéressantes.

💎 Invite uniquement des personnes fiables et actives
🤝 Plus de membres qualifiés = plus de contenu premium pour tous
💰 Possibilité de se regrouper à plusieurs pour acheter du contenu privé

Partage le groupe à tes contacts ou dans tes meilleurs groupes Telegram.

👇 À toi de jouer"""

GROUPS_FULL_TEXT = "Tous les groupes sont actuellement pleins."

CREATORS_ONLY_TEXT = """Pour ce groupe nous acceptons uniquement les personnes avec du contenu de créatrices.

Mais rien n’est fini.

Êtes-vous dans des groupes VIP Telegram payants ?
Si oui, contactez @op75x15"""

WAITLIST_TEXT = "Vous êtes sur la liste d’attente."
UNDER_REVIEW_TEXT = "Votre demande est en cours d’analyse."
BANNED_TEXT = "L’accès au groupe ne vous sera pas attribué."

GROUP_RULES_TEXT = """Règles du groupe :
- Envoyer directement son contenu avant de faire des demandes
- Accompagner les nouveaux
- Ne pas faire fuiter le contenu du groupe ni ruiner le travail et l’apport de chacun
- Proposer des créateurs/créatrices de contenu pour acheter des médias en groupe via une cotisation ou un pot commun
"""

WAITING = "waiting"
SOFT_REJECT = "soft_reject"
PENDING_MEDIA = "pending_media"
UNDER_REVIEW = "under_review"
APPROVED = "approved"
BANNED = "banned"
REFUSED = "refused"

SETTING_GROUPS_FULL = "groups_full"
SETTING_CREATORS_ONLY = "creators_only"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL manquant.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    logger.info("Initialisation PostgreSQL")

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                status TEXT DEFAULT 'new',
                lang TEXT,
                has_content INTEGER DEFAULT 0,
                content_type TEXT,
                refusal_reason TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_submissions (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT,
                file_id TEXT,
                media_type TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_stats (
                key TEXT PRIMARY KEY,
                value INTEGER DEFAULT 0
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT 'off',
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS forbidden_words (
                id SERIAL PRIMARY KEY,
                group_id BIGINT NOT NULL,
                word VARCHAR(255) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
            """)

            cur.execute("""
            INSERT INTO bot_settings(key, value)
            VALUES(%s, 'off')
            ON CONFLICT (key) DO NOTHING
            """, (SETTING_GROUPS_FULL,))

            cur.execute("""
            INSERT INTO bot_settings(key, value)
            VALUES(%s, 'off')
            ON CONFLICT (key) DO NOTHING
            """, (SETTING_CREATORS_ONLY,))

            con.commit()


def get_setting(key: str) -> str:
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT value FROM bot_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            return row["value"] if row else "off"


def is_setting_on(key: str) -> bool:
    return get_setting(key) == "on"


def toggle_setting(key: str) -> str:
    current = get_setting(key)
    new_value = "off" if current == "on" else "on"

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
            INSERT INTO bot_settings(key, value, updated_at)
            VALUES(%s, %s, NOW())
            ON CONFLICT (key)
            DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """, (key, new_value))
            con.commit()

    return new_value


def inc(key: str, n: int = 1):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                INSERT INTO bot_stats(key, value)
                VALUES(%s, 0)
                ON CONFLICT (key) DO NOTHING
            """, (key,))

            cur.execute("""
                UPDATE bot_stats
                SET value = value + %s
                WHERE key = %s
            """, (n, key))

            con.commit()


def set_user(user_id: int, **fields):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                INSERT INTO bot_users(user_id)
                VALUES(%s)
                ON CONFLICT (user_id) DO NOTHING
            """, (user_id,))

            if fields:
                fields["updated_at"] = now_iso()
                columns = ", ".join([f"{k} = %s" for k in fields])
                values = list(fields.values()) + [user_id]
                cur.execute(f"UPDATE bot_users SET {columns} WHERE user_id = %s", values)

            con.commit()


def get_user(user_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT * FROM bot_users WHERE user_id = %s", (user_id,))
            return cur.fetchone()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


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


async def delayed_user_reply():
    await asyncio.sleep(USER_REPLY_DELAY)


async def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    if "bot_username" not in context.application.bot_data:
        me = await context.bot.get_me()
        context.application.bot_data["bot_username"] = me.username
    return context.application.bot_data["bot_username"]


async def safe_reply_photo(message, photo_url: str, caption: str, reply_markup=None):
    if photo_url and photo_url.startswith("http"):
        try:
            return await message.reply_photo(photo=photo_url, caption=caption, reply_markup=reply_markup)
        except BadRequest:
            logger.warning("Image invalide : %s", photo_url)

    return await message.reply_text(
        caption + "\n\n⚠️ Image non chargée. Vérifie l’URL dans le code.",
        reply_markup=reply_markup,
    )


async def safe_send_photo_or_text(context, chat_id: int, photo_url: str, caption: str, reply_markup=None):
    if photo_url and photo_url.startswith("http"):
        try:
            return await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo_url,
                caption=caption,
                reply_markup=reply_markup,
            )
        except BadRequest:
            logger.warning("Image invalide : %s", photo_url)

    return await context.bot.send_message(
        chat_id=chat_id,
        text=caption + "\n\n⚠️ Image non chargée. Vérifie l’URL dans le code.",
        reply_markup=reply_markup,
    )


async def safe_send_message(context, chat_id: int, text: str, reply_markup=None):
    try:
        return await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    except Forbidden:
        logger.warning("Impossible d’envoyer un message à %s", chat_id)
    except TelegramError as e:
        logger.warning("Erreur Telegram : %s", e)


async def safe_callback_text(q, text: str, reply_markup=None):
    try:
        await q.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest:
        await q.message.reply_text(text=text, reply_markup=reply_markup)


def on_off_label(value: str) -> str:
    return "ON ✅" if value == "on" else "OFF ❌"


def share_button():
    url = "https://t.me/share/url?url=&text=" + quote_plus(SHARE_TEXT)
    return InlineKeyboardButton("🔁 Je partage ce groupe", url=url)


def admin_panel():
    groups_full = get_setting(SETTING_GROUPS_FULL)
    creators_only = get_setting(SETTING_CREATORS_ONLY)

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Vérifier configuration", callback_data="admin:check_config")],
        [InlineKeyboardButton(f"🚪 Groupes pleins : {on_off_label(groups_full)}", callback_data="admin:toggle_groups_full")],
        [InlineKeyboardButton(f"🎥 Créatrices uniquement : {on_off_label(creators_only)}", callback_data="admin:toggle_creators_only")],
        [InlineKeyboardButton("📢 Publier dans groupe secondaire", callback_data="admin:show_ad")],
        [InlineKeyboardButton("🖼 Publier dans groupe principal", callback_data="admin:share_ad")],
        [InlineKeyboardButton("📊 Statistiques", callback_data="admin:stats")],
        [InlineKeyboardButton("➕ Ajouter mot interdit", callback_data="admin:add_word")],
        [InlineKeyboardButton("➖ Enlever mot interdit", callback_data="admin:remove_word")],
        [InlineKeyboardButton("📋 Voir mots interdits", callback_data="admin:list_words")],
        [InlineKeyboardButton("📣 Broadcast groupe", callback_data="admin:broadcast")],
        [InlineKeyboardButton("📨 Broadcast utilisateurs", callback_data="admin:broadcast_users")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    if anti_spam(context, user.id):
        return

    set_user(user.id, username=user.username or "")
    row = get_user(user.id)

    if is_admin(user.id):
        await message.reply_text("Panel administrateur :", reply_markup=admin_panel())
        return

    if is_setting_on(SETTING_GROUPS_FULL):
        await delayed_user_reply()
        await message.reply_text(GROUPS_FULL_TEXT)
        return

    if row and row["status"] in (UNDER_REVIEW, APPROVED, BANNED):
        await delayed_user_reply()

        if row["status"] == UNDER_REVIEW:
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

    await delayed_user_reply()
    await safe_reply_photo(message, START_PHOTO_URL, START_TEXT, keyboard)


async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Accès refusé.")
        return

    await update.message.reply_text("Panel administrateur :", reply_markup=admin_panel())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Action annulée.")


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    data = q.data

    if anti_spam(context, user_id):
        await q.message.reply_text("Patiente quelques secondes avant de recliquer.")
        return

    if data.startswith("admin:"):
        if not is_admin(user_id):
            await q.message.reply_text("Accès refusé.")
            return

        action = data.split(":", 1)[1]

        if action == "toggle_groups_full":
            new_value = toggle_setting(SETTING_GROUPS_FULL)
            await q.message.reply_text(
                f"🚪 Groupes pleins : {on_off_label(new_value)}",
                reply_markup=admin_panel()
            )
            return

        if action == "toggle_creators_only":
            new_value = toggle_setting(SETTING_CREATORS_ONLY)
            await q.message.reply_text(
                f"🎥 Créatrices uniquement : {on_off_label(new_value)}",
                reply_markup=admin_panel()
            )
            return

        if action == "check_config":
            lines = ["⚙️ Vérification configuration\n"]
            lines.append("✅ BOT_TOKEN présent" if BOT_TOKEN else "❌ BOT_TOKEN manquant")
            lines.append("✅ DATABASE_URL présent" if DATABASE_URL else "❌ DATABASE_URL manquant")
            lines.append(f"✅ Admins configurés : {len(ADMIN_IDS)}" if ADMIN_IDS else "❌ ADMIN_IDS manquant")
            lines.append(f"✅ MAIN_GROUP_ID présent : {MAIN_GROUP_ID}" if MAIN_GROUP_ID else "❌ MAIN_GROUP_ID manquant")
            lines.append(f"✅ SECONDARY_GROUP_ID présent : {SECONDARY_GROUP_ID}" if SECONDARY_GROUP_ID else "❌ SECONDARY_GROUP_ID manquant")
            lines.append(f"🚪 Groupes pleins : {on_off_label(get_setting(SETTING_GROUPS_FULL))}")
            lines.append(f"🎥 Créatrices uniquement : {on_off_label(get_setting(SETTING_CREATORS_ONLY))}")

            try:
                with db() as con:
                    with con.cursor() as cur:
                        cur.execute("""
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                        ORDER BY table_name
                        """)
                        tables = [r["table_name"] for r in cur.fetchall()]
                        lines.append(f"✅ Tables DB : {', '.join(tables)}")
            except Exception as e:
                lines.append(f"❌ Erreur DB : {e}")

            for group_id, label in [
                (MAIN_GROUP_ID, "principal"),
                (SECONDARY_GROUP_ID, "secondaire"),
            ]:
                if group_id:
                    try:
                        chat = await context.bot.get_chat(group_id)
                        bot_member = await context.bot.get_chat_member(group_id, context.bot.id)
                        lines.append(f"✅ Groupe {label} trouvé : {chat.title}")

                        if bot_member.status in ("administrator", "creator"):
                            lines.append(f"✅ Bot admin dans le groupe {label}")
                        else:
                            lines.append(f"⚠️ Bot présent mais pas admin dans le groupe {label}")

                        if label == "principal":
                            lines.append("✅ Droit suppression messages OK" if getattr(bot_member, "can_delete_messages", False) else "⚠️ Droit suppression messages manquant")
                            lines.append("✅ Droit invitation utilisateurs OK" if getattr(bot_member, "can_invite_users", False) else "⚠️ Droit invitation utilisateurs manquant")

                    except Exception as e:
                        lines.append(f"❌ Impossible d’accéder au groupe {label}")
                        lines.append(f"Détail : {e}")

            lines.append("")
            lines.append("ℹ️ Publier dans groupe secondaire → groupe secondaire")
            lines.append("ℹ️ Publier dans groupe principal → groupe principal")

            await q.message.reply_text("\n".join(lines))
            return

        if action == "show_ad":
            if not SECONDARY_GROUP_ID:
                await q.message.reply_text("❌ SECONDARY_GROUP_ID manquant dans Railway.")
                return

            bot_username = await get_bot_username(context)

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔐 Je rejoins le groupe exclusif", url=f"https://t.me/{bot_username}?start=join")],
                [share_button()],
            ])

            try:
                await safe_send_photo_or_text(context, SECONDARY_GROUP_ID, AD_PHOTO_URL, AD_TEXT, keyboard)
                inc("ads_shown")
                await q.message.reply_text("✅ Publicité envoyée dans le groupe secondaire.")
            except TelegramError as e:
                await q.message.reply_text(f"❌ Impossible d’envoyer dans le groupe secondaire : {e}")
            return

        if action == "share_ad":
            if not MAIN_GROUP_ID:
                await q.message.reply_text("❌ MAIN_GROUP_ID manquant dans Railway.")
                return

            keyboard = InlineKeyboardMarkup([[share_button()]])

            try:
                await safe_send_photo_or_text(context, MAIN_GROUP_ID, SHARE_AD_PHOTO_URL, SHARE_PANEL_TEXT, keyboard)
                inc("share_panels_shown")
                await q.message.reply_text("✅ Panneau publicité envoyé dans le groupe principal.")
            except TelegramError as e:
                await q.message.reply_text(f"❌ Impossible d’envoyer dans le groupe principal : {e}")
            return

        if action == "stats":
            status_fr = {
                "new": "Nouveaux",
                "waiting": "Liste d’attente",
                "soft_reject": "Refus temporaires",
                "pending_media": "Média attendu",
                "under_review": "En analyse",
                "approved": "Acceptés",
                "banned": "Bannis",
                "refused": "Refusés",
            }

            stats_fr = {
                "ads_shown": "Publicités affichées",
                "share_panels_shown": "Panneaux publicité affichés",
                "waitlist": "Ajouts liste d’attente",
                "submissions": "Demandes envoyées",
                "approved": "Accès donnés",
                "banned": "Utilisateurs bannis",
                "refused": "Accès refusés",
                "broadcasts": "Broadcasts groupe",
                "broadcast_users": "Broadcasts utilisateurs",
                "restricted": "Utilisateurs restreints",
                "join_leave_deleted": "Messages arrivée/sortie supprimés",
            }

            with db() as con:
                with con.cursor() as cur:
                    cur.execute("SELECT status, COUNT(*) AS c FROM bot_users GROUP BY status")
                    users = cur.fetchall()

                    cur.execute("SELECT key, value FROM bot_stats ORDER BY key")
                    stats = cur.fetchall()

                    cur.execute("""
                    SELECT COUNT(*) AS c
                    FROM forbidden_words
                    WHERE group_id = %s AND is_active = true
                    """, (MAIN_GROUP_ID,))
                    words = cur.fetchone()["c"]

            lines = ["📊 Statistiques\n", "Utilisateurs :"]
            for r in users:
                lines.append(f"- {status_fr.get(r['status'], r['status'])} : {r['c']}")

            lines.append("\nActions :")
            for s in stats:
                lines.append(f"- {stats_fr.get(s['key'], s['key'])} : {s['value']}")

            lines.append(f"\nMots interdits actifs : {words}")
            lines.append(f"🚪 Groupes pleins : {on_off_label(get_setting(SETTING_GROUPS_FULL))}")
            lines.append(f"🎥 Créatrices uniquement : {on_off_label(get_setting(SETTING_CREATORS_ONLY))}")

            await q.message.reply_text("\n".join(lines))
            return

        if action == "add_word":
            context.user_data["mode"] = "add_word"
            await q.message.reply_text("Envoie le mot interdit à ajouter. /cancel pour annuler.")
            return

        if action == "remove_word":
            context.user_data["mode"] = "remove_word"
            await q.message.reply_text("Envoie le mot interdit à désactiver. /cancel pour annuler.")
            return

        if action == "list_words":
            with db() as con:
                with con.cursor() as cur:
                    cur.execute("""
                    SELECT word
                    FROM forbidden_words
                    WHERE group_id = %s AND is_active = true
                    ORDER BY word
                    """, (MAIN_GROUP_ID,))
                    rows = cur.fetchall()

            if not rows:
                await q.message.reply_text("📋 Aucun mot interdit actif.")
            else:
                await q.message.reply_text(
                    "📋 Mots interdits actifs :\n\n" +
                    "\n".join([f"- {r['word']}" for r in rows])
                )
            return

        if action == "broadcast":
            context.user_data["mode"] = "broadcast"
            await q.message.reply_text("Envoie le message à broadcaster dans le groupe principal. /cancel pour annuler.")
            return

        if action == "broadcast_users":
            context.user_data["mode"] = "broadcast_users"
            await q.message.reply_text("Envoie le message à envoyer à tous les utilisateurs du bot.\n/cancel pour annuler.")
            return

    row = get_user(user_id)

    if row and row["status"] in (UNDER_REVIEW, BANNED, APPROVED):
        await delayed_user_reply()
        await q.message.reply_text("Votre statut actuel ne permet pas de recommencer.")
        return

    if data == "user:intl":
        set_user(user_id, status=SOFT_REJECT, lang="international")
        inc("waitlist")
        await delayed_user_reply()
        await safe_callback_text(
            q,
            "Désolé, pour le moment nous ne pouvons pas donner accès aux profils internationaux.\n\n"
            "Le groupe est actuellement réservé aux profils FR francophones.\n\n"
            "👉 Tu pourras retenter ta chance plus tard si ton profil évolue."
        )
        return

    if data == "user:fr":
        set_user(user_id, lang="fr")
        await delayed_user_reply()
        await safe_callback_text(
            q,
            "Pour protéger la qualité du groupe, seuls les membres capables d’apporter une réelle valeur sont acceptés, sauf exception.\n\n"
            "Quelle situation correspond à ton profil ?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Je possède du contenu exclusif", callback_data="user:has_content")],
                [InlineKeyboardButton("🤝 Je ne possède pas de contenu exclusif mais je peux contribuer", callback_data="user:no_content")],
            ])
        )
        return

    if data == "user:no_content":
        set_user(user_id, status=SOFT_REJECT, has_content=0)
        inc("waitlist")
        await delayed_user_reply()
        await safe_callback_text(
            q,
            "Actuellement, l’accès est réservé aux profils apportant du contenu exclusif ou une forte valeur.\n\n"
            "👉 Tu pourras retenter ta chance plus tard si ton profil évolue."
        )
        return

    if data == "user:has_content":
        set_user(user_id, has_content=1)
        await delayed_user_reply()
        await safe_callback_text(
            q,
            "Très bien.\n\nQuel type de contenu possèdes-tu ?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔐 Contenu MYM / OnlyFans FR exclusif", callback_data="user:type_known")],
                [InlineKeyboardButton("🎥 Contenu amateur exclusif", callback_data="user:type_ama")],
            ])
        )
        return

    if data == "user:type_known":
        set_user(user_id, status=PENDING_MEDIA, content_type="known")
        await delayed_user_reply()
        await safe_callback_text(
            q,
            "Parfait.\n\n"
            "Pour vérifier que le contenu est réellement exclusif, envoie maintenant UN et UN SEUL média de ton choix.\n\n"
            "Photo, vidéo ou document accepté.\n\n"
            "⚠️ Toute fausse déclaration entraînera un bannissement définitif du groupe et du bot."
        )
        return

    if data == "user:type_ama":
        set_user(user_id, content_type="ama")
        await delayed_user_reply()
        await safe_callback_text(
            q,
            "Un média exclusif est un contenu que vous avez vous-même filmé et très peu, voire jamais partagé, ou un média obtenu sans qu’il circule sur Internet.\n\n"
            "Comment avez-vous obtenu les vôtres ?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ C’est un média que j’ai obtenu moi-même", callback_data="user:ama_self")],
                [InlineKeyboardButton("🔁 C’est un média que j’ai échangé", callback_data="user:ama_trade")],
            ])
        )
        return

    if data == "user:ama_trade":
        set_user(user_id, status=SOFT_REJECT, content_type="ama_trade")
        inc("waitlist")
        await delayed_user_reply()
        await safe_callback_text(
            q,
            "Les médias obtenus par échange sont souvent déjà diffusés ailleurs.\n\n"
            "Pour protéger la qualité du groupe, nous acceptons uniquement les contenus réellement rares ou obtenus directement.\n\n"
            "👉 Tu pourras retenter ta chance plus tard si ton profil évolue."
        )
        return

    if data == "user:ama_self":
        if is_setting_on(SETTING_CREATORS_ONLY):
            set_user(user_id, status=SOFT_REJECT, content_type="ama_self_creators_only")
            inc("waitlist")
            await delayed_user_reply()
            await safe_callback_text(q, CREATORS_ONLY_TEXT)
            return

        set_user(user_id, status=PENDING_MEDIA, content_type="ama_self")
        await delayed_user_reply()
        await safe_callback_text(
            q,
            "Parfait.\n\n"
            "Envoie maintenant UN et UN SEUL média de ton choix pour vérification.\n\n"
            "Photo, vidéo ou document accepté.\n\n"
            "⚠️ Seuls les contenus très rares, très peu diffusés ou jamais vus ailleurs sont acceptés.\n"
            "⚠️ Toute fausse déclaration entraînera un bannissement définitif du groupe et du bot."
        )
        return


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


async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    if anti_spam(context, user.id):
        return

    row = get_user(user.id)

    if not row or row["status"] != PENDING_MEDIA:
        return

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
        with con.cursor() as cur:
            cur.execute("""
            INSERT INTO bot_submissions(user_id, file_id, media_type)
            VALUES(%s, %s, %s)
            RETURNING id
            """, (user.id, file_id, media_type))

            sub_id = cur.fetchone()["id"]
            con.commit()

    set_user(user.id, status=UNDER_REVIEW)
    inc("submissions")

    await delayed_user_reply()
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
            with con.cursor() as cur:
                cur.execute("""
                INSERT INTO forbidden_words(group_id, word, is_active)
                VALUES(%s, %s, true)
                """, (MAIN_GROUP_ID, word))
                con.commit()

        context.user_data.clear()
        await message.reply_text(f"Mot interdit ajouté : {word}")
        return

    if is_admin(user.id) and context.user_data.get("mode") == "remove_word":
        word = text.lower().strip()

        with db() as con:
            with con.cursor() as cur:
                cur.execute("""
                UPDATE forbidden_words
                SET is_active = false
                WHERE group_id = %s AND LOWER(word) = LOWER(%s)
                """, (MAIN_GROUP_ID, word))

                affected = cur.rowcount
                con.commit()

        context.user_data.clear()

        if affected:
            await message.reply_text(f"Mot interdit désactivé : {word}")
        else:
            await message.reply_text(f"Mot introuvable ou déjà inactif : {word}")
        return

    if is_admin(user.id) and context.user_data.get("mode") == "broadcast":
        context.user_data.clear()

        if not MAIN_GROUP_ID:
            await message.reply_text("MAIN_GROUP_ID manquant.")
            return

        await safe_send_message(context, MAIN_GROUP_ID, text)
        inc("broadcasts")

        with db() as con:
            with con.cursor() as cur:
                cur.execute("""
                INSERT INTO broadcast_logs(group_id, admin_user_id, message)
                VALUES(%s, %s, %s)
                """, (MAIN_GROUP_ID, user.id, text))
                con.commit()

        await message.reply_text("Broadcast envoyé dans le groupe principal.")
        return

    if is_admin(user.id) and context.user_data.get("mode") == "broadcast_users":
        context.user_data.clear()

        with db() as con:
            with con.cursor() as cur:
                cur.execute("SELECT user_id FROM bot_users ORDER BY user_id")
                users = cur.fetchall()

        total = len(users)
        sent = 0
        failed = 0
        blocked = 0
        retried = 0

        await message.reply_text(
            f"📨 Broadcast utilisateurs lancé.\n\n"
            f"👥 Utilisateurs ciblés : {total}\n"
            f"⏳ Envoi sécurisé en cours..."
        )

        for row in users:
            target_id = row["user_id"]

            for attempt in range(BROADCAST_MAX_RETRIES + 1):
                try:
                    await context.bot.send_message(target_id, text)
                    sent += 1
                    break

                except RetryAfter as e:
                    retried += 1
                    await asyncio.sleep(e.retry_after + 1)

                except Forbidden:
                    blocked += 1
                    failed += 1
                    break

                except TelegramError as e:
                    logger.warning("Erreur broadcast utilisateur %s : %s", target_id, e)

                    if attempt < BROADCAST_MAX_RETRIES:
                        retried += 1
                        await asyncio.sleep(BROADCAST_RETRY_DELAY)
                    else:
                        failed += 1
                        break

                except Exception as e:
                    logger.warning("Erreur inconnue broadcast utilisateur %s : %s", target_id, e)
                    failed += 1
                    break

            await asyncio.sleep(BROADCAST_USER_DELAY)

        inc("broadcast_users")

        await message.reply_text(
            f"📨 Broadcast utilisateurs terminé\n\n"
            f"👥 Ciblés : {total}\n"
            f"✅ Envoyés : {sent}\n"
            f"🚫 Bloqués : {blocked}\n"
            f"🔁 Retry : {retried}\n"
            f"❌ Échecs : {failed}"
        )
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
            "Vous pouvez recommencer le formulaire avec /start.\n\n"
            "Attention, en cas d’abus, vous pourrez être banni."
        )

        await message.reply_text("Raison envoyée à l’utilisateur.")
        return

    if update.effective_chat and update.effective_chat.id == MAIN_GROUP_ID:
        with db() as con:
            with con.cursor() as cur:
                cur.execute("""
                SELECT word
                FROM forbidden_words
                WHERE group_id = %s AND is_active = true
                """, (MAIN_GROUP_ID,))
                words = [r["word"] for r in cur.fetchall()]

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

                with db() as con:
                    with con.cursor() as cur:
                        cur.execute("""
                        INSERT INTO member_offenses(group_id, user_id, offense_type, offense_count, last_offense_at)
                        VALUES(%s, %s, %s, 1, NOW())
                        ON CONFLICT(group_id, user_id, offense_type)
                        DO UPDATE SET
                            offense_count = member_offenses.offense_count + 1,
                            last_offense_at = NOW()
                        """, (MAIN_GROUP_ID, user.id, "forbidden_word"))
                        con.commit()

            except TelegramError as e:
                logger.warning("Erreur modération : %s", e)


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


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Erreur non gérée :", exc_info=context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN manquant")

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL manquant")

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
