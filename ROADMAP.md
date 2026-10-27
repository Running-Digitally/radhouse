# Radhouse roadmap

This is the public capability and engineering roadmap. Commercial hypotheses,
pricing and packaging live in the private venture record and reference this
backlog. See [ADR-0007](docs/decisions/0007-public-engineering-private-commercial-strategy.md).

## Next proposed direction: durable assistant, replaceable compute

The 2026-10-21 [architecture proposal](docs/design/durable-assistant-workspaces.md)
retains the assistant's chat, files, native state and browser profile while
allowing workers and task computers to be replaced. It preserves one Library,
ordinary browser file transfers and meaningful Private takeover. Arbitrary shell
execution stays separate from the credentialed browser.

The [development roadmap](docs/plans/2026-10-21-durable-workspace-roadmap.md)
defines DW-0 through DW-7 and their acceptance evidence. The October 25
[Hermes gap check](docs/research/hermes-continuity-gap-check.md) confirms native
session loading, memory and backup/import are available, and the chat app already
persists session/run identities, frozen inputs and ordered follow-ups.

The [controlled replacement slice](docs/design/controlled-worker-replacement.md)
now provides a persistent admission hold, replacement on the current host,
native-state reattachment and verified recovery packaging. The owner pilot
preserved conversation context, memory and originals, reconciled cancellation
and worker loss without replay, and restored the packaged native/Radhouse stores
into isolated targets. Native import runs inside an offline supervisor boundary
because the pinned command can otherwise start a gateway.

In progress: [browser/Library transfers (DW-2)](docs/design/browser-library-transfers.md).
The candidate is implemented and undergoing installed acceptance. The browser
retirement fix, human uploads/downloads, Private defaults and explicit sharing
have passed; a native callback parser correction must pass agent transfers before delivery.
Retained browser profiles (DW-3) follow with their own contract.
Off-host recovery custody, replacement-host boot and
on-demand placement remain separate from this same-host operator slice. Helpers,
schedules and optional browser import follow later. Memory snapshots and a
runtime comparison do not block this work.

The owner-authorized [browser-first SPACE slice](docs/design/space-browser-pilot.md)
is deployed in the private pilot after real guest/recovery, signed-in viewer and
explicit rollback checks. It retains the original local browser backend. This is
a partial DW-4/DW-5 result: Library transfers, durable browser profiles, disposable
Hermes workers and agent shell computers remain future work. The
[qualification record](docs/design/space-integration-qualification.md) preserves
the earlier isolated experiments.

The remaining sequence is proposed; a standing fleet is not required. See the
[technical assessment](docs/research/space-and-durable-agent-workspaces.md).

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

Continue using the assistant and release small, qualified improvements. The
durable-workspace track above now gives the next engineering direction; memory
correction, additional tools and software delivery remain possible later slices.
No proposed capability changes the qualification status recorded below.

The recorded first-release source includes deliberate human takeover and the native
login vault, Terminal, About You and saved agent identity/appearance. The
address/search and follow-ups source slice adds saved search preferences, local
destination suggestions and durable ordered messages during an active reply.
Its qualification covers synthetic desktop/mobile journeys and pinned native
contracts; live activation remains a separate release decision. See the
[slice contract](docs/design/browser-followups.md).
