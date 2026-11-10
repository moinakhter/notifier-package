# Notifier Service Hub

[![PyPI version](https://img.shields.io/pypi/v/notifier-service-hub.svg)](https://pypi.org/project/notifier-service-hub/)
[![Python versions](https://img.shields.io/pypi/pyversions/notifier-service-hub.svg)](https://pypi.org/project/notifier-service-hub/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A free, open-source, high-throughput, multi-channel notification and error alert dispatching engine. Built with **Django 5 / REST Framework**, **Celery**, and **SQLite (with WAL mode by default)** or **PostgreSQL / MySQL**.

Designed to absorb **hundreds of thousands of logs per second** across distributed microservices and servers without ever blocking your application threads, while giving you complete control over **which errors trigger alerts**.

---

## 🚀 Key Highlights

- **Embedded SQLite by Default**: Zero setup. Runs immediately out-of-the-box without configuring external databases.
- **High-Throughput Concurrency (Benchmarked)**:
  - **500,000+ logs/second** in-memory client absorption rate (`0.0007 ms` median call latency).
  - **9,000+ logs/second** server database write rate via bulk batch ingestion (`/api/v1/notifications/batch/`).
  - Automatic SQLite **WAL (Write-Ahead Logging)** mode with 15s busy timeout: **zero database lock contention** under heavy multi-server traffic spikes.
- **Automated Log Retention (Default: 15 Days)**:
  - Automatically prunes old notification logs and delivery attempts older than 15 days via scheduled Celery beat tasks or CLI.
  - Fully configurable per project in the settings UI (`/settings/`) or REST API. Set to `0` to keep logs indefinitely.
- **Customizable Error Alert Preferences**:
  - **Only Alert on Actual Exceptions**: Filter out informational messages; only send emails/telegrams when an actual uncaught exception or traceback occurs.
  - **Severity Channel Matrix**: Selectively route `CRITICAL`, `ERROR`, `WARNING`, `INFO`, and `SUCCESS` to specific channels (Email, Telegram, WhatsApp, Instagram).
  - Warnings and info logs are stored silently in database history without buzzing your phone or inbox.
- **Zero-Authentication by Default**: Anyone can send alerts and access the dashboard immediately without API keys or passwords (optional API keys are supported).
- **Multi-Server & Multi-Project Auto-Discovery**:
  - Multiple services across different servers can connect to the **same central database** at the same time.
  - Projects and servers are automatically registered upon receiving their first alert.
- **Interactive Multi-Criteria Log Filtering & Explorer**:
  - Filter logs live on the dashboard by **Project**, **Server**, **Severity** (`CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`, `SUCCESS`), and **Keyword Search**.
  - **Logs as per Project** tab: Aggregated metrics per project (total logs, error count, criticals, unresolved alerts) with 1-click filter links.
  - **Logs as per Server** tab: Aggregated metrics per remote server (hostname, project association, errors, total volume).
  - One-click filter links directly on project and server badges in the log stream.
- **Multi-Channel Delivery**: Built-in dispatchers for **Email (SMTP)**, **Telegram Bot API**, **WhatsApp Cloud API**, and **Instagram Graph API**.
- **Triage & History**: Web Dashboard, full traceback viewer, event grouping, duplicate detection, acknowledging, resolving, and CSV/JSON export.

---

## ⚡ Quickstart

### 1. Install & Launch the Central Hub
```bash
pip install notifier-service-hub

# Launch the central server with auto-migrations
notifier-service
```
Open your browser:
- **Interactive Dashboard**: `http://localhost:8000/`
- **Notification & Filter Settings**: `http://localhost:8000/settings/`
- **REST API**: `http://localhost:8000/api/v1/`
- **Django Admin**: `http://localhost:8000/admin/`

---

## 🎯 User-Controlled Error Log Filtering

By default, **WARNING**, **INFO**, and **SUCCESS** logs are recorded silently in history without dispatching emails or messaging alerts. Only **CRITICAL** and **ERROR** events alert you unless you customize them.

### Web Dashboard Settings UI (`/settings/`)
Visit `http://localhost:8000/settings/`:
1. **Select your Project** from the dropdown.
2. **Toggle "Only Alert on Actual Exceptions"**:
   - When enabled, channel alerts (Email, Telegram, WhatsApp) are **only** sent if the log contains an actual Python/application exception or error traceback. Clean logs without tracebacks will be silently recorded in history without spamming your inbox.
3. **Set Log Retention Period (Default: 15 Days)**:
   - Configure how many days logs are retained in the database before automatic daily pruning.
   - Click **"Prune Expired Logs Now"** to clean up instantly.
4. **Customize the Severity Matrix**:
   - Choose exactly which channels (Email, Telegram, WhatsApp, Instagram) are enabled for each level:
     - 🔴 **CRITICAL**: Fatal crashes & system outages
     - 🟠 **ERROR**: Caught exceptions & database/network failures
     - 🟡 **WARNING**: Slow queries, memory warnings (silent by default)
     - 🔵 **INFO**: Operational logs (silent by default)
     - 🟣 **DEBUG**: Detailed diagnostic logs & trace data (silent by default)
     - 🟢 **SUCCESS**: Deployments & backup confirmations (silent by default)
   - Uncheck all channels for any severity to mute it completely.
5. Click **"Save Notification Settings"** to apply instantly.

### In Python Code (Client-Side Filtering)
```python
from notifier_service.client import NotifierLoggingHandler

handler = NotifierLoggingHandler(
    endpoint="http://your-central-server:8000",
    project="Payment Gateway",
    notify_exceptions_only=True,                 # Only notify if record has exc_info / traceback
    allowed_severities=["ERROR", "CRITICAL"],   # Ignore WARNING and INFO
)
```

---

## 💻 Sending Notifications From Any Remote Server

### Method 1: Using `NotifierClient` (Microsecond Non-Blocking)
```python
from notifier_service.client import NotifierClient

client = NotifierClient(
    endpoint="http://your-central-server:8000",
    project="Payment Service",
    async_send=True,
    notify_exceptions_only=True,
)

# Send custom alert
client.notify(
    title="Payment Gateway Timeout",
    message="Stripe API did not respond within 30s",
    severity="CRITICAL",
)

# Automatically capture any uncaught exception with full stack trace
try:
    process_order()
except Exception as e:
    client.capture_exception(e)
```

### Method 2: Python Standard Logging Handler
Direct all logger records across your microservices to the central server:
```python
import logging
from notifier_service.client import NotifierLoggingHandler

handler = NotifierLoggingHandler(
    endpoint="http://your-central-server:8000",
    project="Storefront API",
    service_name="auth-worker",
    notify_exceptions_only=True,
)
logging.getLogger().addHandler(handler)

# Only actual exceptions will alert your inbox!
logging.error("Failed to connect to primary cache")
```

### Method 3: Remote Django Middleware
In your remote application's `settings.py`:
```python
MIDDLEWARE = [
    ...,
    'notifier_service.NotifierExceptionMiddleware',
]

NOTIFIER_SERVICE_URL = 'http://your-central-server:8000'
NOTIFIER_PROJECT_NAME = 'Storefront API'
```

### Method 4: High-Throughput Batch API (cURL / Any Language)
Absorb thousands of logs per second in bulk:
```bash
curl -X POST http://your-central-server:8000/api/v1/notifications/batch/ \
  -H "Content-Type: application/json" \
  -d '{
    "project": "Billing Service",
    "server_hostname": "prod-worker-01",
    "events": [
      {
        "title": "Database connection pool saturated",
        "severity": "CRITICAL",
        "error_type": "ConnectionPoolError",
        "traceback": "Traceback..."
      }
    ]
  }'
```

---

## 📊 Benchmarks

Tested on standard developer hardware with 20 concurrent threads and SQLite:

| Metric | Result | Description |
| :--- | :--- | :--- |
| **Client Emitting Rate** | **527,766 logs/sec** | Microsecond non-blocking queue (`0.0007 ms` median call latency) |
| **Server Batch Ingestion** | **9,066 logs/sec** | Bulk atomic transactions (`/api/v1/notifications/batch/`) |
| **Concurrent Write Stress** | **1,000 requests** | 100% success rate, **0 database lock errors** |
| **Concurrency Mode** | **SQLite WAL** | `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=15000` |

---

## 🗄️ Database Switching (PostgreSQL / MySQL)

By default, the service uses embedded SQLite. To connect to a shared PostgreSQL or MySQL instance:

```bash
# PostgreSQL
export DB_ENGINE=postgres
export DB_HOST=postgres.internal.net
export DB_NAME=notifier_db
export DB_USER=postgres
export DB_PASSWORD=mysecretpassword
notifier-service

# MySQL
export DB_ENGINE=mysql
export DB_HOST=mysql.internal.net
export DB_NAME=notifier_db
export DB_USER=root
export DB_PASSWORD=mysecretpassword
notifier-service
```

---

## 🧪 Testing

```bash
python manage.py test tests
```
All 19 unit and integration tests run in under 4 seconds.

---

## 📄 License

Distributed under the **MIT License**. Free for commercial and private use.
