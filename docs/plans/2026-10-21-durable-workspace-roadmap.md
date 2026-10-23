# Durable workspace development roadmap

Date: 2026-10-21. Updated: 2026-10-23. Status: engineering sequence with a deployed
browser-first DW-4/DW-5 slice; no whole DW stage is complete.

The [initial SPACE implementation record](../design/space-integration-qualification.md)
tracks the experimental management client, synthetic failure tests, real
Firecracker lifecycle, headed-browser streaming/control and pause continuity.
These are partial DW-0/DW-4 results. The subsequent owner-authorized
[browser-first slice](../design/space-browser-pilot.md) qualified and deployed
an application-integrated remote browser with explicit local rollback. It retains
temporary profiles and a running microVM; it does not establish whole-Hermes
replacement, durable profiles, Library transfers or an agent shell capability.

Outcome: **I return to the same assistant, files and browser even when its compute
has been replaced.** The [architecture proposal](../design/durable-assistant-workspaces.md)
defines the target. [Technical research](../research/space-and-durable-agent-workspaces.md)
records source constraints. [ADR-0007](../decisions/0007-public-engineering-private-commercial-strategy.md)
keeps this the public engineering backlog; commercial plans reference these IDs.

## Baseline and sequencing

The source baseline is `f44df3e8172e834a913b8418c6b21db00d92e1c9`, not a live host
inspection. Existing pilot qualification does not establish new profile storage,
remote-browser or microVM behavior. Preserve the current qualified owner pilot
while implementing behind explicitly disabled capabilities.

Start DW-0 and DW-1. DW-2 and DW-3 can then proceed independently against the
agreed state contracts. DW-4 is an isolated infrastructure experiment and can run
in parallel after DW-0; it is not a prerequisite for useful file/browser work.
DW-5 depends on successful continuity and SPACE qualification. DW-6 follows real
single-assistant recovery. DW-7 is optional convenience work, outside the first
deployment's critical path.

| ID | Deliverable | Completion evidence | Deployment boundary |
| --- | --- | --- | --- |
| DW-0 | Native state, authority and paired-release contract | Complete source inventory; compatible recovery manifest; specified migration/rollback; current lifecycle follow-ups assigned | No user behavior change |
| DW-1 | Whole assistant survives worker replacement | Clean replacement and abrupt-loss matrix retain chat, originals, native memory and pending work without blind effects replay | Existing single-owner runtime first |
| DW-2 | One Library for browser transfers | Device/Library upload and human/agent download journeys; durable publication; Private exclusion | Existing browser/runtime, capability gated |
| DW-3 | Retained browser profile and explicit reset | Login/site-state restart, host-backup restore, privacy/revocation and compatible rollback | One owner/profile before any remote move |
| DW-4 | SPACE host and adapter qualification | Real Linux/KVM measurements, security and lifecycle failures, teardown evidence | Separate lab with synthetic accounts/data |
| DW-5 | On-demand remote computers | Full browser parity and separate shell isolation; integrated recovery and current-authority checks | Single-owner opt-in after lab acceptance |
| DW-6 | Helpers and scheduled work | Durable triggers, single-writer native state, quotas and reconciled effects | Incremental opt-in; no automatic co-tenancy approval |
| DW-7 | Optional browser migration | Supported import, explicit choices, safe failure and rollback | Convenience feature after profile qualification |

## DW-0: inventory and release contract

Primary ownership: `src/radhouse/chat/` state/admission, `runtime/hermes/` native
adapter, `runtime/selkies/` lifecycle, and release tooling. Keep changes in their
owning modules rather than introducing a second controller from the retired fleet.

- Inventory every state store used by the pinned native runtime, including
  databases/journals, memory, configuration, tool state and relevant workspace
  files. Identify intentional temporary state and unresolved external effects.
- Define compatible manifests across chat, native state, artifacts and browser
  profiles. Establish authenticated owner/run/generation identifiers and the
  durable admission/fencing boundary before adding concurrent web/agent workers.
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

Exit: reviewed contracts, a synthetic recovery fixture and a concrete release/
rollback procedure. No claim that inventory alone proves continuity.

## DW-1: continuity before disposable compute

Primary ownership: ChatStore/ChatService and the native Hermes adapter. Introduce
stable run IDs, consistent state checkpoints, effect receipts and explicit
uncertainty without replacing Hermes' memory semantics.

The first end-to-end demonstration uses an ordinary multi-turn task with attached
files, a memory update and a queued follow-up. Stop/recreate the worker, reattach
retained state, and continue the same assistant. Then inject loss before/after
admission acknowledgement, file commit, native checkpoint and reply publication.
Repeat with an external-effect stub that records whether a mutation occurred.

Acceptance: no acknowledged file/message loss; no duplicate accepted result or
blindly repeated uncertain mutation; stale workers cannot write; incompatible
state versions fail clearly; conversation/native progress reconcile. State the
maximum recoverable uncheckpointed work and measured restore time. Prove rollback
preserves newer data instead of restoring an older application database.

## DW-2: ordinary file handling

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
Continue using the current runtime placement for this stage.

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
browser memory-snapshot testing; correct that harness and run the actual test.
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
2. **Next runtime candidates:** DW-0/DW-1 continuity on the existing single-owner
   setup, then DW-2 file transfers and DW-3 retained profiles as separately
   reversible, qualified changes. This provides useful behavior before a fleet.
3. **In parallel:** continue the remaining DW-4 experiments with synthetic data,
   including memory snapshots and capacity; qualify each change separately.
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
