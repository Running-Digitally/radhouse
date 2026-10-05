# Radhouse

A private web assistant on your own infrastructure.

The current first slice is deliberately small: sign in, talk to one Hermes
assistant, close the browser, and return to the same conversation. Use the
existing Warp connection for private access.

The new app is `radhouse.chat`, independent of the earlier platform composition.
It reuses local password/TOTP authentication and the pinned Hermes HTTP client.
It saves the displayed transcript and pending reply receipt in one private SQLite
file. New original attachments are streamed to a private directory beside it. A small observer within the web process saves the reply even while the
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
Audio originals can be sent without transcription; their cards say they have not been read. The adapter follows no
redirects and does not inherit proxy settings. It adds no VM or model runtime.

Run one web worker: message preparation is serialized within that process.
The parent data directory must already exist. Keep the transcript path stable
across releases, retain both the SQLite file and its `<transcript_path>.files`
directory on rollback, and back them up together. The first start upgrades
schema-1/2 chat files to schema 3 while retaining messages, legacy BLOB originals,
saved sessions, frozen inputs and run receipts. Keep a compatible reader on rollback;
previous binaries refuse schema 3. Do not replace the transcript with an older
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
in this browser's IndexedDB as binary files. Sent originals remain downloadable
after reload or restart. Clearing browser storage removes unsent drafts. Signing
out clears their display, not their local storage. Use a trusted browser for this
private application.

There is no configured file-size, aggregate-size or file-count ceiling. The browser
streams raw file uploads, receives immutable owner-scoped file IDs, then sends a
small message containing those references. Checksums bind upload retries to the
same bytes; an upload receipt recovers a lost acknowledgement without retransmission.
Available disk space and browser storage still determine whether a transfer can
complete. Interrupted uploads publish no partial-file receipt. A process crash can
leave unpublished temporary or original files; no automatic pruning is installed.

Original storage and assistant reading are separate. Small PNG/JPEG/WebP images
can use the pinned Hermes inline-image transport. UTF-8 text, searchable PDF and
DOCX/XLSX/PPTX have an automatic text reading; optional STT can transcribe audio.
Unknown binary formats, encrypted/scanned PDFs, extra or large images, and files
whose reader fails remain saved. Their cards distinguish a provided excerpt or
transcript from an original that was not read. Spreadsheet formulas are shown
with cached values, never evaluated. Document layout/images are not interpreted;
macros are never run and external references are not followed.

Automatic reading still has time, resource and excerpt budgets. The current
inline-image client allows four images of up to 4 MiB each and 8 MiB combined;
these constrain which images are provided to this run, **not which files can be
uploaded**. The prepared prompt and reading outcome are frozen for retries.

The current assistant connection still disables tools and does not provide
arbitrary incoming-file handoff. Stored originals prepare for selective agent
reading, but the agent cannot open them yet. That requires a separately reviewed
file-access contract and qualification against the existing runtime. Upload size
is no longer coupled to context length.

Downloads require the same signed-in owner. Images/audio support streaming range
requests; other originals are forced downloads with content sniffing disabled.

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
