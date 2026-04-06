from datetime import datetime
from sqlalchemy import Column, Integer, String, BigInteger, DateTime, Text, UniqueConstraint
from .db import Base


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    is_active = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BotConfig(Base):
    __tablename__ = "bot_config"

    id = Column(Integer, primary_key=True)
    source_chat_id = Column(BigInteger, nullable=True)
    source_chat_title = Column(String(255), nullable=True)

    backup_chat_id = Column(BigInteger, nullable=True)
    backup_chat_title = Column(String(255), nullable=True)

    restore_chat_id = Column(BigInteger, nullable=True)
    restore_chat_title = Column(String(255), nullable=True)

    last_seen_chat_id = Column(BigInteger, nullable=True)
    last_seen_chat_title = Column(String(255), nullable=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class KnownChat(Base):
    __tablename__ = "known_chats"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=True)
    chat_type = Column(String(50), nullable=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MediaItem(Base):
    __tablename__ = "media_items"
    __table_args__ = (
        UniqueConstraint("file_unique_id", name="uq_media_file_unique_id"),
    )

    id = Column(Integer, primary_key=True)
    source_chat_id = Column(BigInteger, nullable=False, index=True)
    source_message_id = Column(BigInteger, nullable=False)

    media_type = Column(String(20), nullable=False)  # video / document
    file_id = Column(Text, nullable=False)
    file_unique_id = Column(String(255), nullable=False, index=True)

    caption = Column(Text, nullable=True)
    mime_type = Column(String(255), nullable=True)
    file_name = Column(String(255), nullable=True)

    status = Column(String(20), default="queued", nullable=False, index=True)
    backup_message_id = Column(BigInteger, nullable=True)
    restored_message_id = Column(BigInteger, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    uploaded_at = Column(DateTime, nullable=True)
    restored_at = Column(DateTime, nullable=True)
