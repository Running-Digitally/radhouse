# Radhouse

A private web assistant on your own infrastructure.

The current first slice is deliberately small: sign in, talk to one Hermes
assistant, close the browser, and return to the same conversation. Use the
existing Warp connection for private access.

The new app is `radhouse.chat`, independent of the earlier platform composition.
It reuses local password/TOTP authentication and the pinned Hermes HTTP client.
It saves the displayed transcript and pending reply receipt in one private SQLite
file, including original attachments. A small observer within the web process saves the reply even while the
browser is closed; it only checks existing runs and never submits messages.
Hermes owns the assistant's persistent session context and memory.

**Status:** local source implementation with synthetic runtime verification.
Real model behavior and deployment remain to be qualified. The earlier fleet,
Buzz integration, work/task engine and software delivery code are retained for
history and recovery. They are excluded from this app and are not first-release
requirements. The current [roadmap](ROADMAP.md) and [principles](PRINCIPLES.md)
replace their previous product scope.

## Run the small app

Use the pinned Python dependencies, including `pypdf` for local PDF extraction.
Provide a private mode-0600 JSON configuration file with these required fields. The values below are
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

Optional `transcription_endpoint` selects an existing OpenAI-compatible
`/v1/audio/transcriptions` service; optional `transcription_bearer` belongs only to
that endpoint. Leave both absent until the service connection is qualified.
Audio fails clearly when transcription is not configured. The adapter follows no
redirects and does not inherit proxy settings. It adds no VM or model runtime.

Run one web worker: message preparation is serialized within that process.
The parent data directory must already exist. Keep the transcript path stable
across releases, retain its data on rollback, and include it in the backup plan.
The first start upgrades a schema-1 chat file to schema 2 while retaining all
messages, saved sessions and run receipts. Keep the compatible reader on rollback;
the previous binary refuses schema 2. Do not replace the transcript with an older
copy and lose newer messages. Startup verifies the exact existing authentication database, deployment marker,
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

## Attach files

Paste images or clipboard files, drag files into the composer, or use **Attach**.
Inspect the thumbnails, file names and audio controls; remove any file before
sending. Sending files without message text is supported. Unsent drafts are saved
in this browser's IndexedDB; sent originals and audio transcripts live in the
private chat file and remain available after reload or restart. Clearing browser
storage removes unsent drafts. Signing out clears their display, not their local
storage. Use a trusted browser for this private application.

Supported files:

- PNG, JPEG and WebP images, passed through Hermes' existing image input.
- UTF-8 text/code files, searchable PDFs, and DOCX, XLSX and PPTX documents.
  The assistant receives extracted text. Spreadsheet formulas are shown with
  cached values and never evaluated; document images/layout are not interpreted.
- WAV, MP3, M4A, OGG, FLAC and WebM audio, transcribed by the configured existing
  service. The assistant receives the saved transcript, not sound analysis.

Use up to four files: 4 MiB per image, 8 MiB of images total, 20 MiB per document or
audio file, and 24 MiB combined. Extracted text/transcripts are limited to 128 KiB
combined per message. Originals require the same signed-in owner to download;
images and audio can be previewed. Text documents are always served as downloads.

Scanned PDFs need OCR or individual page images; encrypted PDFs and legacy
DOC/XLS/PPT or macro-enabled Office files are refused clearly. Parsing runs in a
bounded child process without running macros or following external references.
A saved message's text, file order, names and bytes cannot change on retry. Its
prepared input is frozen before the Hermes request, including cached transcripts.

## Verify locally

```sh
PYTHONPATH=src:. python -m pytest -q tests/test_minimal_chat.py tests/test_chat_attachments.py
node --check src/radhouse/chat/static/chat.js
```

`tests/test_minimal_chat_postgres.py` also exercises the real login service and
Chromium against an exclusively owned disposable PostgreSQL fixture. It uses a
synthetic Hermes and transcription transports, never a provider. It checks file
picking, dropping, removal, draft reload, image/PDF/audio sending and original
downloads as well as conversation recovery. The fixture runner's ownership,
identity and cleanup contract in `scripts/vs0.py` applies. Passing these checks
does not prove live Hermes session continuity or model usefulness.
