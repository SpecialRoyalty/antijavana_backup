import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_url: str
    source_chat_id: int
    backup_chat_id: int
    admin_user_ids: set[int]
    webhook_path_secret: str
    webhook_url: str | None
    telegram_secret_token: str | None
    port: int



def _parse_int_set(raw: str | None) -> set[int]:
    if not raw:
        return set()
    return {int(x.strip()) for x in raw.split(",") if x.strip()}



def get_settings() -> Settings:
    bot_token = os.environ["BOT_TOKEN"]
    database_url = os.environ["DATABASE_URL"]
    source_chat_id = int(os.environ["SOURCE_CHAT_ID"])
    backup_chat_id = int(os.environ["BACKUP_CHAT_ID"])
    webhook_path_secret = os.environ.get("WEBHOOK_PATH_SECRET", "telegram-webhook")
    webhook_url = os.environ.get("WEBHOOK_URL")
    telegram_secret_token = os.environ.get("TELEGRAM_SECRET_TOKEN")
    port = int(os.environ.get("PORT", "8000"))
    admin_user_ids = _parse_int_set(os.environ.get("ADMIN_USER_IDS"))

    return Settings(
        bot_token=bot_token,
        database_url=database_url,
        source_chat_id=source_chat_id,
        backup_chat_id=backup_chat_id,
        admin_user_ids=admin_user_ids,
        webhook_path_secret=webhook_path_secret,
        webhook_url=webhook_url,
        telegram_secret_token=telegram_secret_token,
        port=port,
    )
