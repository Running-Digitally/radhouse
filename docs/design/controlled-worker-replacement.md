# Controlled Hermes worker replacement

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
tampered, linked or unexpected payloads. It does not treat a successful ZIP write
as proof that native export included all required stores. Installed orchestration
and secret-bearing location manifests belong in the private deployment record.

## Recovery and acceptance

Ordinary replacement reattaches current state without importing any archive.
Recovery imports the native ZIP into a fresh isolated home using the pinned
Hermes command and restores the other components into isolated targets first.
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
