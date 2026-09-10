# Backup and restore

Status: hybrid protection is accepted for version 1.0. Proxmox, Linux guests,
and existing NAS-backed workflows are the first reference deployment pattern.
The portable engine, coverage manifests, schedules, and recovery procedures
remain design and qualification work. Updated: 2026-09-10. Nothing is deployed.

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

Propose administrator-led guided restore into a stopped or externally isolated
target first. Recover the controller through a documented path that works when
its normal UI is unavailable. Verify data/schema compatibility and the selected
recovery set before enabling any agent runtime, cron, or integration.

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

Choose the default engine, backup frequency/retention, storage setup, key custody,
and detailed restore permissions through subsequent design. A default profile
must state its expected data-loss and recovery targets and prove them with
restore exercises; a selected backup engine alone is not that proof.

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
