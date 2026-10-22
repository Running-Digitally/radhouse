# Durable assistant workspaces and replaceable computers

Date: 2026-10-21. Status: proposed architecture; implementation and deployment
qualification remain open. The accepted documentation boundary is
[ADR-0007](../decisions/0007-public-engineering-private-commercial-strategy.md).

Radhouse should keep the same assistant, conversation and Library while replacing
the compute used to do work. Preserve the current simple experience: open the
app, ask for something, use the shared browser when useful, and return later.
Users should not have to choose a VM, classify a download or manage checkpoints.

The [technical research](../research/space-and-durable-agent-workspaces.md)
records the inspected source baseline and public evidence. The
[development roadmap](../plans/2026-10-21-durable-workspace-roadmap.md) owns the
implementation sequence. This proposal does not select SPACE for production,
enable agent shell access or claim that the current browser profile is durable.

## Target responsibilities

```mermaid
flowchart TD
    User[User: chat, Library, shared browser] --> Control[Radhouse control service]
    Control --> DB[Durable metadata and work receipts]
    Control --> Files[Private file and checkpoint storage]
    Control --> Worker[Hermes worker leased to an assistant]
    Worker --> Broker[Authorized tool and file access]
    Broker --> Browser[Browser computer with retained profile]
    Broker --> Shell[Disposable shell computer]
    Control --> Viewer[Authenticated browser viewer and input]
    Viewer --> Browser
    Vault[Existing credential vault] --> Fill[Scoped credential use]
    Fill --> Browser
```

These are responsibilities, not a requirement for eight independently deployed
services. Initially retain one Radhouse web/control process, the current database
and file storage, and one qualified Hermes runtime. Add separation where the
authority or lifetime requires it. A text-only turn need not start any browser or
shell computer. A browser may remain open while its agent worker is idle.

The preferred target runs Hermes separately from its tool computers, through
qualified adapters. Running an entire Hermes instance in a per-workspace VM is a
valid transitional arrangement if native state export is not ready. It must still
externalize durable state and enforce task grants outside arbitrary guest code.
A VM snapshot of that instance is not sufficient application recovery on its own.

## State ownership and storage

“Our database retains the assistant” means Radhouse controls durable storage and
recovery. It does not require putting large files, browser profiles and memory
snapshots into relational rows or recreating Hermes' memory system.

| State | Durable owner and location | Working copy and recovery |
| --- | --- | --- |
| Displayed chat, identities, file ownership, permissions, task status and effect receipts | Radhouse database outside worker VMs; keep SQLite for the single-process pilot | Workers receive scoped views. Database-backed admission and fencing are prerequisites for concurrent workers. |
| Original uploads, completed downloads and accepted/generated files | Radhouse private file store; database holds owner, version, digest, provenance and visibility | Task copies are disposable. Publish immutable versions; acknowledge a save only after durable file and metadata commit. |
| Native agent session, memory, configuration and relevant local files | Versioned Hermes state under Radhouse custody, with a manifest and an adapter-supported consistent checkpoint | Hermes remains the interpreter of its state. Inventory the actual native database, memory, pending state and dependencies; `USER.md` and `MEMORY.md` alone are insufficient. |
| Browser cookies, site storage, history and preferences | Separate private profile volume per workspace/browser identity | Attach to one browser generation at a time. Checkpoint consistently after stopping/quiescing Chromium; verify compatible restore. |
| Browser cache, temporary uploads and incomplete downloads | Temporary browser/task storage | Rebuild or reconcile after restart; these do not establish a durable Library save. |
| Saved credentials and encryption keys | Existing vault and separately controlled key custody | Exact-origin use through the qualified credential boundary; no bulk export to the model or shell guest. |
| Optional VM memory/disk snapshots | Protected infrastructure snapshot storage with version, owner and policy metadata | An acceleration/recovery aid. Recheck current authority before resuming; retained application files and receipts remain authoritative. |

For the first pilot implementation, place retained profiles and native checkpoints
in separate service-owned directories under the installation's private data root,
outside release trees and generation-temporary directories. Only the browser
service gets the browser profile. Only the owning runtime adapter gets writable
native state. The browser and shell do not mount the control database, the whole
Library or each other's data. Bind a lease to the workspace and generation before
attaching storage.

Back up these retained stores to a separately protected destination; a directory
on the same host only proves process/VM replacement, not host-loss recovery.
Record which backup generations form a compatible recovery point and test their
restore. Protect profiles and snapshots at rest and in transit, with keys outside
arbitrary task guests. Deleting an account must retire live copies, grants and
retained backups according to a stated retention policy. Do not promise immediate
physical erasure of every backup if the implementation retains generations.

Browser sessions are credentials. While a browser is active it necessarily has
access to usable session state. Encryption at rest does not protect that state
from a compromised active browser or a sufficiently privileged operator. Guest
root can read what is inside its guest; this is a central reason to keep arbitrary
shell execution outside the browser computer.

## One Library and ordinary browser file handling

Use one product experience for files:

1. **Add a file:** upload to Library or attach it in chat. In a website's upload
   flow, the picker offers **Your device** and **Library**. A device upload is
   retained in Library as well as transferred to the chosen website.
2. **Download a file:** completed browser downloads appear in Library, whether
   initiated by the person or the assistant. Show saving/failure honestly; allow
   saving to the person's device from Library. Do not silently expire agent
   downloads while retaining human downloads.
3. **Use a file:** files shared with the assistant's workspace are available for
   authorized work. A task such as “upload this application to this portal”
   supplies file-and-destination intent; it should not produce repeated prompts
   for each transfer step. Reading a file does not grant permission to disclose
   it to another destination.

Implement transfers through a small owned bridge. It resolves opaque file IDs
against the authenticated workspace, checks task/browser generation and intended
destination, and stages only selected bytes. A browser tool must not accept an
arbitrary host path or unrestricted debugging connection. Downloads are received
in staging, checked for completion and size/resource safety, and committed to
Library before staging is retired. Make completion publication idempotent so a
reconnect cannot duplicate or lose an acknowledged save.

Run content validation and safe preview/extraction behind this experience. Treat
file bytes, names, archive contents and embedded instructions as untrusted
regardless of who clicked Download. Isolate parsers, refuse path traversal and
unsafe serving, and handle suspicious files with a clear explanation and recovery
action. Record origin and human/agent provenance for audit and troubleshooting;
neither is a safety rating. Retaining a file is distinct from executing it.

Private takeover remains meaningful. Transfers performed in **Private** stay
visible to the person in the same Library but do not silently enter assistant
context or assistant-readable grants. An explicit share or authorized task can
make them available. The UI needs a small private indicator and a Share action,
not a catalogue of upload/download types. A user-selected Library file can be
sent to a site during Private takeover without granting the agent access to the
private interaction. The transfer service enforces this independently of the
model and streaming viewer.

## Browser persistence and human control

The current generation-local profile is deleted on retirement. Replace that
behavior deliberately; retaining only a last-page locator or the chat database
does not retain logins. The first implementation should retain a consistent
profile volume across clean browser restarts. VM memory snapshots come later if
their measured resume benefit justifies the extra compatibility and secret
handling requirements.

Keep **Hide/Show**, **Take control**, **Private/Observe** and **Return to agent**
semantics. Ending a browser process should release compute while preserving its
profile. Add a separate explicit **Reset browser data** operation with a plain
explanation of sign-outs and history loss; do not overload Close with erasure.
Sites can expire/revoke sessions or require MFA despite successful persistence.

Private interaction must not enter agent screenshots, events, transcripts,
autocomplete context or background file grants. On handback, drain old input,
issue a fresh generation/lease and expose only the page the person deliberately
returns to the assistant. Do not replay a private navigation/event backlog. A
later shared page can still reveal actions made privately on that website; this
limitation must be explained without suggesting that Private undoes site effects.
Owner browser history can be retained without making it an automatic model input.

Do not automatically fork a logged-in browser profile for helpers. Retained
cookies can confer substantial account power even when password values remain
hidden. Allow one writer/controller per browser identity; helpers use independent
uncredentialed browsers or queue requests through the owning browser session.
Authenticated concurrent identities need separate explicit qualification.

Keep password saving in the existing vault. Before retaining Chromium profiles,
audit the current `basic` password-store configuration and disable browser-native
password saving/import on this path unless a separately qualified encrypted store
is deliberately selected. Do not infer that the current profile contains saved
passwords. Preserve exact-origin fill, human MFA, and secret-free tool results.

Optional **Bring your browser** onboarding can import supported bookmarks and
preferences, with a preview and rollback. Login and MFA may be required again.
Raw laptop-profile copying is not a reliable portable session migration because
of OS/application/device binding. Never bypass those protections or automatically
activate imported extensions. Handle any supported credential transfer through
the vault and explicit consent; erase temporary transfer packages. Initial use
must work without importing anything.

## Durable work and replaceable Hermes workers

Preserve native Hermes semantics while making ownership and admission durable:

1. Commit a run ID, user intent, frozen inputs, adapter/version and scoped grants
   before dispatch. Acquire a workspace/session lease with a fencing generation.
2. Restore or attach a compatible native state generation. Admission and tool
   services reject writes and requests from an expired generation.
3. Run Hermes with only the authorized context and tool capabilities. Allocate a
   browser or shell computer lazily when a supported tool needs one.
4. Save artifacts and native progress through consistent checkpoints. Commit
   their manifest and run outcome before reporting durable completion. Use a
   staged manifest/commit protocol rather than assuming atomic transactions
   across the database, files and engine state.
5. Release compute when idle. On recovery, reconcile durable intent, native
   progress and effect receipts before choosing resume, completion or uncertainty.

At first support clean checkpoint-and-replacement; then prove abrupt worker loss
at specific admission, file publication, native checkpoint and reply boundaries.
Use SQLite's supported consistent backup mechanisms for SQLite state and account
for journals, open files and concurrent writers. A live directory copy is not a
checkpoint contract. Define a rollback-compatible checkpoint version and refuse
an incompatible engine instead of silently discarding state.

For external effects, use provider idempotency keys and receipts where available.
If a process dies after an external action but before saving its receipt, do not
blindly retry. Reconcile with the destination or hold the operation with an honest
status. Exactly-once execution is not obtained by adding a queue or VM snapshot.
Revoke old leases before a restored copy receives tool access, and enforce current
policy outside the snapshot so old authorization cannot come back to life.

Future schedules require durable trigger IDs, admission and outcomes such as
completed-without-notification, not a fabricated chat reply for every wake-up.
Helpers receive bounded context, separate work directories and budgets. Their
results become proposed artifacts; the owning session serializes accepted memory
and conversation updates. Multiple workers must not concurrently mutate one
Hermes state directory. Model-provider capacity and quotas are separately bounded;
more microVMs do not create more inference capacity.

## SPACE and the security boundary

Add an execution adapter only for capabilities actually proven on its substrate:
create, readiness, execute, stream, stop, suspend/restore and cleanup. Negotiate
support; do not promise fork or draining on an adapter that lacks the required
durability. Keep the existing browser/native adapter until remote parity is proven.

The local worker currently authenticates Unix peers and assumes host-local
display/native transport. A remote adapter needs mutually authenticated service
transport, owner/run/generation checks, narrow browser/file APIs, and server-side
stream/input authorization. Do not expose Chromium debugging, arbitrary ports or
SPACE management APIs to a user's browser or the agent. Recheck authentication
on reconnect and invalidate old viewer/input endpoints on retirement.

SPACE should enforce supported network policy outside arbitrary shell guests.
Radhouse supplies workspace identity, allowed destinations, scoped file grants,
credential use, action authority and recovery. The shell gets task-selected files
and tool rights, not the browser profile, vault, host socket or control database.
Block unintended private-network and metadata-service access, exercise redirects
and DNS/shared-IP cases, and test effective policy again after restore. An allowed
website can still receive an unauthorized upload; network policy is one layer.

Use existing task intent and remembered scoped grants for ordinary work. Ask at
a meaningful boundary: newly exposing private data, an unapproved destination,
an account/financial consequence outside the task, or unresolved external effects.
Avoid confirmation for routine navigation, every local file read or every chunk
of an already authorized transfer. Preserve an audit trail and a usable revoke/
stop path without making the person administer infrastructure.

## Decisions to settle through implementation evidence

- Exact native Hermes checkpoint inventory and compatible restore API.
- Profile encryption/key custody and backup-retention implementation for the
  pilot; measured acceptable recovery time and data-loss bound before activation.
- Whether a dedicated Linux host or a qualified nested VM satisfies SPACE's
  devices, storage, isolation and recovery requirements.
- Direct versus orchestrated SPACE substrate based on needed lifecycle features.
- Remote display responsiveness and idle-resource savings on the actual host.
- Any browser-import formats beyond bookmarks/preferences, based on supported
  migration rather than extraction of protected local sessions.

These are public technical decisions. Commercial packaging and investment
thresholds remain in the private commercial roadmap. No commercial decision is
required to establish a safe, usable public capability.
