# Vendor Bot Final

Version de travail indépendante du Vendor Bot FanMilk.

Ce dépôt est destiné à la migration vers MySQL et au futur raccordement du
Dashboard. Les secrets ne doivent jamais être ajoutés au dépôt : copiez
`.env.example` vers `.env` et renseignez les valeurs uniquement sur la machine
ou la plateforme de déploiement.

## Fonctionnalités

- webhook WhatsApp Flask ;
- parcours conversationnel des revendeurs ;
- génération des QR codes ;
- stockage MySQL des revendeurs, déclarations et sessions du bot ;
- détection des messages WhatsApp en double ;
- validation de la signature Meta `X-Hub-Signature-256` ;
- contrôle de santé `/healthz` ;
- lancement local avec Docker Compose.

## Démarrage local avec Docker

1. Installez Docker Desktop.
2. Copiez `.env.example` vers `.env`.
3. Remplacez toutes les valeurs `replace-with-...` dans `.env`.
4. Lancez `docker compose up --build -d`.
5. Vérifiez `http://localhost:5000/healthz`.

MySQL est conservé dans le volume Docker `fanmilk_mysql_data`. Le navigateur
et le Dashboard ne doivent jamais accéder directement à MySQL : ils passeront
par une API authentifiée.

## Initialisation sans Docker

Avec MySQL déjà installé et `DATABASE_URL` configurée :

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\flask.exe --app app.main init-db
.\.venv\Scripts\python.exe -m app.main
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

## Sécurité

- Ne commitez jamais `.env`, une clé de service ou un jeton Meta.
- Renouvelez tout jeton qui a déjà été publié ou partagé.
- Configurez `META_APP_SECRET`; les requêtes non signées sont rejetées.
- Exposez le webhook uniquement derrière HTTPS en production.
