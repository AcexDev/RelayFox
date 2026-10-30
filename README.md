# RelayFox

A webhook delivery service built with the Python standard library and SQLite. Clients post events, and RelayFox delivers them to the subscriber's registered URL with signing, retries, and crash recovery.

## Features

- Event ingestion over HTTP (`POST /events`)
- Durable storage in SQLite; the database is the source of truth
- Background workers with an in-memory queue
- HMAC-SHA256 request signing
- Retries with exponential backoff and jitter
- Delivery attempt history
- Crash recovery on startup
- Graceful shutdown
- Versioned SQL migrations

## Requirements

- Python 3.10+
- `httpx`, `python-dotenv`

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

## Running

```bash
python -m core.server
```

The server listens on `http://localhost:8000`. Migrations run automatically at startup.

### Configuration

Set in a `.env` file or the environment:

| Variable       | Default | Description                        |
|----------------|---------|------------------------------------|
| `WORKER_COUNT` | `2`     | Number of delivery worker threads  |
| `LOG_LEVEL`    | `INFO`  | Logging level                      |

## API

### `GET /`
Health check. Returns `{"Service": "RelayFox", "Status": "Active"}`.

### `POST /events`
Submit an event for delivery.

```json
{
  "subscriber_id": 1,
  "payload": {
    "user": { "id": 42, "email": "user@example.com" }
  }
}
```

| Status | Meaning                                  |
|--------|------------------------------------------|
| 202    | Accepted and queued                      |
| 400    | Invalid JSON or missing `subscriber_id`  |
| 404    | Unknown or disabled subscriber           |
| 411    | `Content-Length` header missing          |
| 413    | Body larger than 1 MB                    |
| 503    | Queue full (event is stored, retry later)|
| 500    | Internal error                           |

A successful response looks like `{"event_id": 7, "status": "queued"}`.

## How delivery works

1. The event is stored as `queued` and its ID is added to the in-memory queue.
2. A worker claims it (`processing`), looks up the subscriber's URL and secret, and POSTs the payload with a 5s timeout.
3. Every attempt is recorded in the `attempts` table.
4. The outcome decides what happens next:

| Result                                         | Outcome                              |
|------------------------------------------------|--------------------------------------|
| 2xx                                            | `delivered`                          |
| Timeout, network error, 5xx, 429               | `pending`, retried later             |
| Other 4xx                                      | `failed` (permanent, no retry)       |
| Retryable failure on the 5th attempt           | `failed`                             |

**Retry schedule** (plus up to 10% jitter): 10s, 30s, 2m, 10m, 1h. A scheduler thread re-queues events whose retry time has passed.

**Lifecycle:** `queued → processing → delivered`, or `processing → pending → processing → ... → failed`.

### Reliability

- **Crash recovery:** on startup, events left in `queued` or `processing` are reset to `pending` and re-delivered.
- **Atomic claim:** only one worker can take an event, so duplicate queue entries are skipped.
- **At-least-once delivery:** a receiver may occasionally get the same event twice. Use the event ID header to deduplicate.
- **Graceful shutdown:** Ctrl+C stops accepting requests and lets in-flight deliveries finish.

## Webhook format (for receivers)

Each delivery is a `POST` with the JSON payload as the body and these headers:

| Header                 | Description                                  |
|------------------------|----------------------------------------------|
| `X-RelayFox-Event-Id`  | Stable event ID, same across retries         |
| `X-RelayFox-Signature` | `sha256=` + HMAC-SHA256 of the raw body      |

Verify the signature against the **raw request bytes**, using the subscriber's secret:

```python
import hmac, hashlib

def verify(secret: str, raw_body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
```

## Local testing

1. Start a test receiver (port 9001 matches seeded subscriber 1):
   ```bash
   python receiver.py        # or: python receiver.py 9002
   ```
2. Start RelayFox: `python -m core.server`
3. Send an event:
   ```bash
   curl -X POST http://localhost:8000/events \
     -H "Content-Type: application/json" \
     -d '{"subscriber_id": 1, "payload": {"hello": "world"}}'
   ```
4. Inspect the results:
   ```sql
   SELECT id, status, next_attempt_at FROM events;
   SELECT * FROM attempts;
   ```

To test retries, stop the receiver and send another event.

## Migrations

SQL files in `core/migrations/` run in filename order at startup. Applied versions are tracked in the `schema_migrations` table. Never edit a migration that has already run; add a new one instead.

> **Note:** `0003_seed_subscribers.sql` inserts five development subscribers with fake secrets and localhost URLs (subscriber 5 is disabled). It is for development only.

## Project structure

```
core/
  server.py          HTTP server, ingestion, startup and shutdown
  worker.py          queue, workers, delivery, retries, scheduler, recovery
  schema.py          database connection
  migrations.py      migration runner
  logging_config.py  logging setup
  migrations/        numbered .sql migrations
receiver.py          local test receiver
```

## Roadmap

- [ ] `POST /subscribers` registration, with URL validation
- [ ] `GET /events/<id>` status endpoint
- [ ] Move seed data to `scripts/seed.py`
- [ ] Tests for `classify` and `build_request`