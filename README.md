# VitalIO

Plateforme de télésurveillance médicale connectée. VitalIO collecte des mesures physiologiques issues de capteurs depuis un dispositifs IoT, les stocke de manière sécurisée, déclenche des alertes cliniques et assiste les professionnels de santé via un module d'analyse par apprentissage automatique.

| Composant | Hébergement |
|-----------|-------------|
| **Frontend** | [Vercel](https://vitalio-new.vercel.app) |
| **Backend API** | Render (Flask / Gunicorn) |
| **Base de données** | MongoDB Atlas |
| **Broker MQTT** | [HiveMQ Cloud](https://www.hivemq.com/mqtt-cloud/) (MQTTS) |

---

## Sommaire

1. [Fonctionnalités](#fonctionnalités)
2. [Architecture](#architecture)
3. [Structure du dépôt](#structure-du-dépôt)
4. [Prérequis](#prérequis)
5. [Installation locale](#installation-locale)
6. [Variables d'environnement](#variables-denvironnement)
7. [Broker MQTT (HiveMQ Cloud)](#broker-mqtt-hivemq-cloud)
8. [Déploiement](#déploiement)
9. [Rôles et parcours utilisateur](#rôles-et-parcours-utilisateur)
10. [Alertes](#alertes-info--warning--critical--urgency)
11. [Tests](#tests)
12. [Sécurité et conformité](#sécurité-et-conformité)
13. [Documentation complémentaire](#documentation-complémentaire)

---

## Fonctionnalités

| Domaine | Description |
|---------|-------------|
| **IoT** | Ingestion MQTT (TLS) des mesures cardiaques, SpO₂ et température via HiveMQ Cloud |
| **Stockage** | MongoDB Atlas, bases séparées identité et données médicales |
| **Alertes** | Info / Warning / Critical / Urgency, seuils, alerte manuelle, escalade SAMU |
| **IA** | Détection d'anomalies (Isolation Forest), tendances et prévisions |
| **Authentification** | Auth0, JWT, contrôle d'accès par rôle (RBAC) |
| **Notifications** | E-mail (Mailjet) et notifications push navigateur (VAPID) |
| **RGPD** | Export et suppression des données patient |

---

## Architecture

### Chiffrement en transit

| Liaison | Protocole |
|---------|-----------|
| Navigateur ↔ Front Vercel | HTTPS (TLS) |
| Front ↔ API Render | HTTPS (TLS) |
| API ↔ MongoDB Atlas | TLS (`mongodb+srv`) |
| Device / API ↔ HiveMQ Cloud | MQTTS |
| Auth0 ↔ API | JWT |

### Séparation et pseudonymisation

- **Vitalio_Identity** : Auth0 sub, profils, liens, `patient_pseudo_id` (UUID).
- **Vitalio_Medical** : mesures et alertes via `device_id` + `patient_pseudo_id` (sans JWT sub).
- Profils : téléphone, adresse et historique chiffrés au repos (Fernet, `FIELD_ENCRYPTION_KEY`).

### Flux d'une mesure

1. Un device publie sur le topic `vitalio/dev/{device_id}/measurements` sur **HiveMQ Cloud**.
2. L'API Flask (Render) est abonnée au même broker et reçoit le message en temps réel.
3. L'API insère la mesure dans `Vitalio_Medical.measurements`.
4. Le moteur d'alertes évalue les seuils et le module ML calcule un score d'anomalie.
5. Le médecin et l'aidant consultent les alertes via le tableau de bord.

---

## Structure du dépôt

```
vitalio/
├── README.md
├── docker-compose.yml           # Stack locale optionnelle (API + front + Mosquitto)
├── .env.docker.example
├── docs/                        # Auth0, MQTT (legacy Mosquitto), tests E2E
├── back/
│   ├── api.py                   # Point d'entrée (python api.py / gunicorn api:app)
│   ├── Dockerfile
│   ├── docker-entrypoint.sh
│   ├── app/
│   │   ├── main.py              # Factory Flask
│   │   ├── config.py            # Variables d'environnement
│   │   ├── mqtt_handler.py      # Abonné MQTT → persistance + alertes
│   │   ├── ml/engine.py
│   │   ├── api/
│   │   └── services/
│   ├── scripts/
│   ├── docker-compose.yml       # Mosquitto seul
│   ├── mosquitto/               # Config TLS legacy (dev local uniquement)
│   ├── requirements.txt
│   ├── .env.example
│   └── tests/
└── front/
    └── vitalio/                 # SPA React (Vite)
```

---

## Prérequis

| Outil | Version minimale |
|-------|------------------|
| Python | 3.11+ |
| Node.js | 20+ |
| Compte Auth0 | Application SPA + API |
| Cluster MongoDB Atlas | Bases Identity + Medical |
| Cluster HiveMQ Cloud | Broker MQTTS + identifiants (username / password) |
| Docker | Optionnel (stack locale avec Mosquitto) |

---

## Installation locale

### 1. Cloner le dépôt

```bash
git clone https://github.com/klueko/vitalio.git
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

Renseigner `back/.env` : Auth0, MongoDB Atlas, **HiveMQ Cloud** (voir [Broker MQTT](#broker-mqtt-hivemq-cloud)), Mailjet, VAPID, etc.

Démarrer l'API (l'abonné MQTT démarre automatiquement si `MQTT_ENABLED=true`) :

```bash
python api.py
```

### 3. Frontend

```bash
cd front/vitalio
npm install
copy .env.example .env
npm run dev
```

Interface : http://localhost:5173

### 4. Association patient / device (première utilisation)

```bash
cd back
python scripts/seed_db.py
```

Nécessite `SEED_USER_ID_AUTH` (sub Auth0 du patient) et `SEED_DEVICE_ID` dans `.env`.

### 5. Docker (optionnel - stack locale complète)

Alternative pour une démo **sans HiveMQ** (broker Mosquitto embarqué) :

```bash
# À la racine du dépôt
copy .env.docker.example .env
docker compose up --build
```

| Service | URL |
|---------|-----|
| Front | http://localhost:8080 |
| API | http://localhost:5000 |
| Mosquitto (TLS, local) | localhost:8883 |

En production et en dev « cloud », préférez **HiveMQ Cloud** plutôt que Mosquitto. Voir [Broker MQTT](#broker-mqtt-hivemq-cloud).

---

## Variables d'environnement

| Fichier | Usage |
|---------|-------|
| `back/.env.example` | Modèle API (Auth0, MongoDB, HiveMQ, Mailjet, VAPID…) |
| `front/vitalio/.env.example` | Auth0 SPA + URL API |

### Backend (principales)

| Variable | Rôle |
|----------|------|
| `AUTH0_DOMAIN` | Tenant Auth0 |
| `AUTH0_AUDIENCE` | Audience JWT |
| `MONGODB_URI` | Connexion Atlas |
| `MQTT_BROKER` | Hostname HiveMQ Cloud (ex. `xxxx.s1.eu.hivemq.cloud`) |
| `MQTT_PORT` | `8883` (MQTTS) |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | Identifiants du cluster HiveMQ |
| `MQTT_CA_CERT` | Certificat CA pour valider le TLS du broker |
| `MQTT_TOPIC` | Topic d'écoute (défaut : `vitalio/dev/+/measurements`) |
| `MQTT_ENABLED` | `true` pour activer l'abonné au démarrage de l'API |
| `FRONTEND_URL` | URL du front (CORS, liens e-mail) |
| `SMTP_USER` / `SMTP_PASSWORD` | Clés API Mailjet |
| `EMAIL_FROM` | Expéditeur validé Mailjet |
| `VAPID_*` | Notifications push |
| `FIELD_ENCRYPTION_KEY` | Fernet - `python scripts/generate_field_encryption_key.py` |

### Frontend

| Variable | Rôle |
|----------|------|
| `VITE_AUTH0_DOMAIN` | Tenant Auth0 |
| `VITE_AUTH0_CLIENT_ID` | Client SPA |
| `VITE_AUTH0_AUDIENCE` | Audience API |
| `VITE_API_URL` | URL de l'API Flask (Render en prod) |

---

## Broker MQTT (HiveMQ Cloud)

VitalIO utilise **HiveMQ Cloud** comme broker MQTT managé en production. L'API Render et les devices se connectent au **même cluster** en MQTTS (port 8883).

### Configuration dans HiveMQ Cloud

1. Créer un cluster sur [HiveMQ Cloud](https://console.hivemq.cloud/) (région EU recommandée pour Atlas / Render EU).
2. Récupérer dans le dashboard :
   - **Broker URL** (hostname)
   - **Port** : 8883
   - **Username** et **Password** (credentials du cluster)
3. Télécharger le certificat CA HiveMQ (`hivemq-ca.pem` ou équivalent) et le placer dans `back/certs/` (ou un chemin de votre choix).

### Exemple `back/.env`

```env
MQTT_BROKER=xxxxxxxx.s1.eu.hivemq.cloud
MQTT_PORT=8883
MQTT_USERNAME=votre-utilisateur-hivemq
MQTT_PASSWORD=votre-mot-de-passe-hivemq
MQTT_CA_CERT=./certs/hivemq-ca.pem
MQTT_TOPIC=vitalio/dev/+/measurements
MQTT_ENABLED=true
```

### Topic et payload

| Élément | Valeur |
|---------|--------|
| Topic publish | `vitalio/dev/{device_id}/measurements` |
| QoS | 1 (recommandé) |
| Format | JSON (`heart_rate`, `spo2`, `temperature`, `timestamp`…) |

Exemple de payload :

```json
{
  "heart_rate": 72,
  "spo2": 98,
  "temperature": 36.6,
  "timestamp": "2026-06-15T10:30:00Z"
}
```

### Simuler un capteur (dev / test)

Le script publie sur le broker configuré dans `.env` (HiveMQ ou Mosquitto local) :

```bash
cd back
python scripts/simulate_sensor.py
```

Variables utiles : `DEVICE_ID`, `MQTT_BROKER`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_CA_CERT`.

### Mosquitto local (optionnel)

Pour travailler **sans** HiveMQ (offline, CI, démo Docker), un broker Mosquitto peut tourner en local :

```bash
cd back
docker compose up -d
```

Guides TLS Mosquitto (legacy) : `docs/mqtt-quick-start.md`, `docs/mqtt-tls.md`.

---

## Déploiement

### Backend (Render)

- **Build** : `pip install -r requirements.txt`
- **Start** : `gunicorn api:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
- Configurer toutes les variables de `back/.env.example` dans le dashboard Render.
- **MQTT** : renseigner les variables HiveMQ (`MQTT_BROKER`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_CA_CERT`) et laisser `MQTT_ENABLED=true` pour que l'API consomme les mesures en temps réel.
- Placer le certificat CA HiveMQ sur l'instance (variable `MQTT_CA_CERT` pointant vers le fichier) ou l'inclure dans l'image Docker si vous déployez via conteneur.

### Frontend (Vercel)

- **Root directory** : `front/vitalio`
- **Build** : `npm run build`
- Variables : `VITE_AUTH0_*`, `VITE_API_URL` (URL Render).

### Auth0

URLs de callback, logout et web origins :

- `http://localhost:5173` (développement)
- URL de production Vercel

Guide détaillé : `docs/auth0.md`

---

## Rôles et parcours utilisateur

| Rôle | Route principale | Accès |
|------|------------------|-------|
| Patient | `/patient` | Mesures, profil, alerte manuelle, module ML |
| Médecin | `/doctor` | Liste patients, alertes, validation clinique |
| Aidant | `/caregiver`, `/caregiver/alertes` | Suivi du proche, page alertes dédiée |
| Admin | `/admin` | Associations, gestion des devices, audit |

Les rôles sont portés par le JWT Auth0 et confirmés en base (`Vitalio_Identity.users`).

---

## Alertes (Info / Warning / Critical / Urgency)

Chaque alerte dans `Vitalio_Medical.alerts` expose un champ **`severity_level`** :

| Niveau grille | `severity_level` | Déclencheur VitalIO |
|---------------|------------------|---------------------|
| Info | `INFO` | Mesure dans les normes (`ml_level: normal`) |
| Warning | `WARNING` | Valeur proche du seuil ou `ml_level: warning` |
| Critical | `CRITICAL` | Seuil dépassé ou anomalie ML critique |
| Urgency | `URGENCY` | Alerte manuelle patient ou escalade SAMU |

Visible côté médecin (`/doctor/alertes`), aidant (`/caregiver/alertes`) et patient.

### Simulateur de démo

```bash
cd back
python simulate_alert.py --list-devices
python simulate_alert.py --metric near_spo2       # WARNING
python simulate_alert.py --metric spo2            # CRITICAL
python simulate_alert.py --metric manual          # URGENCY
python simulate_alert.py --metric heart_rate_high # CRITICAL
```

---

## Tests

```bash
cd back
python -m pytest tests/ -v
```

Suites : `test_linking_security`, `test_ml_workflow`, `test_alert_ml_audit`, `test_severity_level`, `test_audit_log`, `test_patient_display_name`, `test_doctor_patient_unlink`.

---

## Sécurité et conformité

- **Authentification** : JWT Auth0 (RS256), validation côté API
- **Autorisation** : RBAC strict par endpoint (`@requires_role`)
- **Données** : séparation Identity / Medical, pseudonymisation `patient_pseudo_id`
- **Chiffrement en transit** : HTTPS, TLS MongoDB Atlas, **MQTTS HiveMQ Cloud**
- **Chiffrement au repos** : Fernet sur téléphone, adresse, historique (`field_encryption.py`)
- **Audit** : `audit_log` (append-only), `alert_events`, `audit_links`
- **RGPD** : export JSON et suppression patient (actions tracées)
- **Secrets** : `.env` exclu du dépôt ; modèles sans secrets (`.env.example`)

---

## Documentation complémentaire

| Document | Contenu |
|----------|---------|
| `docs/auth0.md` | Configuration Auth0 |
| `docs/mqtt-quick-start.md` | Mosquitto local (legacy / dev) |
| `docs/mqtt-tls.md` | TLS Mosquitto local |
| `docs/association-migration-notes.md` | Liens médecin–patient |
