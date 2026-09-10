# Security supervisor and maintenance

Status: security oversight, optional private review, and responsibility for
checking and maintaining platform components are accepted product direction.
Weekly OS updates followed by scheduled guest restarts are the accepted default,
with advance notice and work preservation. Detailed execution remains proposed;
the deadline rule for a bot that cannot save safely is the next open decision.
Updated: 2026-09-10. Nothing here is deployed.

The security supervisor helps the administrator understand the installation's
security and health, decide what needs attention, and keep supported components
maintained. It is a platform role with a stable system identity and visible
responsibilities. It is distinct from a Chief of Staff coordinating people's
work and from a bot role template with a reassuring name.

## Responsibilities

| Responsibility | Useful output | Limit |
| --- | --- | --- |
| Security oversight | Explain denied operations, expired grants, suspected compromise, and coverage gaps; group repeated findings | A finding does not authorize punishment, new access, or automatic quarantine |
| Optional private review | Receive scoped findings from a reviewer operating within the selected bot's privacy boundary | No central feed of private conversations, files, or unrestricted summaries |
| Component inventory | Installed and actually running versions, ownership, support status, latest check time | Unknown or stale evidence is visible; worker-reported state is not trusted proof |
| Update assessment | Available fixes, advisory relevance, compatibility, affected bots/services, and expected disruption | Release notes and advisory text are evidence, never executable instructions |
| Maintenance planning | Exact targets/versions, window, required restarts, verification, and recovery steps | No silent expansion from one component to unrelated hosts or services |
| Approved maintenance | Track installation, health checks, bounded recovery, and an auditable outcome | Execution must satisfy a grant or maintenance policy enforced outside the model |

Use existing controller, permission, deployment, and service-health evidence
first. These responsibilities do not require a separate monitoring stack or a
second general-purpose VM with root access. Security signals should continue
without inference; if the supervisor cannot interpret them, show coverage and
pending work honestly. Duplicate expected denials are not automatically incidents.

[Telemetry, logs, and analytics](observability.md) are part of this foundation:
correlate task/run events, actual serving versions, resource pressure, security
findings, and maintenance receipts. The supervisor interprets evidence within
its grants. It cannot turn missing logs into a clean bill of health or use an
incident to enable unrestricted content capture. Analytics does not grant trust.

## Two kinds of authority

For **security incidents**, the accepted version 1.0 rule remains: observe,
warn, and recommend. An authorized human chooses intervention. The supervisor
cannot use a suspicion to pause a bot, remove its grants, inspect private history,
or approve publication. Existing deterministic restrictions still enforce.

For **maintenance**, a disclosed standing policy authorizes weekly OS updates
and planned guest restarts without a fresh approval every week. The supervisor
carries each policy-admitted plan through to verified completion. Other changes
need their own approved scope. An approved maintenance restart is a
specific operational action, not general permission to quarantine a bot. Its
authority expires with that plan. Maintenance must not become a way to rewrite
privacy settings, add tools or permissions, or bypass human control of priorities.

The model proposes typed requests; a deterministic controller checks the caller,
administrator approval/policy, exact plan digest, target identity, current
version, permitted operation, expiry, and concurrency lock. A bounded deployment
or update adapter executes the admitted operation. The model receives sanitized
status and cannot supply arbitrary shell commands, package repositories, or
replacement artifacts. Keep infrastructure credentials in that managed execution
boundary and unavailable to agent VMs or conversational prompts.

Worker files, tool results, update metadata, and even a compromised supervisor
cannot create or widen a maintenance grant. Installing a package can itself run
privileged code: pinned artifacts and narrow verbs reduce risk, but are not a
claim that a malicious trusted upstream is harmless.

## What version 1.0 should maintain

Propose a small, declared support matrix:

- Radhouse components and its qualified runtime/deployment adapters.
- The pinned Hermes runtime, platform-supplied tools, and reviewed bundled skills
  in managed bot environments. Inspect changes to skills and capabilities;
  updates do not grant new ones or enable schedules.
- Qualified guest-OS packages and bot base images. Updating a provisioning image
  does not update existing persistent VMs; inventory and plan those separately.
- Optional shared services installed and managed by Radhouse, such as chat,
  receive-only bot mail, and SSO, with service-specific compatibility and recovery.

For supplied VMs, execution requires the separately configured guest maintenance
capability. A supplied machine does not grant hypervisor access. Externally
managed SSO, inference servers, Proxmox hosts, storage, and network equipment
remain visible as dependencies where read access exists; report updates and
handoff steps, but do not automatically take ownership of them. Additional host
maintenance adapters need their own explicit scope and qualification.

Bot-installed packages are inventoried on a best-effort basis; unknown packages
are not covered by a blanket “fully patched” claim. Reconcile customizations
before touching them. Preserve bot-owned work, memories, secrets, and installed
software unless an approved migration specifically addresses them. Fleet
maintenance must not switch the operator-selected inference provider or change
the model served by an externally managed inference service.

## A reviewable maintenance flow

1. **Check:** use configured sources and an administrator-configured cadence.
   Record freshness, running versions, advisories, and confidence. A new release
   is not automatically a qualified upgrade; an unavailable feed is not “safe.”
2. **Prepare:** resolve exact immutable artifact versions/digests and changes;
   show target components, affected users, new configuration/capabilities,
   compatibility, restart needs, and a concrete recovery plan. Verify authenticity
   using the qualified channel's trust roots/signatures and freshness rules.
   A checksum alone is not publisher authentication.
3. **Authorize:** the administrator reviews the plan, or a previously approved
   weekly OS policy admits the exact batch. A standing policy can admit new
   qualifying package versions each week; freeze the admitted batch's versions
   and artifacts before execution. Changed batch contents require readmission,
   with human approval if outside policy. An urgency label never supplies authority.
4. **Apply:** recheck state and authority; wait for a safe task boundary and
   prevent new work on approved targets during the window. A bot that cannot
   checkpoint safely reaches the unresolved maintenance-deadline decision below;
   do not claim it is ready or safely replay unknown external effects. Stage
   changes and test one suitable target before
   a wider rollout where that reduces the actual risk. Recheck authority before
   each subsequent mutation; revocation stops new steps and cannot undo an
   already completed or in-flight action. Recovery still needs valid authority.
5. **Verify and recover:** confirm running versions, useful task resumption,
   permissions, and service-specific health. Stop the batch on a failed check.
   A recovery step may run automatically only when included in the same approved
   plan and valid for the resulting state. Otherwise retain evidence and request
   help. Report partial completion and exactly which targets remain affected.

Choose recovery evidence proportional to the change. A replaceable stateless
component may only need the old artifact/configuration. Stateful upgrades or
schema changes need a compatible recovery procedure and retained state; a VM
snapshot alone does not prove database consistency. Never restore expired grants
or repeat external actions while recovering a bot. Reverting code across an
incompatible schema must stop. Retained snapshots and receipts inherit the
underlying data's access and retention controls.

Updating the supervisor, controller, identity service, or its enforcement adapter
needs an independently executable recovery path. A conversational supervisor
cannot be its own sole health witness or approve changes to its own authority.
Use qualified controller/host mechanisms with an operator recovery procedure;
do not add an autonomous chain of supervisory bots to solve this problem.

## Everyday experience

An administrator sees **Needs attention**, **Updates available**, **Maintenance
planned**, and **Coverage unavailable**, each with evidence and a next action.
A plan might read: “Update two research bots after their current tasks finish;
leave the others available.” Show downtime as an estimate or unknown, not an
invented guarantee. The operator sees only the effect on their assigned work:
“Mira will be unavailable after this task; your files and history are retained.”
Do not disclose other operators' tasks in maintenance notifications.

## Accepted default: weekly OS maintenance

Version 1.0 defaults to automatic weekly OS updates followed by planned restarts
of enrolled, supported Linux guests. Setup shows the enabled policy, targets,
weekly window, IANA timezone, preparation period, and recovery behavior. An
administrator can change these settings; a bot cannot postpone or expand them.
This is a standing installation policy, not a weekly request for approval.

Cover supported OS security and routine bug-fix packages within the installed
release, including kernel updates and required dependencies where the profile
qualifies them. Use trusted configured repositories and a resolved package plan.
Show held, excluded, failed, or unsupported updates explicitly; do not describe
an incomplete package run as fully patched. Check for advisories more frequently
than the install window; a daily check is the proposed starting cadence. Surface
urgent fixes for an administrator's expedited decision rather than hiding them
until next week.

An OS release upgrade, unqualified package removal, application/schema migration,
new package source, or authority change is outside this routine lane. Do not
blindly remove bot-installed software during cleanup. Hermes, container images,
skills, and shared-service application versions retain separately reviewed
maintenance plans unless a later explicit policy covers them. OS packages that
restart a database or another sensitive daemon require that service's qualified
maintenance contract. “OS update” does not erase service dependencies.

The default can cover bot VMs and supported Radhouse control/shared-service
guests enrolled by the administrator. It does not enroll arbitrary machines or
grant Proxmox-host, network, or external inference-server authority. For supplied
VMs, qualify either the Radhouse maintenance adapter or a documented handshake
with the owner's scheduler; detect competing timers and report unmanaged
restart paths. Do not claim predictable maintenance while another updater can
restart services without coordination.

## Prepare, save, update, restart, resume

| Stage | Proposed behavior |
| --- | --- |
| Publish the calendar | Each affected bot and operator can see the next occurrence, target window, timezone, and policy revision. Supply this structured context at task admission, delegation, and resume; notify affected work when it changes. Show only permitted targets and work. |
| Give notice | Announce the upcoming cycle in advance; proposed reminders are 24 hours and 1 hour before the earliest affected update. Bots created or tasks started later receive the current countdown immediately. Use configured in-product notices; no implicit external messaging. |
| Prepare | Proposed default: 30 minutes before a target's update, stop admitting new work that cannot finish or checkpoint in time. Queue new requests and subtasks visibly. Give the bot a bounded instruction to save work and a concise continuation note. |
| Verify saved state | Persist drafts/files, task progress, pending operations, and continuation references. Record an acknowledgement tied to this occurrence, task/run, and durable checkpoint revision. The runtime/controller verifies the persisted state and quiesces execution; a model saying “saved” is insufficient. |
| Apply and restart | After preparation and readiness checks, update and restart the target in its assigned window. Use a dependency-aware sequence; keep the controller/recovery path available while workers are maintained. Required shared-service maintenance prepares all affected workers first. |
| Resume | Verify guest, services, current versions, grants, and data compatibility; restore task context from the durable checkpoint and release queued work. Mark uncertain external operations for reconciliation instead of replaying them. Report success, failure, delay, and any intervention needed. |

Preparation must complete **before package installation**, since packages can
restart services before the final reboot. Coordinate system-managed automatic
updaters with the same readiness contract; downloading or checking packages is
different from installing them. Ubuntu documents automatic service restarts
during unattended updates; its defaults are not evidence that arbitrary bot
work is checkpointed. [Ubuntu service-restart behavior](https://documentation.ubuntu.com/release-notes/24.04/).

Saving work does not require committing or pushing Git changes. Preserve local
edits and drafts within their existing audience. Memory and a continuation note
do not preserve every running terminal process, browser session, or external
transaction. Publish a checkpoint/recovery capability matrix for supported
tools, and keep operation IDs and outcomes in the controller outside the worker.
Do not restore expired permissions or reissue an uncertain GitHub/mail/publication
operation after a restart.

Use one recorded occurrence ID to prevent duplicate cycles. Resolve timezone,
daylight-saving transitions, target staggering, and any jitter into an announced
window. Proposed DST behavior: one occurrence for a repeated local time, and the
next valid local time for a skipped time. Missed windows become overdue work;
an offline guest's return must not cause a surprise catch-up reboot. Reconcile
and announce a new preparation window before admitting ordinary work. A schedule
change cannot silently shorten the promised preparation period.

The controller and host adapter must handle preparation and execution without
supervisor inference. If readiness or recovery evidence is unavailable, show
the precise blocked condition; no model-generated guess can authorize a restart.
Keep a usable operator recovery path when maintaining the controller itself.

## Open decision: a bot is not ready at the deadline

Advance notice and continuous durable state reduce this case but cannot prove
that arbitrary installed software will always save safely. Do not silently
equate receiving a reminder with readiness. Two product options remain:

- **Bounded grace, then restart — proposed recommendation:** after a configured
  grace period, stop the affected run using the qualified adapter, preserve the
  latest durable state, and carry out the scheduled maintenance. Unsaved transient
  work can be lost; uncertain external actions require reconciliation before
  resume. This prevents a stuck or compromised bot from indefinitely vetoing
  maintenance. It does not override failed package or recovery safety checks.
- **Defer the affected target and alert an administrator:** keep its maintenance
  overdue until readiness or a human decision permits it. Continue other safe
  targets and make the unpatched exposure explicit. A deferral must not quietly
  disappear into the next week's schedule.

The choice is pending. Accepting weekly maintenance does not implicitly select
forced termination of work whose safe checkpoint could not be verified.

## Research informing this proposal

- Hermes documents update preview/plan commands, machine-readable receipts,
  gateway restarts, and checks of running versions. Its ordinary update follows
  main and can change dependencies/configuration. Radhouse should qualify and
  wrap supported mechanisms with its own pinned plan rather than assume that
  calling an updater preserves work or permissions. These are documented
  features, not integration evidence. [Hermes updating guide](https://hermes-agent.nousresearch.com/docs/getting-started/updating/).
- Renovate's dependency dashboard separates seeing pending upgrades from approval
  to create upgrade pull requests. Borrow the inspectable queue pattern; a
  dependency PR approval is not fleet deployment permission.
  [Renovate dashboard](https://docs.renovatebot.com/key-concepts/dashboard/).
- TUF identifies rollback and frozen-update attacks in addition to malicious
  artifacts. The maintenance contract must account for authenticity and freshness;
  this does not commit Radhouse to operating another service or claim TUF is
  already implemented. [TUF security model](https://theupdateframework.io/docs/security/).

## Qualification required

Exercise forged/expired plans, changed digests/versions, duplicate execution,
revocation during a batch, malicious release notes, and compromised workers.
Check interrupted updates, active tasks without checkpoints, mixed versions,
new skill/schedule attempts, supplied-VM capability denial, and shared-service
outages. Prove scope checks survive supervisor inference failure, failed
rollouts stop, private evidence stays scoped, and the supervisor cannot approve
its own grants. Test rollback compatibility and controller recovery, including
failure of the component that normally reports health.

Also test pre-install service restarts, competing automatic updaters, late task
admission, changed schedules, offline/catch-up behavior, DST transitions, and
shared dependencies. Verify preservation of uncommitted files/drafts, checkpoint
authenticity, scoped notifications, pending-operation reconciliation, and the
selected deadline policy. Demonstrate an actual resume without duplicate effects
before advertising automatic weekly maintenance as qualified.

Related: [principles](../PRINCIPLES.md), [boundary experience](boundary-experience.md),
and [version 1.0 roadmap](../ROADMAP.md).
