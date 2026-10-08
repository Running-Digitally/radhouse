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

**Status:** deployed private pilot. Real conversation and restart continuity,
selective reads from large PDF/DOCX originals with follow-up citations, and the
assistant's live browser view have been qualified against the pinned Hermes
runtime. The owner also confirmed that a 50 MB PDF and browser check worked as
expected. This is evidence for the private pilot, not qualification of every
self-hosted installation or model.

The pilot supports selective access to searchable PDF and DOCX/XLSX/PPTX text,
a live view of the same browser the assistant uses, and read-only **Settings**
and **Infrastructure** pages. **Hide/Show** changes the browser view; the assistant
keeps mouse and keyboard control. Human takeover, scanned-document OCR, audio
transcription and editable administration settings have not been activated in
that deployed pilot.

**Next release source:** Browser can open before any chat. Its launcher starts
no Chromium process until **Open browser** is clicked. The owner can navigate,
take control while the assistant finishes its reply, and **Return to agent**
after that reply ends. **Close browser** ends the native process; only a clearly
labelled previous-page reference remains. Sharing a page adds its brief locator
and title to a real chat turn, with further reading through browser tools.

Saved logins reuse the local Hermes credential vault. Explicit save/remove and
exact-origin fill stay within the owned browser. Login tools return metadata and
fill outcomes; credential form inputs are not saved in chat. This requires the
qualified Hermes v0.21.6 private session-control API and its separate Python 3.14
environment. Local native and
UI proofs have passed; Linux browser/sandbox qualification and production
activation remain deployment steps. Retain the paired old-runtime schema-31
compatibility patch for rollback; an unchanged old runtime can delete upgraded
tool-definition blobs during ordinary prompt cleanup. Preserve newer chats and
the separate vault rather than restoring an older database.

The earlier fleet, Buzz integration, work/task engine and software delivery code
are retained for history and recovery. They are excluded from this app. The
current [roadmap](ROADMAP.md) and [principles](PRINCIPLES.md) replace their previous
product scope.

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
  "transcript_path": "/<persistent private application data>/chat.sqlite3",
  "document_access_enabled": false,
  "browser_enabled": false
}
```

`document_access_enabled` and `browser_enabled` are optional booleans, both
defaulting to `false`. After qualifying the matching Hermes private API, set the
document flag to `true` for owner/session-scoped saved-file reads, and the browser
flag to `true` for Browser. The API must advertise the restricted-tool capability
plus the corresponding document or browser capabilities. This source uses the
qualified owner-session API for opening and controlling the browser; saved-login
operations additionally require its qualified vault capability. Pair this app
with that API; rolling back to a view-only gateway also requires the retained
compatible app. Enabling a flag cannot supply a missing runtime
capability; unavailable operations fail closed. Web startup and sign-in do not
depend on the agent being reachable. Both flags are enabled in the existing
pilot, whose older runtime still provides only its qualified live view.

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
to the retained platform. For another installation, a local source proof does
not authorize changes to a live ingress, service, database or runtime. Qualify
that installation's runtime and review its placement and activation separately.
The owner's private pilot has completed those qualification and activation steps.

## Attach files

Paste images or clipboard files, drag files into the composer, or use **Attach**.
Inspect compact thumbnails and document icons; expand audio playback or transcripts
when needed. Sent messages show the first three files with the rest one click away.
Remove any draft file before
sending. Sending files without message text is supported. Unsent drafts are saved
in this browser's IndexedDB as binary files. Sent originals remain downloadable
after reload or restart. Clearing browser storage removes unsent drafts. Signing
out clears their display, not their local storage. Use a trusted browser for this
private application.

The composer stays visible while you read. Opening the conversation resumes at
the latest message; **Latest** returns there when you scroll back. Loading earlier
messages preserves your reading position. Replies show paragraphs, lists, safe
links and code with copy controls; source HTML remains literal text.

Sending moves the message into the conversation immediately. You can write and
attach files to your next draft during upload or reply; it is kept separately from
the outgoing request. Byte progress describes the upload, not assistant reading.
An uncertain delivery keeps the same request ID for recovery. In-place retry and,
when transmission has not happened, editing preserve the message and files.
Signing in again restores the outgoing request and the separate next draft.

Long pasted text is never truncated by the input. Above the message endpoint's
16,000-character text contract, **Attach as text file** explicitly saves the whole
paste as a UTF-8 original. It is not silently shortened or automatically sent.

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

The qualified private pilot enables the reviewed saved-file access contract.
With `document_access_enabled` and the matching Hermes private API capability,
the assistant can list saved turn files, search their text and read selected
pages or document ranges, including earlier attachments in follow-up turns.
Run/session ownership checks scope those reads to the conversation; an attachment
does not automatically become the entire prompt. Installations must qualify the
matching runtime before enabling this connection. Upload size is independent
of context length.

Downloads require the same signed-in owner. Images/audio support streaming range
requests; other originals are forced downloads with content sniffing disabled.

## Verify locally

For security and code-quality analysis after a merge, run the
[local SonarQube launcher](docs/sonarqube.md) on the development laptop. It tests and scans
a clean copy of remote `main` and waits for the quality gate.

```sh
PYTHONPATH=src:. python -m pytest -q tests/test_minimal_chat.py tests/test_chat_attachments.py
node --check src/radhouse/chat/static/chat.js
node --check src/radhouse/chat/static/format.js
```

`tests/test_minimal_chat_postgres.py` also exercises the real login service and
Chromium against an exclusively owned disposable PostgreSQL fixture. It uses a
synthetic Hermes and transcription transports, never a provider. It checks file
picking, dropping, removal, binary draft reload, image/PDF/audio sending, exact
original downloads, long-paste conversion, safe formatting/copy, a separate next
draft during sending, session-expiry recovery, pagination anchors, latest scroll
and a mobile composer as well as conversation recovery. The fixture runner's ownership,
identity and cleanup contract in `scripts/vs0.py` applies. Passing these checks
does not prove live Hermes session continuity or model usefulness.
