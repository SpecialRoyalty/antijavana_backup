# Telegram bot FastAPI + Railway

## Fichiers importants
- `app/main.py` : l'application FastAPI
- `app/__init__.py` : rend `app` importable comme package Python
- `requirements.txt` : dépendances
- `Procfile` et `railway.json` : démarrage Railway
- `.env.example` : variables d'environnement à créer dans Railway

## Variables Railway
Ajoute ces variables dans Railway:
- `BOT_TOKEN` = ton nouveau token Telegram
- `BASE_URL` = l'URL publique Railway, par ex. `https://ton-app.up.railway.app`

## Démarrage Railway
La commande de démarrage doit être:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
```

## Vérifications
Quand c'est déployé:
- `GET /` doit renvoyer `{"status":"ok","message":"Railway bot is running"}`
- `GET /health` doit renvoyer `{"healthy": true}`

## Installer le webhook
Option 1: ouvre dans ton navigateur:

`https://TON-APP.up.railway.app/set-webhook`

Option 2: appelle Telegram directement:

```bash
curl "https://api.telegram.org/bot<TON_TOKEN>/setWebhook?url=https://TON-APP.up.railway.app/webhook"
```

## Debug
Pour voir l'état du webhook:
- `GET /get-webhook-info`

## Commandes Telegram test
- `/start`
- `/ping`
- n'importe quel autre texte

## Important
Ton ancien token a été exposé. Révoque-le dans BotFather et crée un nouveau token avant de déployer ce projet.
