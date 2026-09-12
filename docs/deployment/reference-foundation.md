# Reference deployment foundation

This is the reusable handoff from the first Proxmox preparation. It defines the
guest roles and readiness checks that Radhouse will build on without publishing
an installation's hostnames, addresses, credentials, storage layout, or recovery
receipts. It is also usable when an operator supplies suitably isolated Linux
VMs instead of asking Radhouse to provision them.

**Status:** the five guest roles below have passed operating-system preparation
and isolated guest recovery in the initial private deployment. Radhouse, Hermes,
Authentik, and Buzz have not yet been installed or qualified on those guests.
The table is a tested starting allocation, not a release minimum.

| Guest role | Starting allocation | Boundary |
| --- | --- | --- |
| Control | 2 vCPU, 4 GiB RAM, 64 GiB disk | Radhouse API, coordinator, and PostgreSQL control state |
| Operations | 2 vCPU, 2 GiB RAM, 32 GiB disk | Narrow infrastructure and service executors; no agent workloads |
| Identity | 2 vCPU, 4 GiB RAM, 32 GiB disk | Optional Authentik and its database |
| Buzz | 4 vCPU, 8 GiB RAM, 128 GiB disk | Optional collaboration services and retained media |
| Bot | 2 vCPU, 4 GiB RAM, 64 GiB disk | One persistent Hermes agent, browser, tools, and workspace |

Measure CPU, memory, working storage, backup storage, and restore staging before
creating guests. A preflight refusal is preferable to oversubscribing the host.
Inference capacity is measured separately: an idle guest and a simultaneous
model generation are different loads.

## Common guest contract

Every prepared guest should provide:

- a maintained Linux release, synchronized time, `systemd`, SSH restricted to
  the operator's management path, and a functioning guest agent;
- host or network firewall policy outside the agent's control;
- bounded logs and monitoring that do not copy task content or credentials;
- automatic weekly operating-system updates and restarts, with advance notice
  to Radhouse and a fixed grace period for saving work;
- an explicit resource allocation and storage ceiling; and
- a documented backup set and isolated restore check before retained work is
  admitted.

Docker Engine and Compose belong on the shared application guests that need
them. Their presence does not give the web process, Hermes user, or bot access
to the Docker socket. Hermes may run directly under an unprivileged service
account inside its bot VM.

## Readiness states

Keep these states distinct in automation and in the operator interface:

1. **OS ready:** the guest boots, can be patched and monitored, and has passed a
   guest-level recovery check.
2. **Application ready:** the pinned application starts with its intended user,
   resource, network, secret, and persistent-state boundaries.
3. **Integration ready:** the end-to-end caller, identity, recovery, revocation,
   and failure cases pass for the selected Radhouse release.

An OS-ready guest is a target for qualification, not permission to carry private
work. When an application is installed, replace any empty-guest maintenance or
backup marker with the application's work-aware preparation and recovery logic;
do not create an update or protection gap during that transition.

## Public configuration and private overlays

Public configuration should name roles and capabilities, use synthetic examples,
and refer to secrets by identifier. A private deployment overlay supplies exact
hostnames, addresses, storage pools, certificate names, secret locations, and
backup targets. Installation code must validate the merged configuration and
must not require private values to be committed to this repository.

The deployment handoff for each guest records the image and package versions,
resource limits, allowed callers and destinations, maintenance policy, persistent
paths, recovery coverage, and sanitized verification locators. Missing evidence
is reported as unavailable; it is never inferred from a running VM.

The component contracts for the next qualification step are:

- [Hermes runtime](../integrations/hermes.md)
- [Authentik identity](../integrations/authentik.md)
- [Buzz collaboration](../integrations/buzz.md)
