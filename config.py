import asyncpg
from typing import Any, Optional


class Database:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def init(self) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS backups (
                    id BIGSERIAL PRIMARY KEY,
                    source_chat_id BIGINT NOT NULL,
                    source_message_id BIGINT NOT NULL,
                    backup_chat_id BIGINT NOT NULL,
                    backup_message_id BIGINT NOT NULL,
                    media_kind TEXT NOT NULL,
                    media_group_id TEXT,
                    caption TEXT,
                    file_unique_id TEXT,
                    sent_by_user_id BIGINT,
                    message_date TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(source_chat_id, source_message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_backups_message_date ON backups(message_date);
                CREATE INDEX IF NOT EXISTS idx_backups_media_group ON backups(media_group_id);

                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

    async def add_backup(self, record: dict[str, Any]) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO backups (
                    source_chat_id, source_message_id, backup_chat_id, backup_message_id,
                    media_kind, media_group_id, caption, file_unique_id,
                    sent_by_user_id, message_date
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10
                )
                ON CONFLICT (source_chat_id, source_message_id) DO NOTHING
                """,
                record["source_chat_id"],
                record["source_message_id"],
                record["backup_chat_id"],
                record["backup_message_id"],
                record["media_kind"],
                record.get("media_group_id"),
                record.get("caption"),
                record.get("file_unique_id"),
                record.get("sent_by_user_id"),
                record["message_date"],
            )

    async def set_setting(self, key: str, value: str) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_settings (key, value, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                key,
                value,
            )

    async def get_setting(self, key: str) -> Optional[str]:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM bot_settings WHERE key = $1", key)
            return row["value"] if row else None

    async def count_backups(self) -> int:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            value = await conn.fetchval("SELECT COUNT(*) FROM backups")
            return int(value or 0)

    async def list_last_backups(self, limit: int) -> list[asyncpg.Record]:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM backups
                ORDER BY message_date ASC
                LIMIT $1
                """,
                limit,
            )
            return list(rows)

    async def list_backups_desc(self, limit: int) -> list[asyncpg.Record]:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM backups
                ORDER BY message_date DESC
                LIMIT $1
                """,
                limit,
            )
            return list(rows)

    async def list_backups_since(self, start_date: str) -> list[asyncpg.Record]:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM backups
                WHERE message_date >= $1::date
                ORDER BY message_date ASC
                """,
                start_date,
            )
            return list(rows)

    async def list_all_backups(self) -> list[asyncpg.Record]:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM backups ORDER BY message_date ASC"
            )
            return list(rows)
