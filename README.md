# Vendor Bot Final — FanMilk Togo

Backend unique du Vendor-Bot WhatsApp et des tableaux de bord FanMilk. Les
declarations du bot sont stockees dans PostgreSQL puis exposees par une API
Flask authentifiee. Le navigateur ne se connecte jamais directement a la base.

## Architecture

`WhatsApp -> Vendor-Bot Flask -> PostgreSQL <- API Flask <- Dashboard`

- Le revendeur utilise WhatsApp et est identifie par son numero de telephone.
- Le depositaire est rattache a un seul depot. Toutes ses requetes sont filtrees
  cote serveur avec le `depot_id` contenu dans son jeton.
- L'administrateur dispose de la vue nationale, sans droit de validation des
  ventes ou des stocks.

## Demarrage local

Le fichier `.env` local est deja cree et ignore par Git. Changez les mots de
passe avant toute mise en production et ajoutez les valeurs Meta reelles.

```powershell
cd "C:\Users\DELL LATITUDE 7430\Downloads\diagramme\Vendor-bot-final"
docker compose up --build -d
docker compose ps
```

Verification : <http://localhost:5000/healthz>

L'initialisation est automatique au demarrage. Pour la relancer :

```powershell
docker compose exec vendor-bot flask --app app.main init-db
```

Le fichier `schema_postgresql.sql` est aussi fourni pour une initialisation
manuelle, mais la commande Flask est recommandee car elle ajoute les depots,
les produits et les comptes initiaux definis dans `.env`.

## Connexion du dashboard local

Le dashboard doit utiliser `http://localhost:5000` comme URL d'API. Le parcours
est le suivant :

1. `POST /api/auth/login` avec `email` et `password` ;
2. conserver `access_token` pendant la session ;
3. envoyer `Authorization: Bearer <access_token>` sur les routes protegees ;
4. rediriger vers `/depositaire` ou `/dashboard` selon `user.role`.

Les identifiants locaux sont dans `.env` (`ADMIN_EMAIL`, `ADMIN_PASSWORD`,
`DEPOSITAIRE_EMAIL`, `DEPOSITAIRE_PASSWORD`). Ils ne sont jamais commites.

## API principale

### Authentification

- `POST /api/auth/login`
- `POST /api/auth/forgot-password`
- `POST /api/auth/reset-password`
- `GET /api/me`

La récupération de mot de passe utilise Resend. En production, renseignez
`RESEND_API_KEY`, `RESET_EMAIL_FROM` et `FRONTEND_URL`. Le lien envoyé est
valable 30 minutes et ne peut être utilisé qu'une fois.

### Depositaire

- `GET /api/depositaire/summary`
- `GET /api/depositaire/sales?status=en_attente`
- `PATCH /api/depositaire/sales/{id}` (`validate` ou `reject` + motif)
- `GET /api/depositaire/stocks?status=en_attente`
- `PATCH /api/depositaire/stocks/{id}`
- `GET /api/depositaire/performances`
- `GET /api/depositaire/bonuses`
- `GET /api/depositaire/difficulties`
- `GET /api/depositaire/history`

### Administrateur

- `GET /api/admin/summary`
- `GET|POST /api/admin/users`, `PATCH /api/admin/users/{id}`
- `GET /api/admin/performances`
- `GET|POST /api/admin/bonuses`
- `GET /api/admin/difficulties`, `PATCH /api/admin/difficulties/{id}`
- `GET /api/admin/sales` et `GET /api/admin/stocks` (lecture seule)
- `GET /api/admin/depots`

## Statuts metier

- vente : `en_attente`, `validee`, `rejetee` ;
- stock : `en_attente`, `valide`, `rejete` ;
- difficulte : `ouverte`, `en_cours`, `resolue`.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Les tests couvrent notamment la signature Meta, les doublons WhatsApp,
l'authentification, le filtrage serveur par depot, les droits et le motif de
rejet obligatoire.

## Render

`render.yaml` declare le service web et une base PostgreSQL. Dans Render,
ajoutez les variables Meta (`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`,
`WHATSAPP_VERIFY_TOKEN`, `META_APP_SECRET`) et les comptes initiaux. Changez
`CORS_ORIGINS` si le domaine du dashboard evolue.

## Securite

- Ne commitez jamais `.env`, un jeton Meta ou une cle privee.
- Remplacez tous les secrets locaux avant un deploiement public.
- Desactivez un compte au lieu de supprimer son historique.
- Le motif de rejet est obligatoire et est envoye au revendeur via WhatsApp.
- La validation reste une prerogative exclusive du depositaire.
