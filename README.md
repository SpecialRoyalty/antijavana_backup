# Telegram Backup Bot

Bot d'archivage manuel pour Telegram, prêt pour Railway.

## Fonctions
- surveille un groupe source
- enregistre les vidéos et documents en base
- évite les doublons avec `file_unique_id`
- panneau admin en boutons inline
- upload manuel vers groupe backup
- restauration vers un nouveau groupe principal
- statistiques en temps réel

## Variables Railway
- `BOT_TOKEN`
- `BASE_URL`
- `DATABASE_URL` (optionnel, défaut SQLite)
- `ADMIN_IDS` (liste d'IDs Telegram séparés par des virgules)

## Déploiement
Start command :
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Mise en route
1. Déploie le projet sur Railway
2. Mets les variables d'environnement
3. Ouvre `/set-webhook`
4. Ajoute le bot dans le groupe source et le groupe backup
5. Donne au bot les droits d'envoyer des messages et médias
6. En MP au bot, clique sur **Ouvrir panneau admin**

## Note importante
Le bot sait définir un groupe source / backup à partir du **dernier groupe vu**.
Pour cela :
1. ajoute d'abord le bot dans le groupe
2. envoie un message ou un média dans ce groupe
3. le groupe apparaîtra comme "dernier groupe vu"
4. depuis le panneau admin, utilise :
   - Définir source = dernier groupe vu
   - Définir backup = dernier groupe vu
   - Définir nouveau principal = dernier groupe vu

## Endpoints utiles
- `/` : health check
- `/set-webhook` : enregistre le webhook
- `/debug/config` : état de config
- `/debug/media` : aperçu des médias
