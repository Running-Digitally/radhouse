# NVIDIA OpenShell and Radhouse: a bounded integration assessment

Date and source access: **30 September 2026, UTC**. Status: research complete; experiments proposed, not executed. Intended destination: Radhouse's existing `docs/` directory. This report authorizes no installation, permission change, model switch, runtime migration, or deployment.

## Decision

**Retain Radhouse's control plane and persistent per-bot VMs. Evaluate OpenShell as an optional execution and credential-enforcement backend for a bot with narrower tool needs. Do not migrate Builder first.** Its strongest potential benefits are endpoint-bound credentials, denied network access enforced outside the workload, and reviewable effective policies. Fleet orchestration, Buzz conversations, task identity, human authorization, artifact publication, and model selection remain Radhouse responsibilities.

OpenShell is a real NVIDIA open-source agent runtime. The current stable release is **v0.1.2**, published **2026-09-28T03:58:00Z**, with source commit **`6648bd0c290efbc41ba131ee9831ee45cd431f94`**. NVIDIA now documents qualified stable releases and compatibility rules. That establishes a more concrete support contract than the earlier alpha descriptions, but the 0.1 line began only on 25 September. Treat it as early stable software with substantial recent architectural change, rather than a locally qualified replacement for the existing system. [Release v0.1.2](https://github.com/NVIDIA/OpenShell/releases/tag/v0.1.2), [support matrix](https://docs.nvidia.com/openshell/about/support-matrix), [0.1 upgrade guide](https://docs.nvidia.com/openshell/upgrade/0-1-0).

Three findings dominate the decision:

1. **Builder has a direct compatibility conflict.** Its accepted environment supports rootless Docker and arbitrary unprivileged development inside a dedicated VM. OpenShell's mandatory workload controls prohibit mounts and user-namespace operations needed by a rootless container daemon inside its boundary. Attaching an external Docker socket would introduce a separate authority path and would not preserve the same enforcement claim. This is a source-backed compatibility inference, not an attempted integration failure. [Syscall controls](https://docs.nvidia.com/openshell/security/best-practices), [workload filter source](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-isolation-interface/src/linux/child_seccomp.rs).
2. **Current OpenShell preserves workload-owned model choice.** Version 0.1 removed the shared managed inference route. Profiles and attachments grant access to native provider APIs; the client selects the model, base URL and timeout. This fits explicit bot assignments but does not provide intelligent routing, fallback or inference capacity management. [Inference](https://docs.nvidia.com/openshell/how-it-works/inference).
3. **Strict boundaries need deliberate configuration.** Manual proposal review is the default, but optional automatic approval can grant access to new public hosts. L7 endpoint rules default to audit unless `enforcement: enforce` is specified. Attached provider profiles add network authority. A global policy replaces bot policies rather than intersecting with them. These are different controls and must all be checked. [Advisor](https://docs.nvidia.com/openshell/how-it-works/policies/advisor), [network rules](https://docs.nvidia.com/openshell/how-it-works/policies/network-rules), [policy selection](https://docs.nvidia.com/openshell/how-it-works/policies/overview).

**Recommended next step:** complete Experiment 1, a 90-minute compatibility and effective-policy review. Proceed to a synthetic two-bot pilot only if that review finds a useful bot role that can keep its current tool, privacy and network boundaries. No further model benchmarking is needed to make that decision.

## Method and current-state limits

The verified checkout is `/path/to/private-workspace`, remote `git@github.com:Running-Digitally/radhouse.git`, branch `fix/project-deploy-after-cancelled-review`, HEAD **`64c75cd8b6676226a148fb2efd83c30bc531daff`**. It was clean at initial inspection. I did not check out another branch, fetch, reset, install dependencies, run agents, contact deployed services, or modify runtime/configuration files.

No root `AGENTS.md` or `.agents/skills` directory exists in this Radhouse checkout. The global Codex instructions require exact repository/HEAD verification and bounded searches. Relevant product instructions were read in `PRINCIPLES.md`, architecture, runtime, configuration, Buzz, supervisor and work-model documents. The codex-session-retrieval skill was used to locate earlier session metadata without modifying transcripts.

The local checkout is **older than the newest retained deployment records**. Its README still describes incomplete early-development work. The private homelab change record contains later September 23 receipts for an opted-in private software-delivery path: public PRs 56 (`f672efb8`) and 57 (`2c90d89`) are recorded as merged and live on the controller, with schema 7 retained. These commits are newer than the inspected checkout. Source-grounded statements below describe this checkout; operational statements describe dated records, **not fresh live observation**. In particular, the earlier project plan's initial release summary is superseded by its related change record. A later integration task must verify its actual branch, deployed release and runtime profiles before changing anything.

Local memories were used as leads and checked against the newer qualification/decision records. The September 19 benchmark-framing memory predates the September 20 CWB-v1 qualification and is not the latest benchmark status. The originating delegation's thread ID was not found in the local session store; its requested scope is preserved from the delegation text, without inventing missing transcript content.

For OpenShell, I read current official documentation, verified the GitHub release API, and downloaded **version-pinned documentation and selected source/tests** for inspection only. The accompanying [provenance record](2026-09-30-nvidia-openshell-source-provenance.json) lists upstream paths, URLs, SHA-256 hashes and source/repository identities. Temporary upstream material is outside the repository. Upstream tests were inspected, not executed. No independent security audit, Radhouse/OpenShell integration result or fleet-performance measurement is claimed.

## What Radhouse already owns

| Concern | Current evidence | Consequence for OpenShell |
| --- | --- | --- |
| Durable worker identity | One persistent Linux VM and Hermes home per bot; the implemented runtime router selects its endpoint from durable bot ID. Missing routes become a bounded unavailable state. | Preserve bot identity and its persistent home. A sandbox name, provider name or runtime response must not select a different bot. |
| Management boundary | Accepted design: control VM for policy, task records and UI; operations VM for scoped credentials/lifecycle effects; persistent isolated worker VMs. | Another gateway is an additional trusted component, not a reason to merge existing privilege boundaries. |
| Task execution | `AgentWorkPort` requires capabilities, idempotent start/attach, result, exact-run stop, durable steering and approval. Hermes HTTP Runs API implements the runtime path. | A process-exec API alone cannot replace this contract. Initially keep Hermes inside any trial worker. |
| Durable orchestration | PostgreSQL transactions, task/attempt/dispatch/operation identities, optimistic state revisions and bounded coordinator cycles. | Keep authoritative application state in Radhouse; OpenShell resource state is execution evidence. |
| Concurrency | Accepted design permits overlapping non-conflicting sessions. The retained Builder profile deliberately admits one concurrent run. The coordinator advances a bounded list sequentially. | Separate bots can overlap; unlimited sessions within Builder are neither the current profile nor a free scaling gain. |
| Provider assignment | Each configured bot has one stable provider binding; task callers cannot override it. Capability discovery and actual served-model attribution belong to Radhouse. | OpenShell can authorize the endpoint; Radhouse/Hermes must retain exact model and capability decisions. |
| Buzz | Signed events, verified conversation/roster bindings, durable ingress/outbox deduplication, deterministic specialist handoffs and contextual steering. | Keep Buzz in the existing server adapter. Relay membership is not execution authority. |
| Protected effects | Exact artifact/revision/audience review and publication. The latest private record also describes an explicitly opted-in exact-preview → READY review → Deployer path for one project. | Do not turn sandbox success, model output or a policy proposal into permission to merge, deploy or publish. |
| Recovery | Retained bot files, controller state, runtime run IDs, restart reconciliation and uncertain-effect receipts. Backups and restores are separately qualified. | Sandbox restart must not relaunch a task or replay an external effect automatically. |

Primary code anchors: [`application/ports.py`](../src/radhouse/application/ports.py), [`application/coordinator.py`](../src/radhouse/application/coordinator.py), [`integrations/hermes.py`](../src/radhouse/integrations/hermes.py), [`application/runtime_controls.py`](../src/radhouse/application/runtime_controls.py), [`config.py`](../src/radhouse/config.py), [`composition.py`](../src/radhouse/composition.py). Product anchors: [architecture review](architecture-review.md), [Hermes contract](integrations/hermes.md), [configuration](configuration.md), [Buzz contract](integrations/buzz.md), [work model](work-model.md).

The September 22 Builder decision is particularly important. It rejects command-by-command approval and a new command broker for ordinary development. The guest's unprivileged identity, systemd restrictions, rootless Docker, external network boundary and project credential scope own containment. Hermes command denies are guardrails, with explicitly acknowledged limits where upstream branch protection is absent. OpenShell should improve a demonstrated external boundary, not recreate the rejected command-approval friction. [Local ADR-0073](../../private-installation-record).

The newest retained delivery evidence describes useful image-backed Builder work and private project coordination, with residual UX and recovery work. It does not prove a broadly released fleet or every accepted V1 requirement. OpenShell cannot close those gaps merely by starting containers. [Local completion/change record](../../private-installation-record), [project coordination plan](../../private-installation-record).

## Product identity, maturity and reproducibility

OpenShell is the NVIDIA project at `NVIDIA/OpenShell`: a policy-enforced execution runtime for agents such as Codex, OpenCode and Claude Code. It is not an agent's reasoning loop, a replacement chat client, a full personal computer manager or a model server. NVIDIA's current architecture separates an untrusted workload from a trusted supervisor, with a gateway managing resources and credentials. [Overview](https://docs.nvidia.com/openshell/about/overview), [architecture](https://docs.nvidia.com/openshell/about/architecture).

The release/support contract now distinguishes dev builds, nightly prereleases and qualified stable builds. Stable APIs receive patch compatibility; Experimental interfaces can change in a patch. The latest and preceding minor lines receive security/critical reliability maintenance at their newest patches. Use immutable release tags and image digests, with CLI, gateway, supervisor, drivers and SDK from the same release. Do not evaluate floating `main`, `dev` or `latest` and call the result v0.1.2 qualification. [Support contract](https://docs.nvidia.com/openshell/about/support-matrix).

There is credible implementation evidence beyond marketing: source tests cover stop/start state retention, direct-TCP denial, credential restrictions, VM overlays and recovery; the release pipeline defines conformance, upgrade, API and security gates. This is useful evidence of implemented mechanisms, but not a measurement of this homelab or proof that every Radhouse workload passes. The release-stability RFC still has `state: review` in its source front matter, so the published support matrix and actual stable release are stronger evidence of the current operator contract than that RFC label alone. [Release qualification specification](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/rfc/0014-release-stability/release-qualification.md), [release-stability RFC](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/rfc/0014-release-stability/README.md).

The 0.0 → 0.1 transition required recreating sandboxes, coordinated component upgrades and configuration/API migration. Older tutorials involving `openshell inference set`, image catalog aliases or `--from ./Dockerfile` are unsuitable for this proposal. That historical break is a migration-cost warning, not a claim that future patch releases require recreation. [Upgrade guide](https://docs.nvidia.com/openshell/upgrade/0-1-0).

## Capability comparison and security boundaries

### 1. Sandboxing and OS isolation

The current design mediates workload TCP/DNS through the trusted supervisor. The runtime creates an outer network fence: Docker/Podman workloads have networking off, Kubernetes uses a NetworkPolicy fence, and MicroVM guests have no network device. The workload is non-root with restricted syscalls; controls must be confirmed before it launches. Supervisor connection loss freezes the workload. These are materially stronger than asking an agent to honor proxy environment variables. [Architecture](https://docs.nvidia.com/openshell/about/architecture).

Docker and Podman still share the host kernel. They do not satisfy Radhouse's accepted separate-kernel per-bot VM boundary by themselves. OpenShell's MicroVM driver offers a VM boundary through libkrun, using KVM on Linux or Hypervisor.framework on macOS, but it is an OCI/rootfs-oriented environment rather than the existing Proxmox Linux guest lifecycle. No first-party Proxmox compute driver was found in the inspected built-in driver list. Nested virtualization availability, persistent disks, startup, monitoring and backup integration would need separate qualification. [Runtime drivers](https://docs.nvidia.com/openshell/how-it-works/sandboxes/runtimes), [driver interfaces](https://docs.nvidia.com/openshell/extensibility/drivers).

**Builder conflict:** mounting, namespace creation and related operations are restricted by the workload filter. Starting its rootless Docker daemon inside that workload is therefore unlikely to preserve the current development experience. Moving the daemon outside the boundary and exposing its socket lets its jobs act with the daemon's network/storage authority. Keeping that daemon in a dedicated bot VM could retain the VM boundary, but OpenShell would not thereby mediate every container job. Do not label this a fully enforced OpenShell worker. [Filter source](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-isolation-interface/src/linux/child_seccomp.rs), [Builder decision](../../private-installation-record).

A browser within a Linux workload may be feasible, but this review did not qualify Chromium's subprocess/shared-memory/user-namespace requirements against the actual image and filters. Native macOS/Windows application operation is not established by support for a host-side CLI. Stop a browser trial if it needs weakened sandbox controls, privileged mode or an external personal browser profile.

### 2. Files, persistence and lifecycle

OpenShell supports retained sandboxes: stop/start preserves workspace association, policy, attachments and services. The canonical process restarts as a **new process generation**. Reconnecting to a live terminal can keep the same process; stopping the sandbox cannot keep the agent's in-memory state. Use a long-lived Hermes service if a sandbox represents a persistent bot rather than one assignment. Do not set `--no-keep` on that bot. [Sandbox lifecycle](https://docs.nvidia.com/openshell/how-it-works/sandboxes/overview).

The shipped `sandbox_stop_start_preserves_workspace` test writes a sentinel, denies exec while stopped, checks the sentinel after start and confirms a second canonical-process launch. The VM driver also retains an overlay disk and a stop marker. These are real persistence mechanisms. They do not establish that every installed package, browser profile, Hermes SQLite state, workspace and project database is placed on storage retained by the selected driver. Build a path inventory and test it. [Lifecycle test](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/e2e/rust/tests/sandbox_lifecycle.rs), [VM driver state](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-driver-vm/src/driver.rs), [VM overlay test](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/e2e/rust/tests/vm_overlay.rs).

Docker/Podman named volumes and Kubernetes PVCs are available; caller-selected resources require explicit enablement and operator admission labels. Bind mounts require exceptions that disable resource admission and can bypass workspace isolation. For private bot data, use a distinct admitted volume or disk and independent backup/restore evidence. Keep other bots' disks, host home directories and management secrets unavailable. [Runtime mounts](https://docs.nvidia.com/openshell/how-it-works/sandboxes/runtimes), [external-resource admission](https://docs.nvidia.com/openshell/how-it-works/gateways/configuration).

Radhouse's backup set would grow to include gateway state, credentials/encryption material, worker data and an application-to-sandbox mapping. The default gateway database is SQLite with WAL and full synchronization; its docs require a database backup operation rather than copying the main DB file alone. Kubernetes HA uses external PostgreSQL but does not provide PostgreSQL HA or backups. [Gateway configuration](https://docs.nvidia.com/openshell/how-it-works/gateways/configuration), [HA](https://docs.nvidia.com/openshell/kubernetes/high-availability).

### 3. Policy and approvals

Filesystem and process settings are fixed after activation; network policies can update while running. A filesystem restriction change may require a new sandbox, so workspace continuity and identity must survive replacement. Use `landlock.compatibility: hard_requirement` for a trial claiming all configured filesystem controls; the default additional policy is `best_effort`, although the mandatory private-channel baseline still requires Landlock ABI 3. [Policies](https://docs.nvidia.com/openshell/how-it-works/policies/overview), [default and baseline paths](https://docs.nvidia.com/openshell/how-it-works/policies/default-policy).

Two important distinctions:

- A provider attachment contributes endpoints to the effective policy; base-policy denial is not the full resulting access envelope.
- A gateway global policy **replaces** sandbox policy and suppresses provider-derived policy. It is not a maximum boundary intersected with each worker policy.

Review base, effective and runtime-enriched access. Ordinary policy views omit some runtime-only certificate/GPU paths. This is why linting a handwritten policy alone is insufficient. [Selection/composition](https://docs.nvidia.com/openshell/how-it-works/policies/overview), [baseline paths](https://docs.nvidia.com/openshell/how-it-works/policies/default-policy).

The policy advisor is disabled by default; manual proposal review is also the default. Keep the global `proposal_approval_mode` at `manual`, and initially keep `agent_policy_proposals_enabled` false. OpenShell drafts rules from blocked requests even without the agent advisor enabled. Optional `auto` approval regards some new public destinations without credentials as low risk and may admit them. That directly conflicts with no automatic permission expansion. If advisor proposals later appear in Radhouse, approval must remain an exact human grant decision with current bot, scope and policy revision. [Advisor behavior](https://docs.nvidia.com/openshell/how-it-works/policies/advisor).

The standalone policy prover is a useful, independent concept. It checks whether a candidate stays within a boundary using an SMT model, without applying it. It covers filesystem/process/Landlock/L4/REST constraints; GraphQL, WebSocket, MCP and some path/glob/symlink-dependent comparisons are unsupported. Only `within_boundary` passes. A proposal-risk check is different from this boundary check. Neither proves that the runtime enforces the policy, that allowed actions are appropriate, or that a tool result is safe. [Prover](https://docs.nvidia.com/openshell/how-it-works/policies/prover).

### 4. Networking and credentials

OpenShell profiles bind credentials to endpoints and binaries; workloads see opaque placeholders and the supervisor substitutes secrets at approved destinations. Credential storage defaults to encrypted database envelopes with a separate encryption key, and external credential drivers are available. This could improve the acknowledged custody risk of direct role-scoped tokens, especially for read-only review. The gateway, supervisor, host and secret-storage administrator remain trusted. [Profiles](https://docs.nvidia.com/openshell/how-it-works/providers/profiles), [credential storage](https://docs.nvidia.com/openshell/how-it-works/gateways/configuration).

Explicitly set `protocol: rest` and `enforcement: enforce` for a REST boundary. Host/port access alone permits all methods and paths. Binary matching includes descendants, and interpreted tools must match their interpreter's real executable. Granting the main agent binary's ancestry is broad access for its tools, not a cryptographic statement that each child command has approved intent. TLS inspection also requires compatible trust configuration; TLS passthrough loses request inspection and credential substitution. [Network rules](https://docs.nvidia.com/openshell/how-it-works/policies/network-rules).

The v0.1.2 GitHub example is read-only for REST/GraphQL and clone/fetch, with push denied. It is a starting point rather than an automatically loaded profile. Copy it under a role-specific ID and narrow repository paths/binaries before use. Git smart-HTTP push uses a repository-level endpoint; allowing that endpoint is not equivalent to allowing only one branch. The GitHub push tutorial likewise should not be read as a branch-protection mechanism. Keep merge/workflow/deployment authority in the current exact-effect path or upstream controls. [GitHub example](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/providers/github.yaml), [push tutorial](https://docs.nvidia.com/openshell/tutorials/github-push-access).

Credential confinement blocks stealing the actual token; it does not prevent abusing all granted operations at its allowed endpoint. Broad public browsing/package access also remains a data-exfiltration route. Builder's broad public egress is an accepted personal-development tradeoff; replacing it with an ever-growing hostname allowlist would add interruption costs. Prefer a bounded role whose network needs are already narrow.

Provider detach/rotation and network revisions are dynamic, with `--wait` for application receipts. New environment placeholders require a new process. These mechanisms do not by themselves implement Radhouse's accepted bot-wide pause after grant withdrawal, revoke a browser session upstream, undo an already sent request or erase obtained data. Retain external revocation and uncertain-effect reconciliation. [Inference attachment lifecycle](https://docs.nvidia.com/openshell/how-it-works/inference), [Hermes recovery contract](integrations/hermes.md).

### 5. Local models and the PAIR boundary

OpenShell can admit a custom self-hosted native endpoint, including credentialless OpenAI-compatible use. This would work conceptually with a fixed Radhouse inference binding: a distinct profile declares the exact host/port/path and client binary; the workload retains its configured model. It does not require a GPU in every bot sandbox and does not accelerate an existing model server. Exact private-endpoint behavior must be tested without granting the entire LAN. [Inference](https://docs.nvidia.com/openshell/how-it-works/inference).

Keep administrator-owned per-bot model choice explicit. Do not introduce an automatic fallback or route a helper call to another endpoint. If the backing model of an existing alias changes, preserve Radhouse's capability revalidation, physical model attribution and visible waiting behavior. Endpoint authorization alone cannot assert that a specific physical model served the response.

The retained September 6 specialization report distinguishes model selection from eligible-host placement and parks the Switchyard/PAIR exploration. This report makes **no claim of a supported OpenShell↔PAIR integration**. The only verified overlap is the native model-endpoint contract: any separately qualified serving/routing layer could sit behind an explicitly selected endpoint, subject to identity and capability checks. The separate PAIR research session owns PAIR's current product/API evidence. [Existing local specialization report](../../private-installation-record).

### 6. Multiple agents, control-plane access and operational cost

OpenShell can manage many separately named sandboxes through APIs/SDKs, with resource limits for Docker/Podman and requests/limits for Kubernetes. A gateway selects one compute driver. VM sizing uses driver `vcpus`/`mem_mib`; generic sandbox CPU/memory flags do not change VM allocation. This is resource management, not task scheduling, fairness, collaboration or a measured fleet-capacity guarantee. [Runtimes](https://docs.nvidia.com/openshell/how-it-works/sandboxes/runtimes), [sandbox resources](https://docs.nvidia.com/openshell/how-it-works/sandboxes/overview).

The Python SDK matches Radhouse's stack and requires Python 3.11+. Its package is a gateway client, not the isolation runtime. Keep a narrow adapter rather than moving coordinator semantics into SDK calls. API mutation receipts help, but their confirmed replay window is 24 hours; unresolved admissions do not expire, and cancelling a client does not cancel admitted work. After that replay window, blindly reusing an ID can execute again. Keep Radhouse's durable operation records and resource-generation mapping authoritative. [Python SDK](https://docs.nvidia.com/openshell/sdk/python), [request admission and errors](https://docs.nvidia.com/openshell/sdk/api-errors).

OpenShell logical workspaces isolate resources/members, not filesystem directories. Workspace members have broad authority over resources within their assigned workspace; local gateways without OIDC role configuration treat authenticated callers as platform administrators. A direct human gateway login therefore does not preserve Radhouse's private-history/audience rules automatically. Begin with trusted operator access only; give no bot a CLI client credential. For shared deployment, decide the mapping of private bot/workspace and Radhouse service identity before admitting users. [Workspaces](https://docs.nvidia.com/openshell/how-it-works/workspaces), [authentication](https://docs.nvidia.com/openshell/how-it-works/gateways/authentication).

Kubernetes offers placement and multi-replica gateway HA, but adds a cluster, CNI enforcement, Agent Sandbox controller, PKI, storage, OIDC and another database/recovery path. That is a large migration cost for a small persistent-VM fleet. HA does not eliminate shared model contention. No measured maximum concurrent agents or inference throughput improvement for this installation was found. [Kubernetes setup](https://docs.nvidia.com/openshell/kubernetes/setup), [HA](https://docs.nvidia.com/openshell/kubernetes/high-availability).

Structured OCSF/security logs can be correlated with sandbox identity, but must respect Radhouse privacy/audience constraints and have protected collection/retention. Do not assume workload-visible files are tamper-proof audit storage. OpenShell's anonymous telemetry is enabled by default; an explicit trial can disable it using `OPENSHELL_TELEMETRY_ENABLED=false`. Third-party tools have their own telemetry. [OCSF export](https://docs.nvidia.com/openshell/observability/ocsf-json-export), [telemetry](https://docs.nvidia.com/openshell/observability/telemetry).

## Deployment choices and migration cost

| Choice | Benefit | Cost/changed guarantee | Recommendation |
| --- | --- | --- | --- |
| Reuse concepts in existing VM system | Review effective access, separate credential custody, preserve generation/operation receipts, add adversarial denial evidence. | Requires actual enforcement at the layer that owns each boundary; a copied YAML file provides none. | Adopt the review method immediately; implementation only for a demonstrated gap. |
| One OpenShell worker inside its own dedicated trial Linux VM | Keeps an outer OS boundary while testing enforcement for a narrower workload. | Adds gateway/supervisor storage, image packaging and recovery. Existing rootless Docker/browser compatibility is not guaranteed. | Leading direct-integration pilot. Keep other active bot VMs untouched. |
| OpenShell MicroVM per bot | Separate guest kernels with common runtime API. | Replaces full-VM provisioning/state/backup assumptions; host or nested virtualization and resource allocation must be qualified. | Later option if a repeatable measured VM-footprint problem justifies it. |
| Shared Docker/Podman worker host | More compact provisioning with quotas. | Shared-kernel bots change the accepted isolation guarantee. | Do not describe as equivalent to persistent bot VMs. |
| Kubernetes fleet | Scheduling, existing-cluster integration, HA and PVC options. | Highest component/operational cost; CNI/RBAC/PKI/storage misconfiguration can undermine containment. | Defer unless an already qualified cluster and real fleet-capacity requirement exist. |
| Custom Proxmox compute/isolation driver | Could retain exact guest lifecycle while exposing OpenShell APIs. | Security-critical extension, runtime protocol, readiness/fencing, version negotiation and ongoing maintenance. | No initial custom driver project. Revisit only after built-in pilot success exposes a specific missing contract. |

The integration should have one mapping: `Radhouse bot ID → admitted workspace/sandbox name + immutable sandbox ID/generation → Hermes home/run endpoint`. OpenShell public RPCs use names plus explicit workspace selection; keep the immutable ID/generation in Radhouse evidence to prevent same-name replacement confusion. Stop/delete one resource must not be interpreted as cancellation of every task, nor a new name as a new grant. [Workspace RPC identity](https://docs.nvidia.com/openshell/how-it-works/workspaces), [API semantics](https://docs.nvidia.com/openshell/sdk/api-errors).

For a first integration, retain the current Buzz → Radhouse → Hermes HTTP path. Let OpenShell create/fence the worker environment and provide only an admitted route to the worker listener. Its generic terminal attachment is useful for operator diagnosis; it does not supply Hermes's durable post-tool guidance receipts or exact allowed-tool contract. This division minimizes migration while exposing whether OpenShell provides a tangible boundary improvement.

## Platform and licensing check

The documented host matrix supports Linux amd64/arm64 and Apple Silicon macOS; Windows WSL2/Docker Desktop is Experimental. Intel macOS and native Windows isolation are not part of the selected supported pilot. Docker requires version 28.0+, Podman 5.x, and Kubernetes 1.29+; Linux workloads require enabled Landlock ABI 3 and qualified seccomp/task-memory facilities. Linux 6.2+ is the uncomplicated starting point, but kernel version alone is insufficient. Do not reduce security checks to make an older host start. [Support matrix](https://docs.nvidia.com/openshell/about/support-matrix).

Docker Desktop requires host networking and cannot use Enhanced Container Isolation for the documented driver path. This is a real workstation constraint. Prefer a separately approved disposable Linux trial over changing the daily driver's existing Docker setup. MicroVM requires host virtualization; placing it in a Proxmox guest additionally depends on nested virtualization that this research did not inspect live. [Runtimes](https://docs.nvidia.com/openshell/how-it-works/sandboxes/runtimes).

OpenShell and the local Radhouse checkout are Apache-2.0. Source reuse/distribution must preserve applicable license/notice obligations; this is not an NVIDIA hardware purchase requirement. Agent CLIs, model weights, downloaded images, dependencies and external services have separate licenses/terms. OpenShell's license does not qualify those artifacts or override existing Hermes/model restrictions. No third-party dependency license audit was performed. [OpenShell license](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/LICENSE), [Radhouse license](../LICENSE).

## Ranked, bounded experiments

All steps below describe **future work after separate authorization for the chosen environment and actions**. No command was run against a runtime during this research. Time budgets and success thresholds are proposed decision gates, not upstream performance promises. Stop rules end the experiment; they do not authorize a weaker policy or a different model.

### 1. Effective-policy and compatibility review — first, 90 minutes

**Question:** Is there a useful existing bot workload that OpenShell can contain without weakening its tool or privacy boundaries?

**Prerequisites:** immutable v0.1.2 source/docs; current Radhouse profile and grant inventory; operator-owned maximum boundary. The standalone prover must already be available in an approved tool environment, or its acquisition is a separate action. Do not install it during a documentation-only review.

**Steps:**

1. Inventory one candidate's writable paths, Hermes home/database, browser state, executable paths, model endpoint, allowed service operations and revocation behavior. Prefer review/evidence work with narrow network needs. Include descendant/interpreter access and startup/runtime-enriched paths.
2. Translate only those existing grants into a candidate policy and distinct role profiles. Use explicit `enforce`, `hard_requirement`, manual approval and no new provider. Do not use a global replacement policy as a boundary intersection.
3. Classify each tool against mandatory syscall controls. Mark Builder's nested Docker requirement incompatible unless a documented design preserves its existing outer boundary without claiming nonexistent mediation.
4. If available, run the independent check below on the **complete effective candidate**, including attached-provider rules. Create deliberate negative variants: an extra public endpoint, private range, writable path and API write. Review modeled coverage for each result.

```sh
openshell-prover check candidate-effective.yaml \
  --boundary owner-boundary.yaml --output json
```

5. Produce a compact coverage table: requirement, policy rule, enforcement layer, proof/unsupported reason, runtime probe needed. Nothing is applied. Unsupported GraphQL/MCP/hostname/path comparisons are explicit gaps, not passes.

**Pass:** one useful role retains its current tool set and audience; every permission is accounted for; all modeled candidate/negative checks behave as expected; no automated expansion. **Stop:** after 90 minutes, or immediately if the role requires privileged mode, an exposed management/container socket, broad host bind mounts, new LAN access or a custom driver. If only Builder fits the useful work and Docker is essential, park direct integration and retain the review findings.

**Decision unlocked:** select exactly one runtime/image and one candidate role for Experiment 2, or reject the integration without spending days packaging it.

### 2. Two retained, interactive workers — second, one three-hour session

**Question:** Can OpenShell improve isolation and lifecycle predictability while preserving interactive use and explicit model choice?

**Prerequisites:** Experiment 1 passes; a separately approved disposable Linux VM or qualified host, sufficient recorded headroom, an existing supported runtime, two synthetic bot identities, a prebuilt immutable image with the selected agent and no nested Docker requirement. Preserve an outer per-bot OS boundary if that is the acceptance claim. Use only previously approved model bindings; no model tuning or PAIR routing. No real Buzz channel, private repository or user data in this test.

**Steps:**

1. Pin all components to v0.1.2 and the image digest. Verify active gateway version/driver; record CPU/RAM/disk ceilings and actual model IDs. Disable telemetry in this trial deployment. Explicitly require manual approval and leave agent proposals off:

```sh
openshell gateway info
openshell settings set --global --key proposal_approval_mode --value manual --yes
openshell settings set --global --key agent_policy_proposals_enabled --value false --yes
```

2. Create two named retained workers with distinct admitted storage and an explicit policy. Keep each agent/service's canonical command alive. A generic lifecycle-only example follows; replace the digest and command with the already reviewed image/agent service for the interactive check:

```sh
openshell sandbox create --name trial-a --detach \
  --from registry.example.com/approved-agent@sha256:<approved-digest> \
  --policy trial-a.yaml --approval-mode manual -- sh -c 'exec sleep infinity'
openshell policy get trial-a --base
openshell policy get trial-a --full
openshell sandbox exec --name trial-a --no-login-shell -- \
  sh -c 'printf "trial-a-state\n" > /sandbox/retention-check'
openshell sandbox stop trial-a
openshell sandbox start trial-a
openshell sandbox exec --name trial-a --no-login-shell -- cat /sandbox/retention-check
```

3. Repeat for `trial-b`. Verify isolation against the other worker's sentinel and an operator-created secret canary. Denied probes must be rejected by policy, not merely fail because an endpoint is offline. Use an operator-controlled reachable synthetic HTTP service for network evidence.
4. Run one short real interactive task per worker: read a fixture, make a local draft, incorporate one correction before completion, then provide a final result. Run them concurrently for one overlapping interval. Keep each bot's fixed model visible, and record model identity/timing separately. No silent fallback.
5. Stop/restart A while B continues; verify A's Hermes state, workspace and browser profile if applicable. Verify the old runtime generation cannot be reused and B is unaffected. Simulate one gateway connection interruption; inspect visible waiting/freeze/recovery and reconcile the original work instead of creating a duplicate.
6. On a synthetic local-effect task, lose one acknowledgment and confirm the same Radhouse dispatch/operation identity cannot cause another write. This is an adapter qualification check, not an assumption supplied by OpenShell's exec stream.

**Pass:** both tasks finish with the correction; no cross-bot data access or unintended endpoint is admitted; A's declared persistent state survives; B stays usable; no duplicated effect or automatic model/policy change. Provisional UX gate: no more than 20% added end-to-end time against a matched short control task, and no unexplained control/steering delay above five seconds. Record model wait separately so model contention is not falsely attributed to OpenShell. A single matched pair screens feasibility; it is not a performance benchmark.

**Stop:** one three-hour session; any false allow, missing state, cancellation of B, runtime-required weakening or repeated packaging workaround ends the trial. Browser incompatibility is reported rather than fixed using disabled browser sandboxing. If timings are ambiguous, retain the observations and make an explicit follow-up decision; do not launch a benchmark sweep.

**Decision unlocked:** a limited Hermes environment adapter, or a documented rejection. The measured result does not increase Builder's concurrency or qualify unattended operation.

### 3. Endpoint-bound review credentials — third, 90 minutes, only after a usable worker

**Question:** Does OpenShell remove meaningful credential exposure while preserving the reviewer's useful read-only workflow?

**Prerequisites:** Experiment 2 passes; an operator-controlled fake API and synthetic secret; then, only if separately admitted, a disposable private test repository and read-only token. Never test first with Builder's live token or production Deployer credential. The profile and exact endpoint/binary scope must already be reviewed.

**Steps:**

1. Import a distinct reviewed profile with `enforcement: enforce`, exact client paths and narrow repository/API paths. Bind the synthetic secret through a provider; do not use plaintext `--env SECRET=...`.
2. Attach it only to the intended worker, use `--wait`, and launch a new process so it receives the placeholder. Inspect base/effective policy and provider attachment receipts.
3. From the worker, inspect its environment and readable files: only the placeholder may appear. On the fake upstream, verify substitution occurs at the exact authorized request. At an unauthorized host/path, confirm both denial and absence of the real secret.
4. Exercise reads plus forbidden POST/DELETE and a disallowed binary. Do not infer an L7 denial from a 401/404 returned by upstream. Record the policy denial and protected target state.
5. Detach with `--wait`, start another request and prove it is denied; keep the upstream count of already completed requests. A previously sent request may complete. Link the result to Radhouse's bot-wide pause/revocation contract.

```sh
openshell profile lint -f reviewer-test-profile.yaml
openshell profile import -f reviewer-test-profile.yaml
# Operator creates the synthetic provider from a protected credential source.
openshell sandbox provider attach trial-a reviewer-test --wait
openshell sandbox provider list trial-a
openshell policy get trial-a --full
openshell sandbox provider detach trial-a reviewer-test --wait
```

**Pass:** useful reads succeed, forbidden writes/binaries/destinations fail, the actual credential is absent from workload-readable state, and new requests fail after confirmed detach. **Stop:** 90 minutes or any leak/false allow. Do not broaden methods, enable uninspected credentials or disable enforcement to complete the exercise.

**Decision unlocked:** replace one narrow read-only credential path. It does not authorize Git push, merge, deployment or substitution for the existing operations broker.

## CWB and measurement discipline

CWB-v1 is already qualified for a manual attended two-lane policy: Qwen3.8/OpenCode for appropriate browser/evidence-review work when latency is acceptable; Sol/Codex for time-bounded code repair and strict visual deliverables. It does not qualify a universal default or unattended queue. The retained targeted coding repetition already answered its stopping question. [Local CWB-v1 recommendation](../../private-installation-record).

OpenShell changes the execution boundary. The proposed trials ask whether known useful interactive work survives that change. They do not reopen model/harness quality, thinking-depth tuning or a many-cell benchmark matrix. Record exact physical model, harness, image, policy, task shape and time window. Never pool timings across models behind a switched alias. That respects the verified local memory and keeps the experiment tied to a concrete integration decision.

## Uncertainty, stopping posture and final recommendation

High confidence: exact product/release/license identity; current policy/inference model; retained sandbox lifecycle; mandatory syscall conflict with nested rootless container development; existing Radhouse task/Buzz ownership.

Moderate confidence: a narrower Hermes worker could use a standard OCI image and endpoint-bound credentials without large application changes. This is an architectural inference; no such integration was executed.

Unestablished: local kernel/runtime compatibility, browser operation, OS/installed-tool persistence, actual resource savings, two-bot inference latency, deployment-private workspace mappings, nested MicroVM suitability, current live releases beyond the dated records, and any OpenShell/PAIR adapter. Missing evidence is not permission to relax a boundary.

Proceed with **Experiment 1 only** as the next decision. If it finds a viable narrow role, schedule the single interactive pilot. Keep Builder's qualified VM-local workflow and the existing Buzz/controller path intact while evaluating. Stop if the work becomes custom-driver development, repeated security exceptions or multi-day tuning without a measurable boundary or operator-experience gain.

## Source ledger

All external sources were accessed **2026-09-30 UTC**. Current rendered documentation was checked against the v0.1.2 source where material. The provenance JSON contains the complete downloaded-file hash ledger; below are the main decision sources.

| Source | What it establishes |
| --- | --- |
| [NVIDIA/OpenShell](https://github.com/NVIDIA/OpenShell) and [v0.1.2 release](https://github.com/NVIDIA/OpenShell/releases/tag/v0.1.2) | Product identity, tagged source and release date. |
| [Overview](https://docs.nvidia.com/openshell/about/overview), [architecture](https://docs.nvidia.com/openshell/about/architecture) | Gateway, trusted supervisor and workload fence. |
| [Support matrix](https://docs.nvidia.com/openshell/about/support-matrix) | Release contract, platforms, prerequisites, active kernel checks. |
| [0.1 upgrade](https://docs.nvidia.com/openshell/upgrade/0-1-0) | Historical breaking migration and stale-tutorial hazards. |
| [Sandbox management](https://docs.nvidia.com/openshell/how-it-works/sandboxes/overview), [runtimes](https://docs.nvidia.com/openshell/how-it-works/sandboxes/runtimes) | Retention, canonical processes, resources, mounts and drivers. |
| [Policy overview](https://docs.nvidia.com/openshell/how-it-works/policies/overview), [default policy](https://docs.nvidia.com/openshell/how-it-works/policies/default-policy) | Composition, global replacement and runtime baselines. |
| [Network rules](https://docs.nvidia.com/openshell/how-it-works/policies/network-rules), [security controls](https://docs.nvidia.com/openshell/security/best-practices) | L4/L7 distinction, audit/enforce, binary ancestry and syscall restrictions. |
| [Advisor](https://docs.nvidia.com/openshell/how-it-works/policies/advisor), [prover](https://docs.nvidia.com/openshell/how-it-works/policies/prover) | Manual/automatic proposals and modeled proof limits. |
| [Profiles](https://docs.nvidia.com/openshell/how-it-works/providers/profiles), [providers](https://docs.nvidia.com/openshell/how-it-works/providers/overview) | Endpoint-bound placeholders, profile operations and credential custody. |
| [Inference](https://docs.nvidia.com/openshell/how-it-works/inference) | Native endpoint/client model choice and removed shared route. |
| [GitHub profile source](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/providers/github.yaml), [push tutorial](https://docs.nvidia.com/openshell/tutorials/github-push-access) | Read-only profile and Git transport scope. |
| [Workspaces](https://docs.nvidia.com/openshell/how-it-works/workspaces), [gateway authentication](https://docs.nvidia.com/openshell/how-it-works/gateways/authentication) | Resource roles and local-admin default. |
| [Gateway configuration](https://docs.nvidia.com/openshell/how-it-works/gateways/configuration) | SQLite/credential backup and resource admission. |
| [Extensibility](https://docs.nvidia.com/openshell/extensibility/overview), [drivers](https://docs.nvidia.com/openshell/extensibility/drivers) | SDK/driver distinction and custom integration burden. |
| [Python SDK](https://docs.nvidia.com/openshell/sdk/python), [API errors](https://docs.nvidia.com/openshell/sdk/api-errors) | Application integration, uncertain mutations and replay expiry. |
| [Kubernetes setup](https://docs.nvidia.com/openshell/kubernetes/setup), [HA](https://docs.nvidia.com/openshell/kubernetes/high-availability) | Scheduling prerequisites and external PostgreSQL requirement. |
| [OCSF export](https://docs.nvidia.com/openshell/observability/ocsf-json-export), [telemetry](https://docs.nvidia.com/openshell/observability/telemetry) | Logging, privacy and telemetry opt-out. |
| [Lifecycle tests](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/e2e/rust/tests/sandbox_lifecycle.rs), [TCP bypass test](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/e2e/rust/tests/bypass_detection.rs), [credential gating tests](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/e2e/rust/tests/credential_gating.rs) | Concrete shipped assertions; not locally executed results. |
| [VM driver](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-driver-vm/src/driver.rs), [overlay test](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/e2e/rust/tests/vm_overlay.rs), [restart test](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/e2e/rust/tests/local_driver_token_restart.rs) | Stored VM state and scoped restart evidence. |
| [Workload seccomp source](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/crates/openshell-isolation-interface/src/linux/child_seccomp.rs) | Direct implementation evidence for compatibility constraints. |
| [Release qualification](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/rfc/0014-release-stability/release-qualification.md), [Apache-2.0 license](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/LICENSE) | Declared release gates and source reuse terms. |

Local evidence is linked near its claims. Private operational records remain outside this repository; this report omits credential values, private financial content, addresses, user-event payloads and raw transcripts. Their links require the adjacent private documentation checkout. The exact Radhouse source baseline and document hashes are retained in the provenance record.
