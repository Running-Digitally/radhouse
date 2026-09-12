# Radhouse

**A home for your agents. On your infrastructure.**

Radhouse is a self-hosted platform being built for persistent AI agents: agents
that retain their workspaces, work on useful assignments, and collaborate within
permissions you control.

**Status: early development.** The first offline controller slice is implemented:
a durable task can survive a controller crash and receive a reviewed publication
through two simulated operator channels. The local PostgreSQL proof passes 111
tests. There is no installable fleet release yet; the features below remain the
intended version 1.0.

## Why Radhouse?

Running an agent in a dedicated VM is a useful beginning. Managing several
agents introduces more questions: who can use them, what they can access, how
they share work, which tasks need attention, and how to keep their environments
useful between assignments.

Radhouse aims to make that everyday experience obvious while giving the person
running the infrastructure explicit, inspectable controls. It is for tinkerers,
self-hosting enthusiasts, homelab operators, and people who care about security.
The people using assigned agents should not need infrastructure expertise.

The name combines **RAD — Running Agents Digitally** — with a welcoming home for
your agents. Say **RAD-house**. Radhouse is a project by **Running Digitally**.

## Flexible by design. Opinionated by default.

The recommended path should work as a coherent whole. Documented configuration
and extension points should let people adapt it without editing generic
installation scripts or silently changing its security guarantees.

Our version 1.0 direction includes:

- **Persistent agents:** a Linux VM for each agent, with retained files, tools,
  and workspace; Hermes as the first supported agent runtime.
- **Two deployment paths:** guided Proxmox provisioning and installation into
  suitably isolated Linux VMs supplied by the operator.
- **An approachable control plane:** administrator, operator, and viewer roles;
  a simple operator work home with assigned agents, current work, and a clear
  **Start a task** action. Projects, progress, and requests for help stay close
  to the work.
- **Useful software work:** fine-grained GitHub access, mediated by default;
  explicitly granted direct scoped tokens as an advanced option. Humans retain
  merge approval.
- **Private and shared work:** private agents by default, explicit sharing,
  disclosed supervision, operator-owned projects, and human-reviewed publication.
- **Proactive assistance:** Guardian Angel and Cognitive Amplifier behaviors
  notice what matters and prepare useful briefings, options, and local drafts
  within human-enabled assignments, with controlled interruptions and clear scope.
- **Understandable boundaries:** visible work context, audience, and bot access;
  reusable bot/project/task starters and changeable naming preferences.
- **Security and maintenance oversight:** scoped security findings, update
  checks, and automatic weekly OS updates with planned restarts, advance notice,
  and work preservation; other changes use separately reviewed maintenance plans.
  Security takes precedence at the deadline; an unready bot cannot postpone
  admitted maintenance indefinitely.
- **Useful observability:** local-by-default telemetry, logs, and analytics for
  work progress, fleet health, security evidence, and verified maintenance.
- **Hybrid recovery:** portable application/data backups plus optional complete
  bot-computer protection through existing infrastructure; qualify Proxmox and
  NAS-backed workflows first while retaining the supplied-Linux-VM path.
- **Recent-work protection:** tiered recovery targets admitted only after
  deterministic capacity/performance checks; short retention and explicit storage
  budgets take priority over extensive historical snapshot browsing.
- **Self-hosted inference:** a documented compatible API and explicit provider
  selection, with stable agent identity across supported model changes.
- **Bounded collaboration:** subtasks for existing project agents and schedules
  configured by people, with shared limits and visible reporting lines.
- **Optional shared services:** Buzz chat, receive-only bot mail, and bundled
  or existing-provider SSO; optional guided Cloudflare Access and Tunnel setup.

These are release requirements. Runtime compatibility, isolation, recovery,
network profiles, and shared-service integrations still need qualification.

## Run the first controller proof

With Python 3.14, uv, and a running local Docker daemon:

```sh
uv sync --locked
uv run python scripts/vs0.py verify
```

This creates one disposable PostgreSQL fixture, demonstrates recovery in both
simulated Radhouse/Buzz directions, runs the tests, and removes its owned test
container and volume. It uses synthetic identities and fake agent/model/service
adapters. See [the demo guide](docs/vs0-demo.md) for prerequisites, resource limits,
evidence, and the remaining integration work.

## Read the plan

- [Architecture and first-slice review](docs/architecture-review.md): the proposed
  system structure, accepted boundaries, and the implemented offline slice.
- [VS1-B useful-task pilot](docs/vs1b-pilot.md): the next implementation slices
  for durable Hermes execution, the TypeScript work home, and real Buzz parity.
- [Reference deployment foundation](docs/deployment/reference-foundation.md):
  reusable Proxmox or supplied-VM roles, readiness states, and handoff evidence.
- Integration profiles for [Hermes](docs/integrations/hermes.md),
  [Authentik](docs/integrations/authentik.md), and
  [Buzz](docs/integrations/buzz.md): pinned qualification candidates, boundaries,
  recovery requirements, and the evidence still needed before a live pilot.
- [Product and security principles](PRINCIPLES.md): the rules that guide design
  choices and the limits those choices must make visible.
- [Version 1.0 roadmap](ROADMAP.md): the intended boundaries, delivery sequence,
  and evidence needed before a usable release.
- [Work model](docs/work-model.md): the accepted direction for persistent bots,
  projects, finite tasks, reusable starters, and an optional Chief of Staff.
- [Proactive assistance](docs/proactive-assistance.md): standing assignments,
  prepared briefings, attention controls, and scoped bot-to-operator communication.
- [Mail and account security](docs/mail-and-account-security.md): human-controlled
  security mail and explicitly scoped verification/sign-in automation.
- [CI setup and local runners](docs/ci-and-runner-setup.md): GitHub-hosted defaults,
  guided administrator setup, and preflight-qualified local execution.
- [Boundary experience](docs/boundary-experience.md): make context, audience,
  access, and sharing understandable at the point of use.
- [Security supervisor](docs/security-supervisor.md): security oversight,
  component maintenance, and the proposed limits on update execution.
- [Naming preferences](docs/naming-preferences.md): four presets, themes,
  individual overrides, and permanent identity beneath editable names.
- [Telemetry, logs, and analytics](docs/observability.md): scoped evidence for
  progress, diagnosis, security, maintenance, and resource use.
- [Backup and restore](docs/backup-and-restore.md): the hybrid recovery model,
  first deployment focus, coverage, encryption, and safe restoration.

Feedback and design proposals are welcome through this repository's issues and
pull requests. Use synthetic examples when describing a deployment. Keep
credentials, private conversations, and installation-specific configuration out
of public contributions.

## License

Radhouse's original work is licensed under [Apache-2.0](LICENSE). Dependencies,
agent runtimes, model weights, and other upstream materials retain their own
licenses and notices. The project license does not license a user's private
conversations or deployment data.
