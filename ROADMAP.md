# Version 1.0 roadmap

**Current stage: requirements and architecture.** No milestone below is marked
complete by the existence of this repository. There is no installable release
or qualified security boundary yet.

Version 1.0 must deliver a usable fleet that people can assign work to,
observe, and continue using across assignments, including useful GitHub-based
software engineering. A documentation-only release or a single-agent demo does
not meet that definition.

## Intended release boundary

| Area | Version 1.0 direction |
| --- | --- |
| Agent runtime | Hermes first, behind an adapter suitable for later runtime additions. |
| Agent environment | Persistent Linux VM per agent; terminal, files, and browser access within the agent's boundary. |
| Deployment | Guided Proxmox provisioning plus an installation path for operator-supplied, suitably isolated Linux VMs. |
| Inference | Self-hosted compatible APIs; explicit provider selection; qualification for required tools, model attribution, and interruption recovery. |
| Human access | Administrator, operator, and viewer roles; local accounts plus optional bundled SSO or connection to an existing provider. |
| Operator starting screen | A simple work home with assigned agents, current work, and a prominent Start a task action; conversations and project details remain available within Radhouse. |
| GitHub | Mediated access by default; explicit advanced direct scoped tokens; authorized branch and pull-request work with human merge approval. |
| Privacy | Private by default; explicit sharing or disclosed supervision per agent; shared projects and human-reviewed publication. |
| Oversight | Security-event warnings; optional scoped private review; central supervisor warnings and recommendations, with human intervention. |
| Maintenance | Automatic weekly OS updates and planned guest restarts by default, under a disclosed administrator-managed policy; advance notice, work preservation, and verified recovery. Security takes precedence: stop unready bot runs after bounded preparation/grace and proceed. Other component changes retain separate review. |
| Observability | Built-in work/health/event views; local-by-default telemetry, logs, and analytics; scoped audit and maintenance receipts; visible coverage and resource limits. |
| Backup and restore | Hybrid: managed portable application/data backups plus optional qualified infrastructure protection for complete bot computers; Proxmox/NAS-backed workflows first, with a supplied-VM path and explicit coverage/recovery evidence. |
| Recovery priority | Tiered work-data RPO targets: Standard ~1 hour, Important ~15 minutes, Disposable ~1 day, conditional on deterministic support preflights. Retain the latest 3 validated work-data recovery points; historical archives are off by default. Prioritize recent recovery and finite storage budgets. |
| Recovery keys | Built-in key management for unattended backups, with a guided administrator-held recovery kit saved outside the installation and verified through recovery. Worker bots receive no backup keys. |
| Work model and naming | Persistent bots, project workspaces, finite tasks, role/project/task starters, optional scoped Chief of Staff; four changeable naming presets and individual overrides. |
| Private-data egress | Restricted default profile; explicit administrator grant for broader browsing; documented and tested limits for supported combinations. |
| Collaboration | Delegation to existing project agents; owner-influenced or self-organized reporting lines; leads coordinate work within shared budgets. |
| Routines | On-demand tasks and human-configured schedules with explicit timing, targets, and limits. |
| Optional shared services | Buzz chat, receive-only bot mail, and SSO, with documented installation and isolation contracts. |
| Optional remote access | Limited guided Cloudflare Access and Tunnel setup for the application, with local use available independently. |

## Operator work home

The version 1.0 operator starts on a simple work home showing assigned agents,
current work, and a prominent **Start a task** action. Opening a task or project
keeps its conversation, progress, files, results, and permission requests within
Radhouse. Buzz remains optional for group chat.

The home should make working, waiting, finished, and needs-help states easy to
understand. An operator with no assigned agents sees a clear way to request one
from an administrator. Show only information and actions permitted by the
person's role and scope; a viewer's read-only experience does not offer task
submission. Server-side authorization must enforce the same boundaries.

The accepted [work model](docs/work-model.md) connects persistent bots, project
workspaces, finite tasks, and reusable role/project/task starters through several
entry points into one brief. An optional Chief of Staff coordinates within
explicit information scope. It does not gain automatic assignment authority or
additional access from its title.

Make context, audience, and bot access visible using the
[boundary experience](docs/boundary-experience.md). Offer four changeable
[naming presets](docs/naming-preferences.md) with individual overrides, preserving
stable identity and permissions across renames. Detailed interactions remain
proposed until implemented and qualified.

Qualification includes an unfamiliar operator starting useful work, finding its
result, and understanding a blocked action without a terminal, external manual,
or administrator coaching. The work-home requirement is accepted; a working
interface and usability evidence remain to be delivered.

## Proposed component boundaries

- **Control plane:** human roles, agent assignments, project membership, work
  admission, progress, schedules, and explicit grants.
- **Deployment adapter:** provision and manage an agent VM using only the
  capabilities qualified for that deployment path. A supplied VM does not
  automatically give Radhouse access to its hypervisor.
- **Agent runtime adapter:** start, observe, interrupt, and recover an
  assignment while preserving identity and reporting actual capabilities.
- **Service-access boundary:** enforce granted operations and resource scopes,
  including the selected GitHub credential mode and revocation contract.
- **Inference route:** retain operator-selected provider identity, enforce
  admission policy, and attribute work to the model actually served.
- **Shared services:** integrate chat, mail, and identity through explicit
  contracts rather than giving agent VMs administrative access to those services.
- **Security and maintenance:** correlate scoped findings and maintain component
  inventory; execute only admitted maintenance plans through bounded adapters.
  The [supervisor design](docs/security-supervisor.md) separates model proposals
  from enforced authority and defines the weekly OS default with bounded
  preparation and mandatory maintenance despite unready bot work.

These are responsibilities to design and qualify, not a requirement to create
one independently deployed service per responsibility. Choose the least complex
implementation that adequately enforces each boundary.

[Observability](docs/observability.md) spans these components from the first
useful task. Correlate work, security, and maintenance through scoped structured
evidence; keep sensitive content out of routine telemetry. Qualify missing-signal,
denial, retention, and resource-pressure behavior as each slice is delivered.

## Proposed delivery sequence

| Milestone | Evidence needed before moving on |
| --- | --- |
| 1. Contracts and configuration | Reviewable architecture and component contracts; validated synthetic configuration; documented supported and refused combinations. |
| 2. One persistent agent | Useful task completion through the control plane, retained workspace, truthful inference attribution, and recovery on both deployment paths. |
| 3. Collaboration and admission | Two agents complete shared work without gaining private access; queued background work respects interactive priority and shared limits. |
| 4. Software engineering | A scoped repository task produces a branch and pull request; credential custody, denial, revocation, and human merge boundaries hold in both supported credential modes. |
| 5. Human roles and privacy | A new operator can use an assigned agent without infrastructure knowledge; role isolation, sharing review, supervision, and private-data egress behavior pass boundary checks. |
| 6. Optional shared services | Independently optional chat, receive-only mail, and SSO integrate without widening agent grants; remote Access/Tunnel setup qualifies separately. |
| 7. Delegation and routines | Existing project agents complete bounded subtasks; cycles, duplicate delivery, budgets, cancellation, and scheduled runs obey the admitted work and current grants. |
| 8. Maintenance and release qualification | Component inventory, update checks, approved-plan execution under the selected policy, running-version checks, failure/recovery proof, reproducible installation, configuration tests, useful fleet work, and published evidence for supported profiles. |

Development should proceed through small end-to-end slices. The sequence is a
planning proposal, not a schedule or a promise to implement all components in
parallel.

## Capacity and recovery

Publish capacity evidence for a declared host and inference configuration.
Concurrent active assignments and simultaneous model generations are different
measurements. Resource priority, queueing, browser workload, model context, and
memory pressure must be visible in the results.

Recovery must distinguish resuming agent reasoning from replaying external
actions. Restoring a workspace must not revive an expired grant or silently
repeat a publication, pull-request operation, or scheduled task.

The accepted [hybrid backup model](docs/backup-and-restore.md) provides portable
application/data protection and an additional complete-computer lane through
existing infrastructure. Prioritize the Proxmox/Linux-guest/NAS reference pattern;
retain generic configuration and the supplied-VM path. Show actual coverage and
restore evidence instead of assuming every new bot inherits existing backup jobs.

## Decisions still to resolve

- Maintenance implementation: supported package profiles, checkpoint contracts,
  preparation/grace timing, forced-stop behavior, pending-action reconciliation,
  and recovery adapters. Weekly OS updates/restarts and security precedence over
  unready work are accepted; other component changes retain separately reviewed plans.
- Detailed project-management permissions, starter contents, naming-preference
  precedence, cross-project grants, retained memory, and usable boundary displays
  within the accepted work model.
- Human and bot service identities, credential lifecycles, and the concrete
  mediation mechanism for each allowed GitHub operation.
- Optional mail delivery and attachment behavior, including how receive-only
  restrictions are enforced outside the agent runtime.
- The bundled SSO choice and tested account-linking and recovery behavior.
- Runtime checkpoint capabilities, inference conformance, and behavior when an
  operator changes the model behind a service-following alias.
- Technology stack, packaging, configuration schema, and installation and
  upgrade contracts for each supported deployment profile.
- Telemetry schemas/backend, retention defaults, export boundaries, metric
  definitions, and resource budgets for a small installation.
- Hybrid backup engine, exact schedules and rotation mechanics,
  storage onboarding, recovery-kit implementation, consistent capture, and
  detailed restore permissions; tiered targets and the three-point lean default are accepted,
  while capacity/performance gates and optional retention policies need
  design/qualification. Complete-computer and controller recovery require qualification.
- Public-contribution CI placement and treatment of untrusted code. Public CI
  must not inherit private infrastructure credentials or caches.

## Deferred from version 1.0

Additional agent runtimes, automated provisioning on other hypervisors, dedicated
cloud-inference integrations, private-agent question exchange with automatic
answers, and automatic supervisor incident intervention are deferred. Maintenance
execution includes the accepted weekly OS policy and security-precedence deadline.
Broad personal
inbox/calendar access, outbound bot email, unattended merge/deploy, and agents
expanding their own grants are outside the accepted release boundary.

Extensive historical snapshot browsing and automatic long-term backup archives
are not version 1 baseline requirements. Retain the hybrid infrastructure recovery
path and a small usable fallback set; adding historical retention needs an
explicit capacity-qualified policy.

## Working in public

Keep product contracts, public configuration examples, tests, and installation
code reusable. Keep deployment-specific inventories, hostnames, credentials,
private conversations, and local integration overlays in separately managed
private locations. Do not import a private infrastructure repository's history.

Original Radhouse work uses [Apache-2.0](LICENSE). Assess upstream versions,
interfaces, and licenses before packaging them; no upstream integration is
qualified merely because it appears in this roadmap.
