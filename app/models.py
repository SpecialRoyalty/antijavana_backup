from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean, Text
from .db import Base


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BotConfig(Base):
    __tablename__ = "bot_config"

    id = Column(Integer, primary_key=True, index=True)

    source_chat_id = Column(BigInteger, nullable=True)
    source_chat_title = Column(String, nullable=True)

    backup_chat_id = Column(BigInteger, nullable=True)
    backup_chat_title = Column(String, nullable=True)

    restore_chat_id = Column(BigInteger, nullable=True)
    restore_chat_title = Column(String, nullable=True)

    last_seen_chat_id = Column(BigInteger, nullable=True)
    last_seen_chat_title = Column(String, nullable=True)

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )


class KnownChat(Base):
    __tablename__ = "known_chats"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(BigInteger, unique=True, index=True, nullable=False)
    title = Column(String, nullable=True)
    chat_type = Column(String, nullable=True)  # private | group | supergroup | channel
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MediaItem(Base):
    __tablename__ = "media_items"

    id = Column(Integer, primary_key=True, index=True)

    source_chat_id = Column(BigInteger, nullable=False)
    source_message_id = Column(BigInteger, nullable=False)

    media_type = Column(String, nullable=False)  # video | document
    file_id = Column(Text, nullable=False)
    file_unique_id = Column(String, unique=True, index=True, nullable=False)
    caption = Column(Text, nullable=True)

    status = Column(String, default="queued", nullable=False)  # queued | uploaded | restored

    backup_message_id = Column(BigInteger, nullable=True)
    restored_message_id = Column(BigInteger, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    uploaded_at = Column(DateTime, nullable=True)
    restored_at = Column(DateTime, nullable=True)


class TransferLog(Base):
    __tablename__ = "transfer_logs"

    id = Column(Integer, primary_key=True, index=True)

    media_item_id = Column(Integer, nullable=False)
    action = Column(String, nullable=False)  # upload | restore
    target_chat_id = Column(BigInteger, nullable=True)
    target_message_id = Column(BigInteger, nullable=True)

    status = Column(String, nullable=False, default="success")  # success | failed
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
