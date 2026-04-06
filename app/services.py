from datetime import datetime
from sqlalchemy import func
from .models import BotConfig, KnownChat, MediaItem, Admin
from .telegram_api import copy_message


def ensure_single_config(db):
    config = db.query(BotConfig).first()
    if not config:
        config = BotConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def upsert_known_chat(db, chat_id: int, title: str | None, chat_type: str | None):
    item = db.query(KnownChat).filter(KnownChat.chat_id == chat_id).first()
    if not item:
        item = KnownChat(chat_id=chat_id, title=title, chat_type=chat_type)
        db.add(item)
    else:
        item.title = title
        item.chat_type = chat_type
        item.last_seen_at = datetime.utcnow()
    config = ensure_single_config(db)
    config.last_seen_chat_id = chat_id
    config.last_seen_chat_title = title
    db.commit()
    return item


def ensure_admins_from_env(db, admin_ids: set[int]):
    existing = {a.user_id for a in db.query(Admin).all()}
    changed = False
    for admin_id in admin_ids:
        if admin_id not in existing:
            db.add(Admin(user_id=admin_id, username=None, is_active=1))
            changed = True
    if changed:
        db.commit()


def is_admin(db, user_id: int) -> bool:
    row = db.query(Admin).filter(Admin.user_id == user_id, Admin.is_active == 1).first()
    return row is not None


def add_or_ignore_media(db, source_chat_id: int, source_message_id: int, media_type: str,
                        file_id: str, file_unique_id: str, caption: str | None,
                        mime_type: str | None, file_name: str | None):
    existing = db.query(MediaItem).filter(MediaItem.file_unique_id == file_unique_id).first()
    if existing:
        return existing, False

    item = MediaItem(
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
        media_type=media_type,
        file_id=file_id,
        file_unique_id=file_unique_id,
        caption=caption,
        mime_type=mime_type,
        file_name=file_name,
        status="queued",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item, True


def stats_text(db):
    config = ensure_single_config(db)
    queued = db.query(func.count(MediaItem.id)).filter(MediaItem.status == "queued").scalar() or 0
    uploaded = db.query(func.count(MediaItem.id)).filter(MediaItem.status == "uploaded").scalar() or 0
    restored = db.query(func.count(MediaItem.id)).filter(MediaItem.status == "restored").scalar() or 0

    source_name = f"{config.source_chat_title} ({config.source_chat_id})" if config.source_chat_id else "Non défini"
    backup_name = f"{config.backup_chat_title} ({config.backup_chat_id})" if config.backup_chat_id else "Non défini"
    restore_name = f"{config.restore_chat_title} ({config.restore_chat_id})" if config.restore_chat_id else "Non défini"
    last_seen = f"{config.last_seen_chat_title} ({config.last_seen_chat_id})" if config.last_seen_chat_id else "Aucun"

    return (
        "📊 Statistiques du bot\n\n"
        f"• En attente: {queued}\n"
        f"• Déjà envoyés au backup: {uploaded}\n"
        f"• Déjà restaurés: {restored}\n\n"
        f"• Groupe source: {source_name}\n"
        f"• Groupe backup: {backup_name}\n"
        f"• Nouveau principal: {restore_name}\n"
        f"• Dernier groupe vu: {last_seen}"
    )


def set_source_from_last_seen(db):
    config = ensure_single_config(db)
    if not config.last_seen_chat_id:
        return False, "Aucun groupe vu récemment."
    config.source_chat_id = config.last_seen_chat_id
    config.source_chat_title = config.last_seen_chat_title
    db.commit()
    return True, f"Groupe source défini: {config.source_chat_title} ({config.source_chat_id})"


def set_backup_from_last_seen(db):
    config = ensure_single_config(db)
    if not config.last_seen_chat_id:
        return False, "Aucun groupe vu récemment."
    config.backup_chat_id = config.last_seen_chat_id
    config.backup_chat_title = config.last_seen_chat_title
    db.commit()
    return True, f"Groupe backup défini: {config.backup_chat_title} ({config.backup_chat_id})"


def set_restore_from_last_seen(db):
    config = ensure_single_config(db)
    if not config.last_seen_chat_id:
        return False, "Aucun groupe vu récemment."
    config.restore_chat_id = config.last_seen_chat_id
    config.restore_chat_title = config.last_seen_chat_title
    db.commit()
    return True, f"Nouveau principal défini: {config.restore_chat_title} ({config.restore_chat_id})"


def upload_queued_to_backup(db):
    config = ensure_single_config(db)
    if not config.backup_chat_id:
        return False, "Groupe backup non défini."
    items = db.query(MediaItem).filter(MediaItem.status == "queued").order_by(MediaItem.id.asc()).all()
    if not items:
        return True, "Aucun média en attente."
    sent = 0
    for item in items:
        resp = copy_message(config.backup_chat_id, item.source_chat_id, item.source_message_id)
        if resp.get("ok"):
            item.status = "uploaded"
            item.uploaded_at = datetime.utcnow()
            item.backup_message_id = resp.get("result", {}).get("message_id")
            sent += 1
    db.commit()
    return True, f"{sent} média(s) envoyés vers le backup."


def restore_uploaded_to_primary(db):
    config = ensure_single_config(db)
    if not config.backup_chat_id:
        return False, "Groupe backup non défini."
    if not config.restore_chat_id:
        return False, "Nouveau principal non défini."

    items = db.query(MediaItem).filter(MediaItem.status.in_(["uploaded", "restored"])).order_by(MediaItem.id.asc()).all()
    if not items:
        return True, "Aucun média disponible pour restauration."

    sent = 0
    for item in items:
        if not item.backup_message_id:
            continue
        resp = copy_message(config.restore_chat_id, config.backup_chat_id, item.backup_message_id)
        if resp.get("ok"):
            item.status = "restored"
            item.restored_at = datetime.utcnow()
            item.restored_message_id = resp.get("result", {}).get("message_id")
            sent += 1
    db.commit()
    return True, f"{sent} média(s) restaurés vers le nouveau principal."
