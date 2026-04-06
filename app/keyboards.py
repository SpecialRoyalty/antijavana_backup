def admin_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "Définir source", "callback_data": "set_source"},
                {"text": "Définir backup", "callback_data": "set_backup"},
            ],
            [
                {"text": "Nouveau principal", "callback_data": "set_restore"},
                {"text": "Voir stats", "callback_data": "stats"},
            ],
            [
                {"text": "Téléverser vers backup", "callback_data": "upload_backup"},
            ],
            [
                {"text": "Restaurer backup → principal", "callback_data": "restore_backup"},
            ],
            [
                {"text": "Rafraîchir panneau", "callback_data": "panel"},
            ],
        ]
    }
