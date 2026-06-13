# VitalIO

Plateforme de télésurveillance médicale connectée. VitalIO collecte des mesures physiologiques issues de dispositifs IoT, les stocke de manière sécurisée, déclenche des alertes cliniques et assiste les professionnels de santé via un module d'analyse par apprentissage automatique.

**Frontend** : [Vercel](https://vitalio-new.vercel.app)  
**Backend** : API Flask hébergée sur Render

---

## Sommaire

1. [Fonctionnalités](#fonctionnalités)
2. [Architecture](#architecture)
3. [Structure du dépôt](#structure-du-dépôt)
4. [Prérequis](#prérequis)
5. [Installation locale](#installation-locale)
6. [Variables d'environnement](#variables-denvironnement)
7. [Déploiement](#déploiement)
8. [Broker MQTT (développement)](#broker-mqtt-développement)
9. [Rôles et parcours utilisateur](#rôles-et-parcours-utilisateur)
10. [Tests](#tests)
11. [Sécurité et conformité](#sécurité-et-conformité)
12. [Documentation complémentaire](#documentation-complémentaire)

---

## Fonctionnalités

| Domaine | Description |
|---------|-------------|
| **IoT** | Ingestion MQTT (TLS) des mesures cardiaques, SpO2 et température |
| **Stockage** | MongoDB Atlas, bases séparées identité et données médicales |
| **Alertes** | Taxonomie Info / Warning / Critical / Urgency, seuils, alerte manuelle, escalade SAMU |
| **IA** | Détection d'anomalies (Isolation Forest), tendances et prévisions |
| **Authentification** | Auth0, JWT, contrôle d'accès par rôle (RBAC) |
| **Notifications** | E-mail (SMTP) et notifications push navigateur (VAPID) |
| **RGPD** | Export et suppression des données patient |

---

## Architecture

```
                    TLS (HTTPS)                         TLS (HTTPS)
  Navigateur  <------------------------->  React SPA (Vercel)
       |                                           |
       |              TLS (HTTPS) + JWT             |
       +------------------------------------------>  API Flask (Render)
                                                          |
                    TLS (mongodb+srv)                     |
       +-------------------------------------------------> MongoDB Atlas
       |                    Identity + Medical           |
       |                                                 |
  Capteur / simulateur                                    |
       |                                                  |
       |  TLS MQTT (port 8883, certificat CA)             |
       +------------------->  Mosquitto (Docker local) ---+ (ingestion mesures)
```

**Chiffrement en transit**

| Liaison | Protocole |
|---------|-----------|
| Navigateur ↔ Front Vercel | HTTPS (TLS) |
| Front ↔ API Render | HTTPS (TLS) |
| API ↔ MongoDB Atlas | TLS (`mongodb+srv`) |
| Device ↔ Mosquitto | MQTTS (TLS, port 8883) |
| Auth0 ↔ API | JWT signé RS256 sur HTTPS |

**Séparation et pseudonymisation**

- **Vitalio_Identity** : Auth0 sub, profils, liens, `patient_pseudo_id` (UUID).
- **Vitalio_Medical** : mesures et alertes via `device_id` + `patient_pseudo_id` (sans Auth0 sub).
- Profils : téléphone, adresse et historique chiffrés au repos (Fernet, `FIELD_ENCRYPTION_KEY`).

**Flux d'une mesure**

1. Un device publie sur le topic `vitalio/dev/{device_id}/measurements`.
2. L'API (ou le simulateur `scripts/simulate_sensor.py`) insère la mesure dans `Vitalio_Medical.measurements`.
3. Le moteur d'alertes évalue les seuils et le module ML calcule un score d'anomalie.
4. Le médecin et l'aidant consultent les alertes via le tableau de bord React.

---

## Structure du dépôt

```
vitalio/
├── README.md
├── docker-compose.yml           # Stack API + front + Mosquitto
├── .env.docker.example          # Variables VITE_* pour le build front
├── docs/                        # Guides Auth0, MQTT, tests E2E
├── .env.example                 # Modèle global (optionnel)
├── back/
│   ├── api.py                   # Point d'entrée (python api.py / gunicorn api:app)
│   ├── Dockerfile               # Image API
│   ├── docker-entrypoint.sh     # init ML + MQTT puis Gunicorn
│   ├── app/
│   │   ├── main.py              # Factory Flask (create_app)
│   │   ├── config.py            # Variables d'environnement
│   │   ├── database.py          # Client MongoDB et index
│   │   ├── auth.py              # JWT Auth0 et décorateurs RBAC
│   │   ├── mqtt_handler.py      # Abonnement MQTT
│   │   ├── ml/engine.py         # Détection d'anomalies et prévisions
│   │   ├── api/                 # Blueprints Flask (auth, patients, alerts…)
│   │   ├── services/            # Logique métier
│   │   └── models/              # Constantes collections MongoDB
│   ├── scripts/                 # seed_db, simulate_sensor, migrations…
│   ├── auth0/                   # Action post-login Auth0
│   ├── docker-compose.yml       # Broker Mosquitto (local)
│   ├── requirements.txt
│   ├── .env.example
│   ├── tests/
│   └── mosquitto/               # Configuration TLS du broker
└── front/
    └── vitalio/
        ├── Dockerfile           # Build Vite + nginx
        ├── src/                 # Pages React par rôle
        ├── .env.example
        └── package.json
```

---

## Prérequis

| Outil | Version minimale |
|-------|------------------|
| Python | 3.11+ |
| Node.js | 20+ |
| Docker | Pour Mosquitto en local |
| Compte Auth0 | Application SPA + API |
| Cluster MongoDB Atlas | Deux bases logiques (Identity, Medical) |

---

## Installation locale

### 1. Cloner le dépôt

```bash
git clone <url-du-depot>
cd vitalio
```

### 2. Backend

```bash
cd back
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env        # Windows
# cp .env.example .env        # Linux / macOS
```

Renseigner `back/.env` avec vos identifiants Auth0, MongoDB et MQTT.

Démarrer l'API :

```bash
python api.py
```

L'API écoute par défaut sur `http://localhost:5000`.  
Endpoint de santé : `GET /health`

### 3. Frontend

```bash
cd front/vitalio
npm install
copy .env.example .env
npm run dev
```

Interface disponible sur `http://localhost:5173`.

### 4. Association patient / device (première utilisation)

```bash
cd back
python scripts/seed_db.py
```

Nécessite `SEED_USER_ID_AUTH` (sub Auth0 du patient) et `SEED_DEVICE_ID` dans `.env`.

### 5. Docker (stack complète)

Alternative pour une démo ou un environnement reproductible (API + front + Mosquitto) :

```bash
# À la racine du dépôt
copy .env.docker.example .env          # Windows — variables VITE_* pour le build front
# cp .env.docker.example .env          # Linux / macOS

# Renseigner back/.env (MongoDB Atlas, Auth0, MQTT, SMTP…)
docker compose up --build
```

| Service | URL |
|---------|-----|
| Front | http://localhost:8080 |
| API | http://localhost:5000 |
| Mosquitto (TLS) | localhost:8883 |

**Auth0** : ajouter `http://localhost:8080` aux callbacks, logout URLs et web origins.

**MQTT dans Docker** : le service `api` se connecte au broker via le hostname `mosquitto` (défini dans `docker-compose.yml`). Les certificats TLS doivent être présents dans `back/mosquitto/certs/` (voir `docs/mqtt-quick-start.md`).

Pour Mosquitto seul (sans API conteneurisée) : `cd back && docker compose up -d`.

---

## Variables d'environnement

Les secrets ne doivent jamais être commités. Utiliser les fichiers modèles :

| Fichier | Usage |
|---------|-------|
| `back/.env.example` | API, MongoDB, MQTT, SMTP, VAPID |
| `front/vitalio/.env.example` | Auth0 et URL de l'API (`VITE_*`) |
| `.env.example` | Vue d'ensemble pour un setup racine |

Copier chaque `.env.example` vers `.env` et remplacer les placeholders.

Variables principales côté backend (détail dans `back/app/config.py`) :

| Variable | Rôle |
|----------|------|
| `AUTH0_DOMAIN` | Tenant Auth0 |
| `AUTH0_AUDIENCE` | Audience JWT |
| `MONGODB_URI` | Connexion Atlas ou locale |
| `MQTT_BROKER`, `MQTT_PORT` | Broker Mosquitto |
| `FRONTEND_URL` | URL du front (CORS, liens e-mail) |
| `SMTP_*` | Envoi d'e-mails |
| `VAPID_*` | Notifications push |
| `FIELD_ENCRYPTION_KEY` | Clé Fernet pour chiffrer téléphone, adresse, historique (générer via `python scripts/generate_field_encryption_key.py`) |

Variables frontend :

| Variable | Rôle |
|----------|------|
| `VITE_AUTH0_DOMAIN` | Tenant Auth0 |
| `VITE_AUTH0_CLIENT_ID` | Client SPA |
| `VITE_AUTH0_AUDIENCE` | Audience API |
| `VITE_API_URL` | URL de l'API Flask |

---

## Déploiement

### Backend (Render)

- **Build** : `pip install -r requirements.txt`
- **Start** : `gunicorn api:app --bind 0.0.0.0:$PORT`
- Configurer toutes les variables listées dans `back/.env.example` dans le dashboard Render.
- Sur Render, définir `MQTT_ENABLED=false` si aucun broker MQTT n'est accessible depuis le cloud.

### Frontend (Vercel)

- **Root directory** : `front/vitalio`
- **Build** : `npm run build`
- **Output** : `dist`
- Configurer `VITE_AUTH0_*` et `VITE_API_URL` (URL Render) dans les variables Vercel.

### Auth0

Configurer les URLs de callback, logout et web origins pour inclure :

- `http://localhost:5173` (développement)
- L'URL de production Vercel

Guide détaillé : `docs/auth0.md`

---

## Broker MQTT (développement)

Le broker Mosquitto tourne en local via Docker. Il n'est pas requis pour consulter des mesures déjà stockées dans MongoDB.

```bash
cd back
docker compose up -d
```

Configuration TLS et certificats : `docs/mqtt-quick-start.md`

Simuler un capteur :

```bash
cd back
python scripts/simulate_sensor.py
```

---

## Rôles et parcours utilisateur

| Rôle | Route principale | Accès |
|------|------------------|-------|
| Patient | `/patient` | Mesures, profil, alerte manuelle, module ML |
| Médecin | `/doctor` | Liste patients, alertes, validation clinique |
| Aidant | `/caregiver`, `/caregiver/alertes` | Suivi du proche, page alertes dédiée |
| Admin | `/admin` | Associations, gestion des devices |

Les rôles sont portés par le JWT Auth0 et confirmés en base (`Vitalio_Identity.users`).

---

## Taxonomie des alertes (Info / Warning / Critical / Urgency)

Chaque alerte persistée dans `Vitalio_Medical.alerts` expose un champ **`severity_level`** :

| Niveau grille | `severity_level` | Déclencheur VitalIO |
|---------------|------------------|---------------------|
| Info | `INFO` | Mesure dans les normes (`ml_level: normal`) — affiché sur la timeline patient |
| Warning | `WARNING` | Valeur proche du seuil clinique ou `ml_level: warning` |
| Critical | `CRITICAL` | Seuil dépassé (FC, SpO2, température) ou anomalie ML critique |
| Urgency | `URGENCY` | Alerte manuelle patient, `ml_urgency: immediate`, ou escalade SAMU (15) |

Les niveaux sont visibles côté médecin (`/doctor/alertes`), aidant (`/caregiver/alertes`) et patient (historique des mesures).

### Simulateur de démo (`back/simulate_alert.py`)

Depuis `back/` avec le venv activé et MongoDB accessible :

```bash
python simulate_alert.py --list-devices
python simulate_alert.py --metric near_spo2       # WARNING (SpO2 proche du seuil)
python simulate_alert.py --metric spo2            # CRITICAL (hypoxémie)
python simulate_alert.py --metric manual          # URGENCY (bouton patient)
python simulate_alert.py --metric heart_rate_high # CRITICAL (tachycardie)
```

Backfill des alertes existantes après déploiement :

```bash
python scripts/backfill_alert_severity.py
```

---

## Tests

```bash
cd back
python -m pytest tests/ -v
```

Suites disponibles :

- `test_linking_security.py` : sécurité des liens médecin/patient
- `test_ml_workflow.py` : pipeline ML
- `test_alert_ml_audit.py` : audit des alertes ML
- `test_severity_level.py` : taxonomie Info / Warning / Critical / Urgency
- `test_audit_log.py` : journal de sécurité global (`audit_log`)

---

## Sécurité et conformité

- **Authentification** : JWT Auth0 (RS256), validation côté API
- **Autorisation** : RBAC strict par endpoint (`@requires_role`)
- **Données** : séparation Identity / Medical, TLS MQTT et HTTPS
- **Audit global** : collection `Vitalio_Identity.audit_log` (append-only), consultation admin via `GET /api/admin/audit-log` et interface `/admin`
- **Audit métier** : `alert_events` (cycle de vie des alertes), `audit_links` (opérations de liaison)
- **Pseudonymisation** : `patient_pseudo_id` (UUID) en Identity, propagé dans les documents Medical
- **Chiffrement applicatif** : Fernet sur téléphone, adresse, historique médical et contacts d'urgence (`app/services/field_encryption.py`)
- **Chiffrement en transit** : HTTPS (front, API), TLS MongoDB Atlas, MQTTS (broker local)
- **RGPD** : export JSON et suppression des données via l'API patient (actions tracées dans `audit_log`)
- **Secrets** : `.env` exclu du dépôt (`.gitignore`), modèles sans secrets (`.env.example`). Les fichiers `.env` n'apparaissent pas dans l'historique Git du dépôt.

---

## Documentation complémentaire

| Document | Contenu |
|----------|---------|
| `docs/auth0.md` | Configuration Auth0 pas à pas |
| `docs/mqtt-quick-start.md` | Broker MQTT et certificats TLS |
| `docs/mqtt-tls.md` | Résumé TLS Mosquitto |
| `docs/association-e2e-test-plan.md` | Plan de tests association patient/device |
| `back/.env.example` | Référence complète des variables backend |

---

## Licence

Projet académique VitalIO. Contacter l'équipe projet pour toute réutilisation.
