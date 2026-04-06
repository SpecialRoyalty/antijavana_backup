import requests
from .config import API_URL


def telegram_post(method: str, payload=None):
    if not API_URL:
        return {"ok": False, "description": "BOT_TOKEN missing"}
    payload = payload or {}
    url = f"{API_URL}/{method}"
    r = requests.post(url, json=payload, timeout=60)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "status_code": r.status_code, "text": r.text}


def send_message(chat_id: int, text: str, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram_post("sendMessage", payload)


def answer_callback_query(callback_query_id: str, text: str = ""):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return telegram_post("answerCallbackQuery", payload)


def copy_message(to_chat_id: int, from_chat_id: int, message_id: int):
    return telegram_post("copyMessage", {
        "chat_id": to_chat_id,
        "from_chat_id": from_chat_id,
        "message_id": message_id,
    })


def set_webhook(url: str):
    return telegram_post("setWebhook", {"url": url})


def get_me():
    return telegram_post("getMe")


def get_chat(chat_id: int):
    return telegram_post("getChat", {"chat_id": chat_id})
