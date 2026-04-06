from datetime import datetime
from sqlalchemy.orm import Session
from .models import BotConfig, KnownChat, MediaItem, Admin


def ensure_single_config(db: Session) -> BotConfig:
    config = db.query(BotConfig).first()
    if not config:
        config = BotConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def ensure_admin(db: Session, user_id: int, username: str | None = None) -> Admin:
    admin = db.query(Admin).filter(Admin.user_id == user_id).first()
    if not admin:
        admin = Admin(user_id=user_id, username=username, is_active=True)
        db.add(admin)
        db.commit()
        db.refresh(admin)
    return admin


def is_admin(db: Session, user_id: int) -> bool:
    admin = db.query(Admin).filter(Admin.user_id == user_id, Admin.is_active == True).first()
    return admin is not None


def upsert_known_chat(db: Session, chat_id: int, title: str | None, chat_type: str | None) -> KnownChat:
    chat = db.query(KnownChat).filter(KnownChat.chat_id == chat_id).first()

    if not chat:
        chat = KnownChat(
            chat_id=chat_id,
            title=title,
            chat_type=chat_type,
            last_seen_at=datetime.utcnow(),
        )
        db.add(chat)
    else:
        chat.title = title
        chat.chat_type = chat_type
        chat.last_seen_at = datetime.utcnow()

    db.commit()
    db.refresh(chat)
    return chat


def get_known_group_chats(db: Session):
    return (
        db.query(KnownChat)
        .filter(KnownChat.chat_type.in_(["group", "supergroup"]))
        .order_by(KnownChat.title.asc())
        .all()
    )


def get_chat_by_id(db: Session, chat_id: int):
    return db.query(KnownChat).filter(KnownChat.chat_id == chat_id).first()


def set_source_chat(db: Session, chat_id: int, title: str):
    config = ensure_single_config(db)
    config.source_chat_id = chat_id
    config.source_chat_title = title
    db.commit()
    db.refresh(config)
    return config


def set_backup_chat(db: Session, chat_id: int, title: str):
    config = ensure_single_config(db)
    config.backup_chat_id = chat_id
    config.backup_chat_title = title
    db.commit()
    db.refresh(config)
    return config


def set_restore_chat(db: Session, chat_id: int, title: str):
    config = ensure_single_config(db)
    config.restore_chat_id = chat_id
    config.restore_chat_title = title
    db.commit()
    db.refresh(config)
    return config


def set_last_seen_chat(db: Session, chat_id: int | None, title: str | None):
    config = ensure_single_config(db)
    config.last_seen_chat_id = chat_id
    config.last_seen_chat_title = title
    db.commit()
    db.refresh(config)
    return config


def create_media_if_not_exists(
    db: Session,
    source_chat_id: int,
    source_message_id: int,
    media_type: str,
    file_id: str,
    file_unique_id: str,
    caption: str | None,
):
    existing = db.query(MediaItem).filter(MediaItem.file_unique_id == file_unique_id).first()
    if existing:
        return existing, False

    media = MediaItem(
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
        media_type=media_type,
        file_id=file_id,
        file_unique_id=file_unique_id,
        caption=caption,
        status="queued",
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    return media, True


def get_stats(db: Session):
    config = ensure_single_config(db)

    queued_count = db.query(MediaItem).filter(MediaItem.status == "queued").count()
    uploaded_count = db.query(MediaItem).filter(MediaItem.status == "uploaded").count()
    restored_count = db.query(MediaItem).filter(MediaItem.status == "restored").count()

    return {
        "queued": queued_count,
        "uploaded": uploaded_count,
        "restored": restored_count,
        "source_chat_id": config.source_chat_id,
        "source_chat_title": config.source_chat_title,
        "backup_chat_id": config.backup_chat_id,
        "backup_chat_title": config.backup_chat_title,
        "restore_chat_id": config.restore_chat_id,
        "restore_chat_title": config.restore_chat_title,
    }


def get_queued_media(db: Session):
    return (
        db.query(MediaItem)
        .filter(MediaItem.status == "queued")
        .order_by(MediaItem.id.asc())
        .all()
    )


def get_uploaded_media(db: Session):
    return (
        db.query(MediaItem)
        .filter(MediaItem.status == "uploaded")
        .order_by(MediaItem.id.asc())
        .all()
    )


def mark_media_uploaded(db: Session, media: MediaItem, backup_message_id: int | None = None):
    media.status = "uploaded"
    media.backup_message_id = backup_message_id
    media.uploaded_at = datetime.utcnow()
    db.commit()
    db.refresh(media)
    return media


def mark_media_restored(db: Session, media: MediaItem, restored_message_id: int | None = None):
    media.status = "restored"
    media.restored_message_id = restored_message_id
    media.restored_at = datetime.utcnow()
    db.commit()
    db.refresh(media)
    return media
