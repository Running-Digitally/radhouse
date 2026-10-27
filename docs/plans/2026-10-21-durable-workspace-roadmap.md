# Durable workspace development roadmap

Date: 2026-10-21. Updated: 2026-10-25. Status: engineering sequence with a deployed
browser-first DW-4/DW-5 slice and an installed DW-0/DW-1 operator slice.
Broader on-demand placement and host-loss recovery are not yet qualified.

The [initial SPACE implementation record](../design/space-integration-qualification.md)
tracks the experimental management client, synthetic failure tests, real
Firecracker lifecycle, headed-browser streaming/control and pause continuity.
These are partial DW-0/DW-4 results. The subsequent owner-authorized
[browser-first slice](../design/space-browser-pilot.md) qualified and deployed
an application-integrated remote browser with explicit local rollback. It retains
temporary profiles and a running microVM; it does not establish whole-Hermes
replacement, durable profiles, Library transfers or an agent shell capability.
The [controlled replacement slice](../design/controlled-worker-replacement.md)
subsequently added retained-home worker replacement on the existing host and
isolated recovery-package restoration. It does not relocate the worker to a
new host or add a provisioning fleet.

Outcome: **I return to the same assistant, files and browser even when its compute
has been replaced.** The [architecture proposal](../design/durable-assistant-workspaces.md)
defines the target. [Technical research](../research/space-and-durable-agent-workspaces.md)
records source constraints. [ADR-0007](../decisions/0007-public-engineering-private-commercial-strategy.md)
keeps this the public engineering backlog; commercial plans reference these IDs.

## Baseline and sequencing

The October 25 [implementation gap check](../research/hermes-continuity-gap-check.md)
reviews `2ed8aa89cb03e922e687a99ace1d946a36029698` and its pinned Hermes v0.21.6
source/overlays. It supersedes the initial `f44df3e` source assessment for this
sequence. This is a code review, not a new inspection of installed state.
Preserve the qualified owner pilot while implementing capability-gated changes.

Hermes already supplies native session persistence, memory, keyed Runs admission
and backup/import. Radhouse already stores chat/run identities, frozen inputs and
ordered follow-ups. Reuse them. DW-0 closes storage/release mapping; DW-1 adds a
controlled replacement and recovery path. It no longer starts with a broad
experiment to prove Hermes persistence or a new native checkpoint implementation.

DW-2 and DW-3 can proceed independently once their storage/authority contracts
are agreed; neither requires disposable Hermes workers. DW-4 work is limited to
unqualified capabilities actually needed by the next slice. Browser memory
snapshots, a runtime comparison and a standing fleet are not prerequisites.
DW-5 adds on-demand lifecycle and separate shell execution after the relevant
integration checks. DW-6 and DW-7 remain later increments.

| ID | Deliverable | Completion evidence | Deployment boundary |
| --- | --- | --- | --- |
| DW-0 | Retained-store mapping and paired-release contract | Pilot mapping, protected seven-component recovery set and isolated restores qualified; off-host custody/schedule and blank-host recovery remain | Operator-owned source and state receipts |
| DW-1 | Controlled Hermes worker replacement using retained native state | Installed: durable admission hold, same-host replacement, native exclusive-owner refusal, retained conversation/memory/originals, cancelled/interrupted outcomes without replay, trusted restore identity checks | Single owner/current host; native backup/import reused; on-demand placement remains DW-5 |
| DW-2 | One Library for browser transfers | Device/Library upload and human/agent download journeys; durable publication; Private exclusion | Existing browser/runtime, capability gated |
| DW-3 | Retained browser profile and explicit reset | Login/site-state restart, host-backup restore, privacy/revocation and compatible rollback | One owner/profile on the qualified backend |
| DW-4 | SPACE host and adapter qualification | Real Linux/KVM measurements, security and lifecycle failures, teardown evidence | Separate lab with synthetic accounts/data |
| DW-5 | On-demand remote computers | Full browser parity and separate shell isolation; integrated recovery and current-authority checks | Single-owner opt-in after lab acceptance |
| DW-6 | Helpers and scheduled work | Durable triggers, single-writer native state, quotas and reconciled effects | Incremental opt-in; no automatic co-tenancy approval |
| DW-7 | Optional browser migration | Supported import, explicit choices, safe failure and rollback | Convenience feature after profile qualification |

## DW-0: inventory and release contract

Primary ownership: `src/radhouse/chat/` state/admission, `runtime/hermes/` native
adapter, `runtime/selkies/` lifecycle, and release tooling. Keep changes in their
owning modules rather than introducing a second controller from the retired fleet.

- Use the gap check's source inventory, then map actual retained stores privately:
  ChatStore and originals, Hermes home/session and run-idempotency databases,
  memories/skills/configuration, native vault and browser-control database, plus
  relevant workspace files or configured external memory. Do not copy live paths,
  credentials or contents into this public plan.
- Define a small recovery manifest across those stores and source/schema pins.
  Reuse native backup/import; inspect exclusions and skipped files. Hold relevant
  writers for a coherent package rather than treating individual SQLite backups
  as an atomic cross-service snapshot. Browser profile backup is separate.
- Keep existing owner/session/request/dispatch/run identities. Add exclusive
  runtime ownership and stale-worker rejection where replacement requires them;
  do not rebuild the current Runs protocol or earlier retired fleet controller.
- Preserve the existing single web-worker constraint until its process-local
  locks and observers have a proven durable replacement.
- Specify a qualified application/native/schema release lane. The current
  [release helper](../deployment/repeatable-releases.md) applies static web source
  only; it must refuse these changes until the separate lane is ready.
- Carry forward the final S5 lifecycle follow-ups in the
  [stabilization plan](2026-10-15-boundary-stabilization.md#observed-owner-pilot-acceptance-after-diagnostic-selection).
  The earlier cleanup root cause remains unproven and a lost close acknowledgement
  required reconciliation. Reopen on recurrence and before broader users,
  co-tenancy or ingress expansion; retain the recorded 2026-11-14 review trigger.

Exit: reviewed installation mapping and a concrete release/replacement/rollback
procedure based on native capabilities. Source inventory alone does not qualify
a new storage attachment or recovery package.

## DW-1: continuity before disposable compute

Primary ownership: a bounded operator replacement/recovery helper, the existing
native runtime composition, and ChatService admission/observer integration.
Hermes continues to own state persistence and transcript loading. ChatStore's
stable session and dispatch keys, saved receipts and frozen requests remain intact.

Build the first usable slice in this order:

1. Produce and validate the retained-store/release manifest. Package a protected
   recovery set using native full backup/import plus the Radhouse stores outside
   its scope. Preserve the vault/key and source compatibility requirements.
2. Add a replacement hold covering new sends and observer-dispatched follow-ups.
   Use native drain/stop behavior, confirm the old owner is gone, and attach the
   same persistent home to a compatible successor at the stable service endpoint.
   Ordinary replacement does not restore an older backup or copy state per turn.
3. Check required capabilities and callback access, reconcile existing run IDs,
   retire obsolete browser grants, then release the hold. An unresolved admission
   remains held; expired idempotency records do not authorize redispatch.

Reuse the [existing regression coverage](../research/hermes-continuity-gap-check.md#existing-tests-to-reuse).
Add only coverage of the new hold/attachment/recovery boundary: clean replacement,
interrupted replacement, second-writer denial, missing required store, incompatible
source/schema and rollback retaining newer data. One synthetic integration journey
checks conversation, native memory, Library access and queued follow-ups against
the replacement. Restore the recovery package separately to check backup coverage.

Acceptance: no acknowledged file/message loss on retained-storage replacement;
no duplicate accepted reply or blind retry of interrupted effects; no writable
old owner; missing/incompatible state fails clearly. Report recovery time and
the backup's recovery point separately from process replacement. The pinned API's
`interrupted` result is a valid recorded outcome, not a promise to finish that run
automatically. General automatic action continuation remains future work.

## DW-2: ordinary file handling

The [implemented candidate and qualification findings](../design/browser-library-transfers.md)
are recorded separately. The unexpected browser retirement is reproduced and
corrected in the candidate: a confirmed transient target detach no longer faults
the entire file observer. That correction is deployed. Installed device and
Library uploads, Private download byte integrity and a 94-second native picker
have passed. Explicit sharing, agent upload/download and Private observation/
chooser denial also passed after the admission and callback parser corrections.
DW-2 is deployed and accepted in the private pilot; review/merge status remains
separate. Profile persistence is the next DW-3 slice.

Primary ownership: Library/ChatStore and the browser/native file bridge. Add an
opaque-file-ID upload contract and an idempotent completed-download intake.
Keep the seven existing browser tools narrow; introduce an explicit capability
for file transfer rather than unrestricted browser debugging or host paths.

Exercise these user journeys with synthetic files:

- Upload from device or Library to a website selected by the person/task.
- Human download and agent download both appear in Library with the same
  retention and save-to-device behavior; interrupted transfers show useful status.
- Download completion races a browser close/restart; a saved receipt still names
  an intact file, and retries do not create duplicate entries.
- Private takeover files remain person-visible and excluded from agent context
  until shared. An agent request cannot read another owner's or private file.
- Destination changes, forged filenames/IDs, symlinks, large/archive inputs and
  hostile content cannot broaden file access or escape isolated processing.

Acceptance includes a short observed usability walkthrough: ordinary authorized
transfers require no repeated permission cycle and no new file-class taxonomy.
Diagnostics retain provenance without treating a human click as a safety label.

## DW-3: browser persistence on the existing runtime

Primary ownership: browser worker/profile lifecycle, native vault boundary and
browser UI. Introduce one retained profile per workspace, exclusive attachment,
consistent checkpoint/backup, compatible restore and explicit Reset browser data.
Qualify the selected browser backend and preserve its existing local rollback.
Hermes backup deliberately excludes browser profiles; implement this storage
contract explicitly. A local-only proof must not be called SPACE profile support.

Exercise login/session storage, site preferences and owner history across clean
Close/Open, service restart, interrupted checkpoint and restore onto replacement
compute. Restore a backup from the independently protected destination. Verify
that session expiry/MFA is handled honestly, Private history is not replayed to
the assistant, old input leases are rejected, and credentials do not enter model
results, Library or logs. Qualify disabling Chromium-native password saving and
the intended vault/profile key custody before retaining the profile.

Acceptance: user can return to a supported signed-in test site after restart;
reset removes the intended local browser data; another workspace cannot attach
the profile; backup/version failure preserves a known recoverable generation.
Do not claim every website session is portable or immortal.

## DW-4: separate SPACE laboratory

Partial result (October 22): sandboxed headed Chromium, Selkies video, human/agent
handoff, pause/wake with synthetic site state, and a separate root-shell guest
worked in the isolated lab. Both guests were retired. An already-open WebSocket
survived SPACE session revocation in a bounded test, so the Radhouse relay must
close streams and fence input itself. An invalid empty-VM clock preflight skipped
browser memory-snapshot testing. It remains unqualified; correct the harness if
snapshot support is selected later, rather than making it a continuity prerequisite.
Maintained packaging, current-authority
restore, external profile durability and full application parity remain open;
see the [qualification record](../design/space-integration-qualification.md).

Primary ownership: a new execution adapter and its host qualification record.
Use an isolated Linux x86_64 host or VM after verifying KVM/nesting, required
devices, btrfs, supported CPU/kernel behavior and available memory/storage. Keep
real profiles, credentials and pilot customer data out of this experiment.

Pin SPACE, Firecracker, guest images and the actual substrate. Record missing
direct-mode capabilities instead of claiming orchestration parity. Measure cold
and warm ready time, idle/active resource use, browser stream/input latency,
concurrent capacity, checkpoint size/time and restore behavior. Establish explicit
acceptance budgets before declaring success; this plan invents no measurements.

Test guest-root isolation, network/metadata restrictions, DNS/shared-IP and redirect
cases, effective policy after restore, revoked grants, old endpoints, host restart,
unacknowledged operations and orphan cleanup. Use both a browser image and a
separate shell image. A successful shell command or vendor benchmark is not
interactive-browser or application-recovery qualification.

Exit: reproducible measurements, supported/unsupported capability matrix, failure
evidence and removal procedure. Decide whether SPACE is suitable and which
substrate is justified. A failed evaluation can leave DW-1 through DW-3 useful.

## DW-5: on-demand computers for one assistant

Partial delivery (October 23): the owner explicitly prioritized a browser-first
slice before durable profiles. Actual video, human/agent handoff, Private/Observe
boundaries, reconnect, fresh launch, host cold recovery and explicit local rollback
passed. The frozen adapter is selected in the owner pilot. Full file/profile
parity and separately authorized shell execution below remain open.

Primary ownership: Radhouse execution adapter, browser transport and Hermes tool
integration. First prove a remote browser with existing display/input/privacy
behavior and retained profile. Replace local Unix-peer assumptions with qualified
mutual authentication and owner/run/generation authorization. Keep management
endpoints and raw browser debugging outside the agent and browser client.

Then expose a separately authorized shell capability in a different guest with
only task-selected files. Do not promote the current human-only Terminal into
an agent tool implicitly. Verify shell root cannot access browser state, vault,
control storage, private network services or ungranted Library files.

Exercise the complete task, including browser upload/download and worker loss.
Restore rechecks current grants before tools/network use. Stop/revoke drains
input and retires endpoints. Failed remote admission never silently falls back
to an unconfined local shell. If the new capability fails, disable new admissions
and reconcile existing work before selecting the previously qualified adapter.

## DW-6 and DW-7: later capabilities

DW-6 adds helpers with isolated work copies, scoped context, inference/resource
budgets and serialized accepted memory updates. Add scheduled trigger IDs and
notification outcomes only after admission/recovery works without an open chat.
Prove cancellation, duplicate wake-up handling and uncertain effects. One
credentialed browser identity retains one active controller. Multi-customer
co-tenancy needs a separate isolation, quota and operating qualification; adding
helpers does not supply it.

DW-7 adds **Bring your browser** as optional supported import. Start with bookmarks
and selected preferences. Show exactly what will transfer; exclude automatic
extension activation; handle credential transfer only through the qualified
vault. Require sign-in again where OS/device-bound sessions are nonportable. Test
rollback and temporary-package deletion. Do not extract protected cookies by
weakening the laptop's security or require import to begin using Radhouse.

## Recommended deployment sequence and release gates

1. **Delivered bounded slice:** retain the qualified SPACE browser pilot and its
   explicit local rollback. This does not complete the durable-workspace target.
2. **Next build:** DW-0/DW-1 retained-store mapping, native recovery packaging and
   controlled worker replacement on the existing single-owner setup. Use upstream
   support and current tests; qualify only the integration changes.
3. **Next user-facing increments:** DW-2 browser/Library transfers and DW-3 retained
   profiles, independently reversible once their contracts are settled. Run DW-4
   checks only for the infrastructure behavior these or later shell work require.
4. **After evidence:** expand the bounded pilot toward full DW-5. Expand to DW-6 only after
   ordinary use and recovery evidence justify it. DW-7 is optional.

Before each runtime activation, freeze exact source/images and current host
configuration; run the changed boundary's positive/negative tests; prove data
backup and compatible rollback; record resource/recovery budgets, named operator,
acceptance and explicit activation authority. Keep private host identity,
credentials and raw evidence outside public source. Publish synthetic/reduced
qualification evidence and unresolved limits.

Failure recovery preserves newer chat, files, profiles and vault state. Quiesce
admission, reconcile effects and choose compatible code/checkpoints; never erase
newer data to make an older binary start. Releasing a new adapter does not grant
permission to delete the existing runtime or its recovery copies. The owner
authorized documentation publication and starting implementation/testing on
2026-10-21, and subsequently authorized the qualified browser-first activation
recorded above. Broader runtime activation remains a separate qualified change.
