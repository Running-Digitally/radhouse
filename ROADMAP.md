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
| GitHub | Mediated access by default; explicit advanced direct scoped tokens; authorized branch and pull-request work with human merge approval. |
| Privacy | Private by default; explicit sharing or disclosed supervision per agent; shared projects and human-reviewed publication. |
| Oversight | Security-event warnings; optional scoped private review; central supervisor warnings and recommendations, with human intervention. |
| Private-data egress | Restricted default profile; explicit administrator grant for broader browsing; documented and tested limits for supported combinations. |
| Collaboration | Delegation to existing project agents; owner-influenced or self-organized reporting lines; leads coordinate work within shared budgets. |
| Routines | On-demand tasks and human-configured schedules with explicit timing, targets, and limits. |
| Optional shared services | Buzz chat, receive-only bot mail, and SSO, with documented installation and isolation contracts. |
| Optional remote access | Limited guided Cloudflare Access and Tunnel setup for the application, with local use available independently. |

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

These are responsibilities to design and qualify, not a requirement to create
one independently deployed service per responsibility. Choose the least complex
implementation that adequately enforces each boundary.

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
| 8. Release qualification | Reproducible installation, upgrade and recovery guidance, configuration tests, useful fleet work, and published evidence for supported profiles. |

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

## Decisions still to resolve

- The first-use interaction: how the control-plane work view and optional chat
  service fit together for a non-technical operator.
- Human and bot service identities, credential lifecycles, and the concrete
  mediation mechanism for each allowed GitHub operation.
- Optional mail delivery and attachment behavior, including how receive-only
  restrictions are enforced outside the agent runtime.
- The bundled SSO choice and tested account-linking and recovery behavior.
- Runtime checkpoint capabilities, inference conformance, and behavior when an
  operator changes the model behind a service-following alias.
- Technology stack, packaging, configuration schema, and installation and
  upgrade contracts for each supported deployment profile.
- Public-contribution CI placement and treatment of untrusted code. Public CI
  must not inherit private infrastructure credentials or caches.

## Deferred from version 1.0

Additional agent runtimes, automated provisioning on other hypervisors, dedicated
cloud-inference integrations, private-agent question exchange with automatic
answers, and automatic supervisor intervention are deferred. Broad personal
inbox/calendar access, outbound bot email, unattended merge/deploy, and agents
expanding their own grants are outside the accepted release boundary.

## Working in public

Keep product contracts, public configuration examples, tests, and installation
code reusable. Keep deployment-specific inventories, hostnames, credentials,
private conversations, and local integration overlays in separately managed
private locations. Do not import a private infrastructure repository's history.

Original Radhouse work uses [Apache-2.0](LICENSE). Assess upstream versions,
interfaces, and licenses before packaging them; no upstream integration is
qualified merely because it appears in this roadmap.
