# Security supervisor and maintenance

Status: security oversight, optional private review, and responsibility for
checking and maintaining platform components are accepted product direction.
The execution design below is proposed; the maintenance authorization policy
is the next open decision. Updated: 2026-09-10. Nothing here is deployed.

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

For **maintenance**, recommend allowing the supervisor to carry an approved
plan through to verified completion. An approved maintenance restart is a
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
   narrow policy admits it if that option is selected. Changed targets, artifact
   digests, privileges, or material impact require a new decision. An urgency
   label never supplies authority.
4. **Apply:** recheck state and authority; wait for a safe task boundary and
   prevent new work on approved targets during the window. A bot that cannot
   checkpoint safely makes the plan wait for a human decision; do not interrupt
   unknown external effects. Stage changes and test one suitable target before
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

## Maintenance authorization decision

**Recommended for version 1.0:** the supervisor checks and prepares plans;
an administrator approves each maintenance batch, and the supervisor carries
out that bounded plan, including only its approved verification and recovery.

**Alternative:** additionally offer administrator-defined automatic maintenance
policies for explicitly qualified low-impact updates. Each policy names targets,
allowed changes, window, health/recovery requirements, limits, and expiry or
review date. Privilege changes, schemas, identity/enforcement components, host
reboots, and changes outside that scope still need an individual plan approval.
“Patch version” alone is not proof of low impact.

Neither policy is selected yet. The request to include maintenance establishes
the product responsibility; it does not authorize changes to a live installation.

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

Related: [principles](../PRINCIPLES.md), [boundary experience](boundary-experience.md),
and [version 1.0 roadmap](../ROADMAP.md).
