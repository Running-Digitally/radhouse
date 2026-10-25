# Controlled Hermes worker replacement

Status: implemented and deployed in the owner pilot on 2026-10-25. Web admission
source: `47bdc9ec1eb70978c29692097c73b6dada2ffc69` (initial qualification at
`fe1c068634da30488729a021334736f6329ab582`); recovery tooling subsequently
qualified at `d160b1d`. Native Hermes remains at the pinned v0.21.6 composition.
Installation paths, credentials, operation scripts and receipts are private.

This is the first single-owner implementation of DW-0/DW-1. It keeps the stable
Hermes endpoint and retained home. Hermes remains responsible for session loading,
memory, keyed run admission, gateway ownership and native backup/import.

## Operator sequence

1. Install an operator-owned dispatch control directory outside the worker home.
   Set `RADHOUSE_WORKER_CONTROL` on the web service. A shared file lock spans each
   chat admission, including its HTTP acknowledgement. Creating a durable hold
   takes the exclusive lock, so successful hold creation proves earlier admissions
   have finished. Send, Retry and queued follow-ups all use that gate. Missing or
   unreadable configured control state fails closed; a hold never expires itself.
2. Stop the web service after holding admission, closing browser/terminal clients
   and quiescing chat, Library and auth writers. Stop the native gateway through
   its existing supervisor. Confirm its process and cgroup are empty. Do not
   attach the home elsewhere when this cannot be established. The current slice
   replaces a process on the existing host; it is not a cross-host storage lease.
   This first operator procedure requires native browsers and human terminals to
   be idle before stopping the gateway. It does not migrate an active browser
   session or preserve its temporary profile. Active chat can drain or be stopped
   through the native API; its actual terminal outcome remains authoritative.
3. With writers stopped, create the recovery set. Invoke the pinned full
   `hermes backup`, retain its completion report and review exclusions. Package
   chat SQLite and originals, auth database export, private settings/key custody,
   external workspace data and runtime/source identities separately. Hash every
   payload. Keep archives private and outside public source control.
4. Start the compatible native worker against the same home. Reuse Hermes's
   native gateway lock. Confirm capabilities, original session/run identities and
   retired browser authority. Start the web service with admission still held;
   observation may save terminal outcomes, but cannot dispatch a queued message.
5. Review unresolved admissions and interrupted work. Never replay an interrupted
   or unknown run as a new request. Release the exact hold only after readiness
   and reconciliation. A failed operation leaves the hold in place for an explicit
   operator retry; it never silently rolls state back.

## Code contracts

`chat.worker_control.DispatchGate` implements the cross-process admission barrier.
The operator CLI creates/releases a cycle identified by a random ID. No public
HTTP route or model tool can release it. The existing service dispatch function
is the final authority even if a request started before the hold. Browser and
terminal mutations receive a simple temporary-unavailability response while held;
the supervisor stop closes already-open channels before packaging.

`scripts/recovery_set.py` assembles and verifies immutable, private recovery sets
from quiesced component exports. Its manifest identifies component roles, source
pins, excluded material and payload digests. Verification refuses incomplete,
tampered, linked or unexpected payloads. Extraction requires the expected manifest
digest and compatible Hermes/web revisions from the operator's separate receipt.
Do not derive those expected values from an untrusted candidate archive. A
successful ZIP write does not prove that native export included all required stores. Installed orchestration
and secret-bearing location manifests belong in the private deployment record.

## Recovery and acceptance

Ordinary replacement reattaches current state without importing any archive.
Recovery imports the native ZIP into a fresh isolated home using the pinned
Hermes command and restores the other components into isolated targets first.
Use `scripts/hermes_offline_restore.py` on Linux: the pinned native import may
automatically install/start a gateway when it finds no installation at the
platform-default home. A custom `HERMES_HOME` does not disable that behavior.
The wrapper runs the unmodified import as the service user in a transient cgroup,
with network and service-control sockets unavailable, a read-only filesystem and
only the fresh target writable. Children are stopped with the importing process.
Native CLI logs may append during import; compare their archived prefix and
verify all remaining portable files and logical database contents exactly.
Check database integrity, session/run mappings, memory bytes and original file
digests. Verify the auth export can restore and private keys/settings are covered.
Only an operator may promote a restored set; never overlay an old set on a live
writer. An isolated restore is not evidence of a replacement-host boot or of an
off-host backup schedule.

Acceptance covers the admission race, restart with a hold, interrupted-run
reconciliation without redispatch, retained chat/memory/Library, native archive
import, payload tampering and current browser reconnection. Browser profile
durability remains DW-3: current SPACE profiles are temporary and excluded from
native backup. Keep the qualified SPACE backend and its previous backend available.

## Installed qualification and limits

The pilot checked a retained-home successor, the native lock's rejection of a
second owner, a hold across web/runtime restarts, and saved conversation recall.
A queued message stayed held and completed once after release. Native Stop
settled asynchronously as `cancelled`; forced worker loss settled as `interrupted`.
Both kept their original request/dispatch/run identities and were not replayed.
Graceful shutdown can instead drain a reply to `completed`; preserve that result.
Memory and original file contents matched the captured state.

Native export/import and Radhouse component restores passed with private synthetic
test evidence. Authentication was restored into a fresh temporary database and
the test database was then removed. Native restore verified portable files and
logical SQLite contents, including the run ledger. An uninitialized vault was
recorded explicitly; no key or credential data was fabricated. Old operator-only
historical files that blocked unprivileged native backup were retained separately
in protected configuration custody.

The first import exposed automatic gateway activation. The corrected offline
wrapper was executed successfully and left no extra service or child cgroup.
Updated package extraction requires independently retained manifest/source pins.
The final full regression gate passed 1,691 tests and 20 subtests with 306 optional
fixture skips; the focused recovery/hold suite passed 16 tests. Actual
post-recovery browser navigation and snapshot tools succeeded on SPACE, with the
previous browser backend retained. Native viewer input/video rechecking is a
separate desktop acceptance item; it is not inferred from tool success.

This is an operator-controlled same-host process replacement, not distributed
leasing, a new VM provisioner, a scheduled off-host backup system or an executed
replacement-host boot. Browser cookies remain temporary until DW-3. A recovery
archive contains credentials when they exist: keep it private and establish
separate protected custody before claiming host-loss recovery.
