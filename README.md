# Radhouse

**A home for your agents. On your infrastructure.**

Radhouse is a self-hosted platform being built for persistent AI agents: agents
that retain their workspaces, work on useful assignments, and collaborate within
permissions you control.

**Status: design and development.** This repository currently contains the
product direction, principles, and release plan. There is no installable Radhouse
release yet. The features below describe the intended version 1.0, not a tested
or deployed system.

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
  disclosed supervision, shared projects, and human-reviewed publication.
- **Self-hosted inference:** a documented compatible API and explicit provider
  selection, with stable agent identity across supported model changes.
- **Bounded collaboration:** subtasks for existing project agents and schedules
  configured by people, with shared limits and visible reporting lines.
- **Optional shared services:** Buzz chat, receive-only bot mail, and bundled
  or existing-provider SSO; optional guided Cloudflare Access and Tunnel setup.

These are release requirements. Runtime compatibility, isolation, recovery,
network profiles, and shared-service integrations still need qualification.

## Read the plan

- [Product and security principles](PRINCIPLES.md): the rules that guide design
  choices and the limits those choices must make visible.
- [Version 1.0 roadmap](ROADMAP.md): the intended boundaries, delivery sequence,
  and evidence needed before a usable release.

Feedback and design proposals are welcome through this repository's issues and
pull requests. Use synthetic examples when describing a deployment. Keep
credentials, private conversations, and installation-specific configuration out
of public contributions.

## License

Radhouse's original work is licensed under [Apache-2.0](LICENSE). Dependencies,
agent runtimes, model weights, and other upstream materials retain their own
licenses and notices. The project license does not license a user's private
conversations or deployment data.
