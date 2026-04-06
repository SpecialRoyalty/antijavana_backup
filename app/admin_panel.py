from typing import List, Tuple, Dict, Any


def inline_keyboard(button_rows: List[List[Dict[str, str]]]) -> Dict[str, Any]:
    return {"inline_keyboard": button_rows}


def admin_main_menu() -> Dict[str, Any]:
    return inline_keyboard([
        [{"text": "🎯 Définir Source", "callback_data": "pick_source"}],
        [{"text": "💾 Définir Backup", "callback_data": "pick_backup"}],
        [{"text": "📊 Voir les stats", "callback_data": "show_stats"}],
        [{"text": "⬆️ Téléverser vers backup", "callback_data": "upload_backup"}],
        [{"text": "🆕 Choisir nouveau principal", "callback_data": "pick_restore"}],
        [{"text": "♻️ Restaurer backup → principal", "callback_data": "restore_backup"}],
    ])


def known_chats_menu(chats: List[Tuple[int, str]], action: str, title: str):
    rows = []

    for chat_id, chat_title in chats:
        safe_title = (chat_title or str(chat_id))[:60]
        rows.append([
            {
                "text": f"🎯 {safe_title}",
                "callback_data": f"{action}:{chat_id}",
            }
        ])

    rows.append([{"text": "⬅ Retour", "callback_data": "admin_menu"}])

    return title, inline_keyboard(rows)
