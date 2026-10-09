# Radhouse roadmap

## First release: one private web conversation

Acceptance: **I open Radhouse, talk to my assistant, close the browser, and return
later to the same conversation.**

The owner's private pilot is deployed. Its qualification applies to that pinned
runtime; another installation must qualify its own connections before activation.

1. **Delivered:** the small `radhouse.chat` app: existing password/TOTP sign-in, one
   stable Hermes session, readable history, streamed original attachments without
   application size/count caps, optional bounded readings, pending
   reply recovery and clear errors.
2. **Verified locally:** the browser journey, auth boundary and retry behavior with
   synthetic Hermes and an owned disposable authentication database. The local UI
   now includes a persistent composer, separate outgoing/next drafts, compact
   files, long-paste preservation, upload progress, formatted answers and recovery.
3. **Qualified in the private pilot:** real replies and restart continuity,
   selective reads from large PDF/DOCX originals with citations and follow-ups,
   and streamed views of the same browser the assistant uses. The reviewed
   saved-file handoff contract is active; upload size is independent of context
   length. Searchable PDF and DOCX/XLSX/PPTX text are supported. The owner also
   confirmed that a 50 MB PDF and browser check worked as expected.
4. **Active:** the private web app behind the existing Warp access, with read-only
   Settings and Infrastructure pages. Browser Hide/Show changes the view while
   the assistant keeps control. Further infrastructure retirement still requires
   verified dependencies and explicit data disposition.

Scanned-document OCR, audio transcription and editable infrastructure
administration remain future work. Image understanding needs its own recorded
real-runtime qualification. Incremental assistant reply streaming and a
trustworthy Stop action also need qualification before exposure; current replies
arrive on completion. The live browser view streams independently of reply text.

The earlier durable-work source and design are preserved for history and
recovery. They are outside the first-release critical path. Buzz integration is
removed from the product direction.

## After the first release

Use the assistant and identify one concrete missing capability at a time. Memory
correction, useful tools, routines, delegation and software delivery are possible
later slices. None is required to release the basic conversation, and no standing
fleet or new service is assumed for them.

The current release branch includes deliberate human takeover and the native
login vault, Terminal, About You and saved agent identity/appearance. The
address/search and follow-ups source slice adds saved search preferences, local
destination suggestions and durable ordered messages during an active reply.
Its qualification covers synthetic desktop/mobile journeys and pinned native
contracts; live activation remains a separate release decision. See the
[slice contract](docs/design/browser-followups.md).
