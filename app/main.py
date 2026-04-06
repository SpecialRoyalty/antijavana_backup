import os
import asyncio
from telethon import TelegramClient, events

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SOURCE_CHAT_ID = int(os.getenv("SOURCE_CHAT_ID"))
BACKUP_CHAT_ID = int(os.getenv("BACKUP_CHAT_ID"))

client = TelegramClient("session", API_ID, API_HASH)

@client.on(events.NewMessage(chats=SOURCE_CHAT_ID))
async def handler(event):
    msg = event.message

    if not (msg.video or msg.document):
        return

    print("📥 Média détecté")

    file_path = await msg.download_media(file="/tmp/")
    print(f"⬇️ Téléchargé: {file_path}")

    caption = msg.text or ""

    await client.send_file(
        BACKUP_CHAT_ID,
        file_path,
        caption=caption,
        supports_streaming=True
    )
    print("📤 Envoyé dans le backup")

    try:
        os.remove(file_path)
    except Exception as e:
        print(f"⚠️ Suppression impossible: {e}")

async def main():
    await client.start()
    print("✅ Userbot connecté")
    print(f"📡 Source: {SOURCE_CHAT_ID}")
    print(f"📦 Backup: {BACKUP_CHAT_ID}")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
