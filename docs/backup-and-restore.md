# Backup and restore

Status: hybrid protection is accepted for version 1.0. Proxmox, Linux guests,
and existing NAS-backed workflows are the first reference deployment pattern.
Tiered work-data recovery targets are accepted only with deterministic support
preflights. Recent recoverable work takes priority over extensive historical
snapshot retention or browsing. The lean work-data default is accepted: retain
the latest three validated recovery points, with historical archives off by
default. Built-in key management with an administrator-held recovery kit is
also accepted. Operators may recover currently authorized files into a separate
folder; administrators handle whole-bot and platform recovery. The engine,
manifests, schedules, and detailed procedures still need design and qualification.
Updated: 2026-09-10. Nothing is deployed.

## One recovery experience, two protection layers

Radhouse manages portable backups of its application and work data. Existing
infrastructure can additionally protect complete bot computers. Show both in one
recovery view, with their coverage, freshness, ownership, and last restore test.
Do not make people infer what is protected from a single green backup icon.

| Layer | Owner and purpose | Important limit |
| --- | --- | --- |
| Task checkpoint | Radhouse/runtime saves progress, files, and pending-operation references for restart recovery | A checkpoint on the failed disk cannot recover that disk |
| Portable application/data backup | Radhouse schedules a qualified existing engine against consistent exports and declared persistent data; the administrator supplies storage | Restore is portable only across compatible schema/runtime versions; copying a workspace does not capture every installed tool or volume |
| Complete bot computer backup | The administrator's qualified infrastructure backup workflow captures the VM or complete guest state | All relevant disks/volumes and application preparation must be covered; a snapshot alone is not proof of usable recovery |

The third layer supplements the portable baseline. Enable and verify it where
complete-computer recovery is required. For supplied Linux VMs, retain a manual,
documented integration path using the owner's qualified guest/system backup tool;
do not require access to its hypervisor. Recovery of arbitrary custom software
requires complete capture or a demonstrated reconstruction path. A file-only
deployment must disclose that limitation instead of claiming complete protection.

## Version 1.0 focus

Prioritize a Proxmox deployment using existing backup storage, including a NAS
destination, plus the portable data layer. Reuse an established backup engine;
do not build a new backup engine or require a new backup server merely to enable
Radhouse. Qualify one recommended portable path and a bounded Proxmox integration
before expanding the provider catalog. Proxmox Backup Server is a possible
integration for people who already use it, not an installation prerequisite.

The first reference deployment can drive sequencing, sample configurations, and
acceptance tests. Product code and schemas remain generic: keep hostnames,
credentials, paths, retention choices, and schedules in installation overlays.
The supplied-VM path remains supported; it may require more administrator setup.
No private installation's existing jobs are automatically reconfigured or assumed
to protect newly provisioned bots.

## Accepted recovery targets and priority

Use three administrator-controlled work-data profiles: **Standard**, targeting
about one hour of recent work at risk; **Important**, about fifteen minutes;
and **Disposable**, about one day. Standard is the proposed installation default.
Operators inherit the profile and can request a change; bots cannot weaken it.
Overlapping/shared state uses the strongest admitted requirement or separately
qualified recovery sets. Protect controller/identity/operation state separately;
it cannot inherit a weaker profile from a disposable project.

These are recovery point objectives (RPOs), not promises that a timer alone can
deliver. Measure the age of data in the newest completed, validated, consistent
recovery point. Capture, queueing, verification, and retry time affect freshness;
derive a schedule with enough margin to meet the target. Restoration time is a
separate objective. None of these work-data profiles requires hourly full-VM images.

Version 1 prioritizes reliable recent-state recovery within a finite storage
budget. Long historical archives, automatic monthly/yearly retention, and a
user-facing time-machine-style version browser are not baseline requirements.
This does not remove the accepted optional infrastructure recovery layer, the
few fallback points needed for safe recovery, or an update's explicit rollback
requirements. Do not impose a new retention policy on an existing external job.

## Accepted lean retention default

Retain the latest three completed, validated, compatible work-data points for
each tier. The refresh schedule changes with the RPO; a tighter target does not
increase historical retention. Existing infrastructure owns its separate policy.

| Recovery set | Retention policy and status |
| --- | --- |
| Standard work data | Latest 3 completed, validated, compatible recovery points |
| Important work data | Latest 3 points; refresh more frequently to meet the tighter target |
| Disposable work data | Latest 3 points; refresh less frequently within its target |
| Optional complete-computer lane | Latest 2 usable images/sets remains a recommendation for the infrastructure owner, not an adopted policy for existing jobs |
| Extra historical archive | Off by default; adding history requires an explicit capacity-qualified policy |

Any optional history needs an explicit capacity-qualified policy; its detailed
configuration remains design work. The accepted default does not require a
history-browsing interface.

Keep a controller-authorized catalog of valid points, independent of names,
timestamps, and claimed success supplied by a worker. Count only completed sets
whose integrity and consistency checks pass. Their underlying capture/restore
procedure must have a current qualification test; validating each archive is
not a claim that every capture received a full restore rehearsal.

After admitting, capturing, and validating a replacement, expire the oldest
eligible point and run the backend's space-reclamation process. A failed or
partial upload never replaces a usable recovery point. Point count is a steady
state policy: budget temporary space for the incoming copy before old data can
be removed. Sets with incremental dependencies retain every required base/chunk;
deleting a listed point does not necessarily free its full logical size.

The proposed minimum safety floor is **two independently committed usable points**
per set after initial seeding; they need not be on independent devices and do
not provide off-site protection by themselves. A new set with fewer points is
visibly initializing. Never delete the only surviving usable point. Ordinary
age or a missed backup must not silently erase the last recovery path. Explicit
administrative data deletion remains a separate scoped action.

Optional history, manually pinned points, and pre-update rollback artifacts all
consume the same declared capacity budget. A rollback artifact may have a
separate release condition: identify its owner, bytes, and retention condition
before admitting the change. Do not let automatic snapshot creation become an
unbounded exception. Pruning obeys current recovery leases and backend locks.

A three-point rolling set offers only a short window for discovering accidental
deletion or corruption, especially for Important work. Older history may no
longer be recoverable. Disclose this tradeoff in setup; adding a small daily
history is a separate storage decision, not a consequence of a tighter RPO.

## Deterministic support preflight

The selected policy is enforceable only when a versioned rule set can return
**pass**, **fail**, or **unknown** from measured evidence. Unknown is not pass.
The supervisor may explain the result but cannot override it or estimate a
missing capacity value into a pass. Run this before enabling a profile, adding
protected state, changing storage/retention, or materially changing the engine.

| Check | Required evidence and admission rule |
| --- | --- |
| Scope and recovery | Fixed source/target identity, declared volumes/exports, compatible manifests, recovered keys, and a successful isolated restore of representative data. Missing custom-software/volume coverage is explicit. |
| Capacity | Actual destination free bytes and enforced installation quota; current use, bounded source growth, next-capture peak, indexes/staging, prune/repack/GC overhead and delay, retained dependencies, rollback holds, and shared-infrastructure reserve. Do not assume favorable compression or deduplication. |
| Freshness | Measured capture-to-usable latency under representative churn and concurrent fleet work, including verification, queueing, retries, and cleanup locks. A conservative operating bound plus schedule interval must fit the selected RPO. Record the load/data limits under which it passed. |
| Reclamation | Demonstrate expiration and actual byte reclamation with the selected retention policy. Account for backend delays/locks; a deleted catalog entry or count reduction is insufficient. |
| Permissions and failure | Verify source/target access, encryption/recovery, scoped retention rights outside worker control, destination outage handling, failed uploads, and preservation of the existing usable recovery set. |

The numerical thresholds, evidence age, and supported data/load envelope belong
in validated configuration. Use conservative source quotas/change bounds for
admission; a small favorable sample is not proof that future growth fits. A
bootstrap measurement or restore rehearsal is a separately authorized bounded
operation, not an excuse to inspect/decrypt private content in an administrator UI.

Before each backup write, deterministically check that expected peak use stays within
the installation budget and leaves the required shared-storage reserve. Enforce
write quotas/limits independently of the model and allowlisted scope. Keep global
physical capacity authoritative where deduplicated snapshots share storage;
per-project logical-size estimates cannot enforce a physical byte ceiling.
Unknown maximum growth means no admission of the tighter profile until bounded.

On failure, keep the requested profile unavailable with a concrete reason and
remedy. Do not silently select a weaker RPO or expand storage/privileges. If the
environment changes after admission, show **Protection target missed** or
**Capacity blocked**, with the real recovery-point age, and stop admitting new
backup commitments that do not fit. A preflight pass is not a perpetual guarantee
against destination outages, new data patterns, or failed jobs.

## Preserve freshness without filling shared storage

Reserve room for replacement captures and cleanup before accepting the policy.
As pressure rises, apply only the approved retention policy: shed optional
history first, then eligible points above the safety floor, and verify reclaimed
space. Prefer funding a fresh recovery point over retaining optional old history.
Never discard required incremental bases, leased rollback state, or the sole
usable copy to attempt an unproven replacement.

If even the required current data, safety floor, and replacement workspace do
not fit, no policy can guarantee both the RPO and the storage ceiling. Refuse the
new backup write/commitment and alert the administrator to add budget, reduce explicitly
approved scope, or select a different target. Preserve existing usable backups
and shared-storage safety; do not disguise missed protection as success. Ordinary
resource limits prevent a bot from creating unlimited source growth. A missing
bot checkpoint still does not veto accepted weekly OS security maintenance.

Backend qualification matters here. Restic separates forgetting snapshots from
pruning data; its documentation states that pruning locks the repository and
can prevent backups completing. Proxmox Backup likewise separates pruning from
garbage collection. Verify both timing and actual reclaimed bytes for the chosen
backend. Neither is selected by this design.
[Restic retention](https://restic.readthedocs.io/en/stable/060_forget.html),
[Proxmox Backup maintenance](https://pbs.proxmox.com/docs/maintenance.html).

## Declare the recoverable set

The manifest must cover or explicitly account for:

- Controller configuration, stable identities, users/roles, membership, policies,
  schedules, task/operation history, and a separate credential recovery procedure.
- Project files and knowledge, private bot memory and conversations, local edits,
  drafts, runtime state, and every declared persistent volume.
- Installed package/tool state, custom binaries, and system configuration needed
  for a complete bot rebuild, through the appropriate protection layer.
- Optional shared services through service-specific consistent exports or
  qualified backup hooks, with their own scope and retention.

A package inventory is useful reconstruction evidence; it does not guarantee that
old versions, custom builds, or container volumes can be recreated. Preserve
uncommitted work without requiring a Git push. Treat bot-supplied path lists and
backup hooks as untrusted; the administrator's manifest determines authority.

For the two backup layers, retain capture/version identifiers and document which
restore sets are compatible. Do not combine a controller from one time with an
older bot disk and silently resume work. Show normal recovery, partial recovery,
and unresolved external operations distinctly.

## Security and custody

Retained private data must be encrypted through a qualified archive or storage
mechanism. A compressed VM archive or encrypted network transport alone does not
establish encryption at rest. Keep recovery keys available independently of the
installation being recovered; test key recovery as part of restoration.

Use built-in key management for unattended backups. Setup guides an administrator
to export a recovery kit, store it outside the installation in an independently
recoverable location, and complete a guided recovery check using that copy. A
separate secrets-manager service is not required by the accepted default.

The kit must identify its protected recovery sets and include the material needed
to unlock them. Keep backup locations, required configuration, and an offline
restore procedure available without the lost controller. The kit does not contain
the backed-up work itself. Key rotation must preserve access to every retained
recovery set and prompt an updated export/check when necessary. Do not label key
recovery verified merely because a download button was clicked. The exact
export/check mechanism depends on the qualified engine and remains design work.

Scope operational key access to the backup/recovery components that require it.
Do not expose kit contents through bots, routine logs, analytics, or support
bundles. Protect its export through administrator authentication and an audit
event without recording secret values. Holding recovery keys does not grant
routine application permission to browse private contents.

Store backups outside worker-writable storage. Worker bots must not receive
backup repository credentials, other bots' keys, or retention/deletion powers.
Give retention/pruning only the bounded administrative authority it requires.
Multiple archives on the same failed device are not independent protection;
record the failure domains and any separately configured off-site copy.

Backup browsing, exports, support bundles, and recovery previews obey the data's
application audience. Infrastructure ownership and possession of decryption keys
remain a separate source of underlying power; do not promise privacy from the
machine owner or treat that power as routine permission to browse private work.

## Restore with current authority

Scoped self-service file recovery is accepted for operators. Provide a guided
action over the retained recovery points: select authorized files, confirm the
destination and audience, and recover a copy into a separate folder. Preserve
current work; do not overwrite files or activate restored code, bots, schedules,
or integrations. A full historical browsing interface is not required.

The recovery service enforces current permissions on both the source and the
destination and preserves the source data's privacy. Check access before exposing
backup names/previews and again before releasing recovered files. A historical
ACL or former membership does not revive access. Deny recovery when the source's
identity or applicable policy cannot be established, including for deleted files;
request administrator resolution without silently widening the audience.

Extract only the authorized file set into a bounded recovery location outside
automatic runtime/configuration discovery. Do not follow archive paths or links
into live work or a different privacy scope. Account for staging and output bytes
within resource limits. Keep backup credentials and keys within the recovery
service; operator self-service does not grant direct access to the backup store.
Credential material, control databases, grant records, and executable runtime
state require the administrator-led recovery path. This file-copy permission
does not grant worker bots self-restore powers or viewers write access.
Ordinary source-code files can be recovered as inert files; recovering a file
does not authorize executing it or loading it as runtime configuration.

Administrators perform whole-bot and platform recovery through a guided restore
into a stopped or externally isolated target first. Infrastructure recovery
authority does not grant routine permission to browse private contents. Recover
the controller through a documented path that works when its normal UI is
unavailable. Verify data/schema compatibility and the selected recovery set
before enabling any agent runtime, cron, or integration.

Reconcile current grants, revocations, pending operations, and stable identity.
Fence the previous instance before activating a replacement. Restored credentials
and old approval records do not automatically authorize external access. Direct
tokens embedded in a disk may need upstream revocation or replacement before
first connected boot; network isolation must exist outside that disk. Reuse of
an identity must not create two active bots with the same authority.

For suspected compromise, prefer a clean rebuild and reviewed data import over
reactivating restored executable state. A readable archive is not proof the bot
is trustworthy. Isolated restore staging is a recovery procedure, not a new
automatic security-supervisor quarantine power.

## Supervisor and maintenance interaction

The supervisor reports backup coverage, overdue captures, integrity checks,
restore-test age, storage pressure, and missing recovery keys using scoped
evidence. It does not need access to decrypted private contents to report health.
Distinguish “job completed,” “archive verified,” and “restore tested.”

Plan backup schedules around maintenance and actual work-loss/recovery targets.
The weekly OS update policy does not imply weekly backups are sufficient for
active work. A bot's failure to create a new checkpoint must not indefinitely
veto the accepted security maintenance deadline. Separate infrastructure recovery
prerequisites are predeclared, proportional, and independently verified.

## Qualification and remaining choices

Demonstrate restoration of a project/file, a bot with local edits and custom
software, and a lost controller. Test absent keys, excluded/mounted volumes,
inconsistent exports, old schemas, expired grants, duplicate identities,
uncertain external actions, and compromised executable state. Test retention
and storage failure without giving a worker backup deletion authority.

Choose the default engine, storage setup, the recovery-kit implementation,
and concrete restore authorization/extraction contracts through subsequent
design. Derive backup frequency from the accepted tier's measured operating
envelope. A default profile
must state its expected data-loss and recovery targets and prove them with
restore exercises; a selected backup engine alone is not that proof.

Also exercise quota exhaustion, incompressible/high-churn data, slow verification,
cleanup locks/delay, failed/forged points, dependent incremental chains, retained
rollback holds, clock skew, and unavailable evidence. Prove deterministic refusal
of unsupported profiles and that ordinary rotation preserves usable recovery
while respecting actual peak bytes. Qualification must include the intended
fleet concurrency rather than only one idle bot.

Test recovery with the original controller unavailable and the externally saved
kit. Exercise missing/stale kits and key rotation across retained recovery sets;
verify that worker bots and ordinary telemetry cannot obtain recovery material.

Qualify self-service recovery against revoked/changed membership, inaccessible
backup metadata, deleted sources with missing policy, path traversal and links,
destination collisions, insufficient space, and runtime auto-discovery. Verify
that files remain copies, privacy is preserved, and system recovery powers are
not reachable through the file-recovery action.

## Source grounding

Proxmox documents file/image backup archives, explicit handling of mount points,
client-side encryption, independent recovery-key custody, and recovery tests.
Its VE integration can use PBS through the usual VM/container backup workflow.
These are candidate mechanisms, not evidence of a qualified Radhouse integration.
[Proxmox Backup client](https://pbs.proxmox.com/docs/backup-client.html),
[VE integration](https://pbs.proxmox.com/docs/pve-integration.html).

Restic's file/snapshot backup model is another candidate building block for the
portable layer; no engine is selected yet.
[Restic backup guide](https://restic.readthedocs.io/en/stable/040_backup.html).
