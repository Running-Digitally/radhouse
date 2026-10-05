# Radhouse

A private web assistant on your own infrastructure.

The current first slice is deliberately small: sign in, talk to one Hermes
assistant, close the browser, and return to the same conversation. Use the
existing Warp connection for private access.

The new app is `radhouse.chat`, independent of the earlier platform composition.
It reuses local password/TOTP authentication and the pinned Hermes HTTP client.
It saves the displayed transcript and pending reply receipt in one private SQLite
file. A small observer within the web process saves the reply even while the
browser is closed; it only checks existing runs and never submits messages.
Hermes owns the assistant's persistent session context and memory.

**Status:** local source implementation with synthetic runtime verification.
Real model behavior and deployment remain to be qualified. The earlier fleet,
Buzz integration, work/task engine and software delivery code are retained for
history and recovery. They are excluded from this app and are not first-release
requirements. The current [roadmap](ROADMAP.md) and [principles](PRINCIPLES.md)
replace their previous product scope.

## Run the small app

Use the existing pinned Python dependencies; the app adds none. Provide a private
mode-0600 JSON configuration file with these exact fields. The values below are
placeholders, not working credentials:

```json
{
  "auth_dsn": "<existing local-auth PostgreSQL connection>",
  "auth_database": "<exact existing database name>",
  "deployment_id": "<existing deployment marker>",
  "auth_encryption_key": "<existing local-auth Fernet key>",
  "origin": "https://<existing private web hostname>",
  "owner_id": "<existing owner principal ID>",
  "hermes_endpoint": "https://<pinned private Hermes endpoint>",
  "hermes_bearer": "<existing API bearer key>",
  "transcript_path": "/<persistent private application data>/chat.sqlite3"
}
```

The parent data directory must already exist. Keep the transcript path stable
across releases, retain its data on rollback, and include it in the backup plan.
Startup verifies the exact existing authentication database, deployment marker,
schema version 7 and migration digest. It does not provision users or migrate
PostgreSQL. Do not start this version against a divergent or newer schema.

The intended listener is loopback behind the existing private ingress, which
owns HTTPS and Warp access:

```sh
RADHOUSE_CHAT_CONFIG=/absolute/private/chat.json \
  uvicorn radhouse.chat.main:app_factory --factory --host 127.0.0.1 --port 8090
```

Use this entry point for the new assistant; the older `radhouse` CLI still belongs
to the retained platform. Do not alter a live ingress, service, database or
runtime simply to run the source proof. The actual placement and activation
remain a separate reviewed change.

## Verify locally

```sh
PYTHONPATH=src:. python -m pytest -q tests/test_minimal_chat.py
node --check src/radhouse/chat/static/chat.js
```

`tests/test_minimal_chat_postgres.py` also exercises the real login service and
Chromium against an exclusively owned disposable PostgreSQL fixture. It uses a
synthetic Hermes transport, never a provider. The fixture runner's ownership,
identity and cleanup contract in `scripts/vs0.py` applies. Passing these checks
does not prove live Hermes session continuity or model usefulness.
