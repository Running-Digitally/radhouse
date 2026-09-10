# CI setup and local runners

Status: accepted V1 direction; implementation, numerical capacity thresholds,
runner lifecycle, and security qualification remain outstanding.

When an administrator enables GitHub software-development features, offer a
guided choice of where automated repository checks run. Default new CI setups
to GitHub-hosted runners. Offer local hosting after deterministic suitability
checks, and enable it only after the selected profile passes qualification.
This applies the product's flexible-but-opinionated principle to CI hosting.

## A setup choice at the right moment

Use the prompt **Where should automated code checks run?** Explain that these
checks test proposed changes and can execute contributor-controlled code.

| Choice | Plain-language explanation |
| --- | --- |
| GitHub-hosted — default | GitHub provides the test computers. No local runner pool is required. Repository visibility, plan limits, and storage affect cost. |
| On my infrastructure — conditional | Radhouse provisions disposable test VMs on a qualified local target. Show the measured resource budget, maximum concurrency, maintenance responsibility, and isolation status before setup. |

Keep this in administrator onboarding and GitHub integration settings. Operators
using assigned bots should not have to choose runner infrastructure. Research-only
installations can skip GitHub/CI setup and still use their fleet. Portainer is an
optional administrator runbook/profile, not a fleet or runner prerequisite.

Store an installation default for new CI setups, with explicit administrator
selection per repository. Existing workflows, runner selections, required checks,
and deployment arrangements remain in place. Attaching a repository does not
authorize replacing its CI. Preview any proposed workflow or runner-routing
change for review under that repository's existing rules.

The choice is changeable later. Apply an admitted change to future jobs after
draining the affected pool; show changes to data location, permissions, cost,
and resource limits. Bots cannot change this preference or silently fall back
between local and GitHub-hosted execution. A local outage or capacity loss queues
or blocks affected work with a clear reason.

## Preflight and activation

Start with bounded read-only evidence from the administrator-selected target and
existing authorized sources. Do not scan unrelated networks, request broad root
access merely to offer the choice, or provision a VM during discovery. Missing,
stale, contradictory, or unsupported evidence is not a pass.

| Check | Required evidence |
| --- | --- |
| Capacity | Available RAM after host, fleet, and service reserves; CPU load/pressure; healthy storage and space for the template, concurrent guest disks, image layers, build growth, logs, and cleanup overlap. Include shared-host demand and existing commitments. |
| Lifecycle | A supported mechanism to create a fresh guest per job, establish unique identity, remove registration, and destroy guest state after success, failure, cancellation, or interruption. |
| Isolation | Network and resource restrictions enforced outside the job guest; denied private/management reachability, no host/shared Docker socket, and no unrelated infrastructure/bot credentials or private shared caches. |
| Software | Qualified OS, template, runner, and Docker versions; required workflow/build compatibility and a maintained image-refresh policy. |
| Authority | Exact repositories, job trust class, pool target, concurrency/budgets, registration scope, and narrowly bounded lifecycle access. Bot repository access does not confer infrastructure or CI administration. |

Calculate a conservative proposed pool size from a declared and measured job
profile, including peak use and safety reserves. Report assumptions and evidence
age. Total host RAM or a momentarily idle CPU cannot establish usable capacity.
Do not invent a universal resource minimum before qualification.

Show useful states: **Not checked**, **Capacity available — validation needed**,
**Unavailable — explanation**, and **Ready to enable**. A capacity pass can offer
local setup; it cannot call the pool safe or enable job routing.

After the administrator reviews the concrete target, access, limits, and cleanup
plan, a bounded activation flow may run a disposable canary within that approved
scope. Verify actual deny paths, supported Docker workflows, cleanup and failure
recovery, and absence of credential/workspace carryover. Only a complete pass
allows enabling the pool. Reuse this admitted policy for ordinary jobs; do not
require repeated approval for every job already within scope. Drift or expansion
requires a new decision appropriate to the changed authority.

Recheck fresh capacity and critical readiness before each provisioning wave.
Configuration changes invalidate affected evidence. Pressure or failed cleanup
stops new admission; do not weaken reserves, reuse a dirty guest, or silently
switch provider. Show the administrator the reason and available remedy.

## Local execution boundary

The first local profile uses Proxmox VMs with Docker and the required runner
toolchain preinstalled in a clean, versioned template. Each job gets a fresh VM;
the whole guest is destroyed afterward. Share image-build recipes where useful,
but never run public CI inside a persistent bot or shared-service VM.

Treat the guest as job-controlled when it can control Docker. Keep Proxmox and
GitHub registration management credentials outside it, and provide only scoped
one-job bootstrap material. Enforce network policy outside the guest, including
IPv4/IPv6 and alternative paths. Runner labels alone do not enforce access.
Jobs receive only the repository-scoped permissions required for their admitted
checks, including authorized checkout of a private repository where applicable.
Repository publication, release, and deployment authority remain separate.
Collect bounded logs/results as untrusted evidence; do not promote artifacts or
writable caches into a privileged workflow merely because tests passed.

A supplied Linux bot VM does not by itself qualify as a local CI backend. Offer
that path only if a separately qualified external lifecycle can recreate clean,
isolated one-job guests. Otherwise explain why local CI is unavailable and keep
GitHub-hosted checks available subject to repository policy and authorization.

An optional Portainer profile must keep its management API and credentials out
of job reach, scope it to the CI environment, and qualify its Docker configuration.
It does not replace lifecycle, isolation, or cleanup enforcement.

## Radhouse development and deployment records

Radhouse's own public repository follows the GitHub-hosted default. Real Proxmox,
supplied-VM, maintenance, recovery, and inference integration tests still need
separately admitted environments and exact reviewed candidates. Neither successful
CI nor this setup preference authorizes a deployment or a privileged follow-on job.
CI placement does not change self-hosted fleet operation or local inference.

Publish generic contracts, supported-profile limitations, portable test commands,
synthetic examples, and product ADRs here. Keep deployment overlays, topology,
operational evidence, and local deviation ADRs in separately access-controlled
private repositories. Private decisions reference the public version, describe
the difference and its consequences, and record validation and review triggers.
Public setup and CI must remain usable without those private records.

## Qualification and source evidence

Acceptance includes honest unavailable/unknown states, capacity reserves and
concurrent admission, failed cleanup and interrupted activation, denied management
access, no job-state carryover, unchanged existing repository workflows, and safe
later preference changes. Local hosting is a release target, not a capability
established by this document or by a capacity check alone.

GitHub documents one-job ephemeral registration and the separate need for cleanup
in its [runner reference](https://docs.github.com/en/actions/reference/runners/self-hosted-runners).
Its [security guidance](https://docs.github.com/en/actions/reference/security/secure-use)
warns about untrusted contributions on self-hosted runners and privileged workflows.
[Docker security](https://docs.docker.com/engine/security/) explains daemon authority;
[Portainer installation](https://docs.portainer.io/start/install-ce/server/docker/linux)
documents socket access and rootless limitations. These sources inform the design,
not proof of the integrated boundary.

Standard GitHub-hosted compute is currently free for public repositories; private
repositories have plan-dependent allowances, and larger runners/storage have
separate charges or limits. Show current terms instead of promising free service
for every setup. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

Related: [principles](../PRINCIPLES.md), [roadmap](../ROADMAP.md),
[work model](work-model.md), and [observability](observability.md).
