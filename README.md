<<<<<<< HEAD
# Notifier Service

A production-grade, reliable multi-channel notification and alert dispatching service built with **Python 3.12+**, **Django 5 / REST Framework**, **Celery**, **Redis**, and **PostgreSQL**.

Designed to handle high-throughput application error alerts and notifications across development, staging, and production without ever blocking client applications.

---

## Features

### 1. 📊 Real-Time Dashboard
- **Total Notifications**: Aggregated counts (all-time, last 24h, last 7 days).
- **Critical Errors**: Real-time counter of critical errors and unresolved criticals.
- **Errors by Project and Server**: Breakdown of error hotspots across microservices and servers.
- **Delivery Success / Failure Rates**: Real-time percentage success rates and per-channel breakdown.
- **Recent Activity Feed**: Real-time event log with severity badges and triage statuses.
- **Interactive UI**: Web dashboard available at `/` and programmatic REST stats at `/api/v1/dashboard/stats/`.

### 2. 📁 Project & Environment Management
- **Multi-Project Support**: Manage independent projects across `development`, `staging`, and `production`.
- **API Key Lifecycle**:
  - Secure SHA-256 hashed storage with unique key prefixes (`ntf_xxxxxxxx_...`).
  - Seamless generation, instant rotation, and one-click revocation.
- **Server Registration**: Register multiple servers and instances per project with hostname, IP, and heartbeat tracking.

### 3. 🔔 Notification Management & Ingestion
- **Standardized Severities**: `CRITICAL`, `ERROR`, `WARNING`, `INFO`, and `SUCCESS`.
- **Reusable Notification Templates**: Define templated alert formats with dynamic context variable substitution (`{server}`, `{service}`, `{error_type}`).
- **Custom Notification Routing**: Route alerts to specific channels using regex patterns on service names or titles with priority ordering.
- **Severity-to-Channel Matrix**: Configure which channels receive which severities (e.g., `CRITICAL` triggers SMS/WhatsApp/Telegram; `INFO` sends email only).
- **Duplicate Detection**: SHA-256 content hashing with sliding dedup windows (e.g. 5 minutes) suppresses redundant alerts.
- **Intelligent Grouping**: Automatically collapses rapid repetitive errors (e.g. same service + error type within 60s) into a parent record with an incrementing `occurrence_count`.
- **Rate Limiting**: Per-project sliding window rate limits (e.g. 100/minute) enforced in Redis.

### 4. 📡 Multi-Channel Delivery
- **Email (SMTP)**: Multi-recipient plain-text and HTML formatting with TLS/SSL.
- **Telegram Bot API**: Instant messages to multiple chat/channel IDs with HTML or Markdown formatting.
- **WhatsApp Cloud API**: Official Meta Graph API integration with international E.164 phone numbers.
- **Instagram Messaging API**: Graph API integration with Instagram-scoped user IDs.
- **Test Connection Tool**: Dedicated test connection endpoints (`POST /api/v1/channels/{channel}/{id}/test_connection/`) to verify credentials before going live.
- **Per-Channel Delivery History**: Individual status (`PENDING`, `DELIVERED`, `FAILED`, `RETRYING`) logged for each recipient.

### 5. 📜 History, Search & Error Triage
- **Fast Search & Filtering**: Query by project, server, service name, severity, status, and custom date ranges (`?start_date=&end_date=`).
- **Full Traceback Viewer**: Complete error stack traces and arbitrary JSON context payloads.
- **Triage Workflow**:
  - Acknowledge notifications (`POST /api/v1/notifications/history/{id}/acknowledge/`).
  - Resolve notifications with resolution notes (`POST /api/v1/notifications/history/{id}/resolve/`).
- **Data Export**: One-click export to **CSV** or **JSON** formats (`/api/v1/notifications/history/export/?format=csv`).

### 6. 🛡️ Reliability & Fault Tolerance
- **Non-Blocking Ingestion**: Ingest endpoint (`POST /api/v1/notifications/notify/`) returns `202 Accepted` immediately, offloading delivery to Celery.
- **Idempotency**: Client-provided `idempotency_key` ensures exactly-once intake during network re-transmissions.
- **Exponential Backoff Retries**: Automatic retries on transient delivery errors (60s base backoff, up to 3 retries).
- **Dead-Letter Queue (DLQ)**: Deliveries that exhaust retries are placed in the dead-letter queue with the full payload and failure reason.
- **Reprocessing**: Reprocess DLQ items with one click via API (`POST /api/v1/delivery/dead-letter/{id}/reprocess/`).

---

## Architecture Overview

```mermaid
flowchart TD
    ClientApp["Client Application (Django, Flask, Node, Go)"] -->|POST /api/v1/notifications/notify/ (X-API-Key)| API["Django REST Framework API"]
    
    subgraph IngestionPipeline["Ingestion Pipeline"]
        API --> Idem["1. Idempotency Check"]
        Idem --> Rate["2. Redis Rate Limiter"]
        Rate --> Dedup["3. SHA256 Duplicate Filter"]
        Dedup --> Group["4. Event Grouping Engine"]
        Group --> DB[(PostgreSQL / SQLite)]
    end

    Group -->|enqueue non-blocking| RedisQueue["Redis Message Broker"]
    RedisQueue --> CeleryWorker["Celery Delivery Worker"]
    
    subgraph Channels["Delivery Dispatchers"]
        CeleryWorker --> SMTP["Email (SMTP)"]
        CeleryWorker --> TG["Telegram Bot API"]
        CeleryWorker --> WA["WhatsApp Cloud API"]
        CeleryWorker --> IG["Instagram Graph API"]
    end

    Channels -->|Failed after retries| DLQ["Dead-Letter Queue (DLQ)"]
```

---

## Quickstart

### Prerequisites
- Python 3.12+ (or 3.10+)
- Redis running on `localhost:6379`
- (Optional) Docker & Docker Compose

### 1. Local Setup
```bash
# Clone and enter directory
cd /home/moin/Projects/notifier_service

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Seed sample data (creates admin user, demo project, API keys, channels, alerts)
python manage.py seed_data
```

### 2. Start the Services
In terminal 1 (Web Server):
```bash
python manage.py runserver 0.0.0.0:8000
```

In terminal 2 (Celery Background Worker):
```bash
celery -A config worker --loglevel=info
```

Open your browser at:
- **Interactive Dashboard**: `http://localhost:8000/`
- **Django Admin**: `http://localhost:8000/admin/` (Login: `admin` / `admin123`)
- **API Root**: `http://localhost:8000/api/v1/`

---

## Docker Compose Setup

Run the entire stack (PostgreSQL 16, Redis 7, Web server, and Celery worker) with one command:

```bash
docker compose up --build
```

---

## API Usage Guide

### Ingesting an Alert (Client Application)
Include your API key in the `X-API-Key` header:

```bash
curl -X POST http://localhost:8000/api/v1/notifications/notify/ \
  -H "X-API-Key: ntf_YOUR_KEY_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Payment Gateway Timeout",
    "message": "Stripe endpoint timed out after 30000ms",
    "severity": "CRITICAL",
    "service_name": "checkout-api",
    "server_hostname": "api-gw-01.us-east-1",
    "error_type": "TimeoutException",
    "traceback": "Traceback (most recent call last):\n  File \"payment.py\", line 84",
    "context": {
      "order_id": 99482,
      "amount": 149.99
    },
    "idempotency_key": "unique-payment-err-99482"
  }'
```

**Response (HTTP 202 Accepted):**
```json
{
  "status": "PENDING",
  "notification_id": "7fa84d1e-250d-4592-8051-92b8d030c6a8",
  "action": "queued_for_delivery",
  "queued_for_delivery": true,
  "occurrence_count": 1,
  "created_at": "2026-11-09T07:23:00Z"
}
```

---

### Rotating an API Key
```bash
curl -X POST http://localhost:8000/api/v1/projects/api-keys/{id}/rotate/ \
  -H "Authorization: Basic YWRtaW46YWRtaW4xMjM=" \
  -H "Content-Type: application/json" \
  -d '{"new_name": "Rotated Key"}'
```

---

### Testing Channel Connectivity
```bash
curl -X POST http://localhost:8000/api/v1/channels/email/{id}/test_connection/ \
  -H "Authorization: Basic YWRtaW46YWRtaW4xMjM="
```

---

### Acknowledging and Resolving an Alert
```bash
# Acknowledge
curl -X POST http://localhost:8000/api/v1/notifications/history/{id}/acknowledge/ \
  -H "Authorization: Basic YWRtaW46YWRtaW4xMjM="

# Resolve with note
curl -X POST http://localhost:8000/api/v1/notifications/history/{id}/resolve/ \
  -H "Authorization: Basic YWRtaW46YWRtaW4xMjM=" \
  -H "Content-Type: application/json" \
  -d '{"note": "Mitigated: Increased connection pool size to 500."}'
```

---

### Exporting Records
```bash
# Export filtered records to CSV
curl -O -J "http://localhost:8000/api/v1/notifications/history/export/?format=csv&severity=CRITICAL" \
  -H "Authorization: Basic YWRtaW46YWRtaW4xMjM="

# Export to JSON
curl -O -J "http://localhost:8000/api/v1/notifications/history/export/?format=json" \
  -H "Authorization: Basic YWRtaW46YWRtaW4xMjM="
```

---

## Running the Automated Test Suite

```bash
python manage.py test tests
```
Output:
```
Ran 13 tests in 2.266s
OK
```
All unit and integration tests verify project management, channel configurations, deduping, grouping, rate limiting, triage, exports, and DLQ retries.
=======
# notifier-pacakge
>>>>>>> 26e8849424b91a1ca69b3cbd284b6353b46c2de8
