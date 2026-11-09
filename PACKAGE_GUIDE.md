# Notifier Service Hub — Package Guide & PyPI Publication

A free, open-source, multi-channel notification and alert dispatching engine with **embedded SQLite by default**, **zero-authentication open access**, and **one-command deployment**.

---

## 1. Key Highlights

- **100% Free & Open Source**: MIT Licensed.
- **Embedded SQLite by Default**: Zero setup. Runs instantly without setting up or running external database servers.
- **Flexible Database Switching**: Effortlessly switch to **PostgreSQL** or **MySQL** whenever your scale demands it using simple environment variables.
- **Zero-Authentication Open Mode**: Anyone can send notifications and access the dashboard immediately without logins, user accounts, or API keys.
- **Multi-Channel**: Supports **Email (SMTP)**, **Telegram**, **WhatsApp Cloud API**, and **Instagram Messaging API**.
- **High-Reliability Pipeline**: Background queuing, deduplication, automatic retries with exponential backoff, and a dead-letter queue (DLQ).

---

## 2. Quickstart & Installation

### Option A: Install from PyPI
```bash
pip install notifier-service-hub
```

### Option B: Local / Development Install
```bash
git clone https://github.com/example/notifier-service.git
cd notifier-service
pip install -e .
```

### Run with a Single Command
Run the built-in CLI command:
```bash
notifier-service
```
This command automatically:
1. Applies all database migrations to your embedded SQLite database.
2. Initializes the default project for unauthenticated intake.
3. Launches the web server and live dashboard on `http://127.0.0.1:8000/`.

---

## 3. Database Configuration

### Default: Zero-Config SQLite
By default, the package creates and manages an embedded SQLite database in your working directory (`db.sqlite3`):
```bash
# Optional: Change the location of your SQLite file
export SQLITE_PATH=/var/data/notifier_service.db
notifier-service
```

### Switch to PostgreSQL
To switch to PostgreSQL, set `DB_ENGINE=postgres` (or `USE_POSTGRES=True`):
```bash
export DB_ENGINE=postgres
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=notifier_db
export DB_USER=postgres
export DB_PASSWORD=your_password

notifier-service migrate
notifier-service
```

### Switch to MySQL
```bash
export DB_ENGINE=mysql
export DB_HOST=localhost
export DB_PORT=3306
export DB_NAME=notifier_db
export DB_USER=root
export DB_PASSWORD=your_password

notifier-service migrate
notifier-service
```

---

## 4. Zero-Authentication Open Access

Authentication is completely optional. Out-of-the-box, any microservice, script, or developer can send alerts without needing to create user accounts or pass credentials.

### Send an Alert Instantly (No Auth Required)
```bash
curl -X POST http://127.0.0.1:8000/api/v1/notifications/notify/ \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Payment Microservice Outage",
    "message": "Connection refused to payment gateway after 3 retries",
    "severity": "CRITICAL",
    "service_name": "checkout-service",
    "error_type": "ConnectionRefusedError",
    "traceback": "Traceback (most recent call last):\n  File \"checkout.py\", line 45"
  }'
```

**Response (HTTP 202 Accepted):**
```json
{
  "status": "PENDING",
  "notification_id": "6b71fdfe-2f7b-4880-918b-c078f7c5d34f",
  "action": "queued_for_delivery",
  "queued_for_delivery": true,
  "occurrence_count": 1,
  "created_at": "2026-11-09T07:47:16.844674Z"
}
```

### Optional: Using API Keys for Multi-Project Isolation
If you manage multiple projects or teams and want isolated API keys:
1. Create a project: `POST /api/v1/projects/projects/`
2. Generate an API Key: `POST /api/v1/projects/api-keys/`
3. Pass `X-API-Key: ntf_YOUR_KEY` in the request header.

---

## 5. Live Dashboard & History

- **Interactive Web Dashboard**: Navigate to `http://127.0.0.1:8000/` in any browser to see total notifications, critical error counts, error hotspots by server/project, and delivery success rates.
- **REST Stats Endpoint**: `GET /api/v1/dashboard/stats/`
- **History & Search**: `GET /api/v1/notifications/history/?search=ConnectionRefused`
- **Export Data**: `GET /api/v1/notifications/history/export/?format=csv`

---

## 6. PyPI Publication Guide

The package distributions have been built and verified in the `dist/` directory:
- Source distribution: `dist/notifier_service_hub-1.0.0.tar.gz`
- Binary wheel: `dist/notifier_service_hub-1.0.0-py3-none-any.whl`

### Validation Status
```bash
twine check dist/*
# Checking dist/notifier_service_hub-1.0.0-py3-none-any.whl: PASSED
# Checking dist/notifier_service_hub-1.0.0.tar.gz: PASSED
```

### Step 1: Obtain a PyPI API Token
1. Log in to [pypi.org](https://pypi.org/).
2. Go to **Account Settings** -> **API tokens**.
3. Create a token with "Entire account" or "Project" scope and copy the token (`pypi-AgEI...`).

### Step 2: Publish using Twine
Run either:

#### Option A: Interactive prompt
```bash
python3 -m twine upload dist/*
# Username: __token__
# Password: <paste your pypi-... token>
```

#### Option B: Using environment variables
```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-YOUR_TOKEN_HERE
python3 -m twine upload dist/*
```

#### Option C: Test on TestPyPI first (Recommended)
```bash
python3 -m twine upload --repository testpypi dist/*
```

### Step 3: Verify Installation from PyPI
Once uploaded:
```bash
pip install notifier-service-hub
notifier-service
```
