from datetime import datetime
from sqlalchemy import (
    Column, Integer, BigInteger, String, DateTime, Boolean,
    ForeignKey, UniqueConstraint, Text
)
from sqlalchemy.orm import relationship
from .db import Base


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True)
    telegram_user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class KnownChat(Base):
    __tablename__ = "known_chats"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    chat_type = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BotConfig(Base):
    __tablename__ = "bot_config"

    id = Column(Integer, primary_key=True)
    source_chat_id = Column(BigInteger, nullable=True)
    backup_chat_id = Column(BigInteger, nullable=True)
    restore_target_chat_id = Column(BigInteger, nullable=True)
    updated_by = Column(BigInteger, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MediaItem(Base):
    __tablename__ = "media_items"

    id = Column(Integer, primary_key=True)
    source_chat_id = Column(BigInteger, nullable=False, index=True)
    source_message_id = Column(BigInteger, nullable=False)
    media_kind = Column(String(30), nullable=False)  # video | document
    telegram_file_id = Column(Text, nullable=False)
    telegram_unique_id = Column(String(255), nullable=False, unique=True, index=True)
    caption = Column(Text, nullable=True)

    status = Column(String(30), default="queued", nullable=False, index=True)
    uploaded_to_chat_id = Column(BigInteger, nullable=True)
    uploaded_message_id = Column(BigInteger, nullable=True)
    restored_to_chat_id = Column(BigInteger, nullable=True)
    restored_message_id = Column(BigInteger, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    uploaded_at = Column(DateTime, nullable=True)
    restored_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("source_chat_id", "source_message_id", name="uq_source_message"),
    )


class TransferLog(Base):
    __tablename__ = "transfer_logs"

    id = Column(Integer, primary_key=True)
    action = Column(String(50), nullable=False)  # upload_to_backup | restore_to_source
    from_chat_id = Column(BigInteger, nullable=True)
    to_chat_id = Column(BigInteger, nullable=True)
    count_total = Column(Integer, default=0, nullable=False)
    count_success = Column(Integer, default=0, nullable=False)
    triggered_by = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
