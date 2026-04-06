import os


def parse_admin_ids(raw: str) -> set[int]:
    values = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.add(int(part))
        except ValueError:
            pass
    return values


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
ADMIN_IDS = parse_admin_ids(os.getenv("ADMIN_IDS", ""))
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None
